# Собирает релиз: installer\Output\Tf2SkinGenerator-Setup.exe и рядом
# Tf2SkinGenerator-portable.zip.
#
# Установщик обязателен: внутри него лежит само приложение, и по нему работает
# обновление из приложения — оно ищет в релизе файл с таким именем (ASSET_NAME
# в src\services\update_checker.py), качает, сверяет SHA-256 и запускает тихо.
# Zip — та же сборка для тех, кто не хочет ставить: распаковал и запустил.
# Обновляется он тем же установщиком в портативном режиме (см. /PORTABLE в
# installer\Tf2SkinGenerator-bundle.iss), поэтому второго файла апдейтеру не
# нужно; отличает портативную копию файл-маркер PORTABLE в корне zip.
#
# Запуск:
#   .\build-release.ps1                 спросит версию (Enter — оставить как есть)
#   .\build-release.ps1 -Version 1.0.4  без вопросов
#   .\build-release.ps1 -SkipDeps       не трогать пакеты в .venv (быстрее)
#
# Чего скрипт НЕ делает намеренно: не трогает папку dist\ (там лежат ваши
# прошлые сборки и резервные копии) и ничего никуда не выкладывает.

[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"

$AppName      = "Tf2SkinGenerator"
$Root         = $PSScriptRoot
$VenvPython   = Join-Path $Root ".venv\Scripts\python.exe"
$SpecFile     = Join-Path $Root "$AppName.spec"
$VersionFile  = Join-Path $Root "src\shared\version.py"
$IssFile      = Join-Path $Root "installer\$AppName-bundle.iss"
# Промежуточные папки — свои, чтобы не задеть dist\ с прошлыми сборками.
$PayloadDir   = Join-Path $Root "build\release\$AppName"
$WorkDir      = Join-Path $Root "build\release-work"
$SetupPath    = Join-Path $Root "installer\Output\$AppName-Setup.exe"
$ZipPath      = Join-Path $Root "installer\Output\$AppName-portable.zip"

# Что из tools\ в релиз НЕ идёт.
#
#   temp, temp_vmt_extract, temp_vmt, backupVMT, edited_vmt
#       скретч: их наполняет само приложение в рантайме, и это десятки
#       мегабайт остатков прошлых сборок.
#   mod_data
#       кэш, а не исходник. Единственный файл там — crit.pcf, и он НЕ наш:
#       приложение делает его из стокового particles/crit.pcf установленной у
#       человека TF2 (см. CritPcfService). Класть его в релиз значило бы
#       распространять контент Valve — ровно то, ради чего сервис и написан.
#       Плюс приложение читает mod_data из папки ДАННЫХ, так что копия рядом
#       с .exe всё равно не читается.
#   Model
#       место, куда ЧЕЛОВЕК кладёт свою модель для сцены крита. В репозитории
#       там только .gitkeep, а искать её приложение теперь тоже будет в папке
#       данных. Девять пустых каталогов в установщике не нужны.
$ToolsExclude = @('temp', 'temp_vmt_extract', 'temp_vmt', 'backupVMT',
                  'edited_vmt', 'mod_data', 'Model')

function Fail($message) {
    Write-Host "ОШИБКА: $message" -ForegroundColor Red
    exit 1
}

function Step($number, $text) {
    Write-Host ""
    Write-Host "[$number] $text" -ForegroundColor Cyan
}

# PyInstaller и ISCC пишут ход работы в stderr. При $ErrorActionPreference =
# "Stop" PowerShell 5.1 считает КАЖДУЮ такую строчку ошибкой и валит скрипт на
# первой же — хотя команда отработает успешно. Поэтому на время внешнего
# вызова переключаемся на Continue, а успех проверяем по коду возврата.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments, [string]$What)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { Fail "$What (код $LASTEXITCODE)" }
}

Write-Host "=== Сборка релиза $AppName ===" -ForegroundColor Green

# ── Проверки окружения ──────────────────────────────────────────────────────
if (-not (Test-Path $VenvPython)) { Fail "нет .venv — создайте: python -m venv .venv" }
if (-not (Test-Path $SpecFile))   { Fail "нет $SpecFile — состав сборки описан там" }
if (-not (Test-Path $IssFile))    { Fail "нет $IssFile" }

# Inno Setup: ISCC.exe. Ищем в PATH и в обычных местах установки.
$Iscc = $null
$found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($found) { $Iscc = $found.Source }
if (-not $Iscc) {
    foreach ($candidate in @(
        # Inno умеет ставиться и «для меня» — тогда он не в Program Files.
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe"
    )) {
        if (Test-Path $candidate) { $Iscc = $candidate; break }
    }
}
if (-not $Iscc) {
    Fail ("не найден ISCC.exe (компилятор Inno Setup).`n" +
          "  Поставьте Inno Setup 6: https://jrsoftware.org/isdl.php`n" +
          "  Он нужен только для сборки релиза, пользователям — нет.")
}
Write-Host "Inno Setup: $Iscc" -ForegroundColor Gray

# ── Версия ──────────────────────────────────────────────────────────────────
# version.py — единственный источник правды: отсюда версию берут и «О программе»,
# и проверка обновлений, и установщик.
$current = "1.0.0"
$versionText = Get-Content $VersionFile -Raw -Encoding UTF8
if ($versionText -match '__version__\s*=\s*["\x27]([0-9]+\.[0-9]+\.[0-9]+)["\x27]') {
    $current = $Matches[1]
}

if ($Version -eq "") {
    Write-Host ""
    Write-Host "Текущая версия: $current" -ForegroundColor Cyan
    $Version = Read-Host "Новая версия (Enter — оставить $current)"
}
if ($Version -eq "") { $Version = $current }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "версия '$Version' не вида X.Y.Z" }

if ($Version -ne $current) {
    $updated = $versionText -replace '(__version__\s*=\s*["\x27])[0-9]+\.[0-9]+\.[0-9]+(["\x27])', "`${1}$Version`${2}"
    [System.IO.File]::WriteAllText($VersionFile, $updated, (New-Object System.Text.UTF8Encoding($true)))
    Write-Host "version.py: $current -> $Version" -ForegroundColor Green
}

# ── Зависимости ─────────────────────────────────────────────────────────────
if ($SkipDeps) {
    Step "1/6" "Зависимости пропущены (-SkipDeps)"
} else {
    Step "1/6" "Зависимости"
    Invoke-Native $VenvPython @("-m", "pip", "install", "--disable-pip-version-check",
        "-q", "-r", (Join-Path $Root "requirements.txt")) "не установились зависимости"
    Invoke-Native $VenvPython @("-m", "pip", "install", "--disable-pip-version-check",
        "-q", "pyinstaller") "не установился PyInstaller"
    # pywebview даёт настоящее окно приложения. Без него код молча уходит на
    # запасной путь — окно Edge --app со своим профилем. Работает, но это не
    # то, что вы собирались отдавать людям.
    & $VenvPython -c "import webview" 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "pywebview не установился — окно приложения будет запасным (Edge --app)" }
}

# ── Сборка приложения ───────────────────────────────────────────────────────
Step "2/6" "PyInstaller по $AppName.spec"
if (Test-Path (Join-Path $Root "build\release")) {
    Remove-Item -Recurse -Force (Join-Path $Root "build\release")
}
# Собираем ПО СПЕКЕ, а не из main.py с флагами: во втором режиме PyInstaller
# генерирует спеку и перезаписывает нашу, молча теряя правки состава сборки.
Invoke-Native $VenvPython @(
    "-m", "PyInstaller", $SpecFile, "--clean", "--noconfirm",
    "--distpath", (Join-Path $Root "build\release"), "--workpath", $WorkDir
) "PyInstaller не собрал приложение"

$ExePath = Join-Path $PayloadDir "$AppName.exe"
if (-not (Test-Path $ExePath)) { Fail "после сборки нет $ExePath" }

# ── Инструменты рядом с .exe ────────────────────────────────────────────────
# tools\ НЕ идут через datas спеки: приложение читает их от папки .exe
# (install_dir() в src\shared\paths.py), а копия внутри _internal нигде не
# резолвится — это был бы мёртвый груз.
Step "3/6" "tools\ в корень сборки"
$ToolsSource = Join-Path $Root "tools"
if (Test-Path $ToolsSource) {
    $ToolsDest = Join-Path $PayloadDir "tools"
    New-Item -ItemType Directory -Path $ToolsDest -Force | Out-Null
    Get-ChildItem -Path $ToolsSource |
        Where-Object { $ToolsExclude -notcontains $_.Name } |
        ForEach-Object { Copy-Item -Path $_.FullName -Destination $ToolsDest -Recurse -Force }
    Write-Host "  скопировано (скретч-папки пропущены: $($ToolsExclude -join ', '))" -ForegroundColor Gray
} else {
    Write-Host "  папки tools\ нет — пропускаю" -ForegroundColor Yellow
}

Set-Content -Path (Join-Path $PayloadDir "VERSION") -Value $Version -Encoding UTF8 -NoNewline

# Страховка: конфиг с вашим путём к игре и вашими ключами в релиз попасть не
# должен. Спека его больше не пакует, но проверить дешевле, чем отозвать ключ.
$leaked = Get-ChildItem -Recurse -File $PayloadDir -Filter "app_config.json" -ErrorAction SilentlyContinue
if ($leaked) { Fail "в сборку попал app_config.json: $($leaked[0].FullName)" }

$payloadMb = [math]::Round((Get-ChildItem $PayloadDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "  размер приложения: $payloadMb МБ" -ForegroundColor Gray

# ── Установщик ──────────────────────────────────────────────────────────────
Step "4/6" "Inno Setup: упаковываю приложение внутрь установщика"
if (Test-Path $SetupPath) { Remove-Item -Force $SetupPath }
Invoke-Native $Iscc @("/Q", "/DAppVersion=$Version", "/DPayloadDir=$PayloadDir",
    $IssFile) "ISCC не собрал установщик"
if (-not (Test-Path $SetupPath)) { Fail "ISCC отработал, но нет $SetupPath" }

# ── Портативный zip ─────────────────────────────────────────────────────────
# СТРОГО после установщика: маркер PORTABLE кладётся в ту же папку сборки, и
# попади он внутрь Setup.exe — установленная копия считала бы себя портативной.
Step "5/6" "Портативный zip"
Set-Content -Path (Join-Path $PayloadDir "PORTABLE") -Value "portable" -Encoding ASCII -NoNewline
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
# Имена записей пишем сами, с прямым слэшем: и Compress-Archive, и
# ZipFile::CreateFromDirectory в .NET Framework кладут обратный, и часть
# распаковщиков раскладывает такой архив плоско, файлами «Tf2SkinGenerator\…».
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($ZipPath, 'Create')
try {
    Get-ChildItem -Path $PayloadDir -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($PayloadDir.Length + 1).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $_.FullName, "$AppName/$rel",
            [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $zip.Dispose() }
if (-not (Test-Path $ZipPath)) { Fail "zip не собрался: $ZipPath" }

# ── Итог ────────────────────────────────────────────────────────────────────
Step "6/6" "Готово"
$setupMb = [math]::Round((Get-Item $SetupPath).Length / 1MB, 2)
$zipMb   = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
$sha = (Get-FileHash -Algorithm SHA256 $SetupPath).Hash.ToLower()

Write-Host ""
Write-Host "Версия:     $Version" -ForegroundColor Cyan
Write-Host "Установщик: $SetupPath" -ForegroundColor Cyan
Write-Host "            $setupMb МБ (приложение внутри: $payloadMb МБ), SHA-256 $sha" -ForegroundColor Gray
Write-Host "Портативно: $ZipPath ($zipMb МБ)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Что дальше:" -ForegroundColor Yellow
Write-Host "  1. Проверьте установку: запустите Setup.exe у себя." -ForegroundColor Yellow
Write-Host "  2. Создайте релиз на GitHub с тегом v$Version (не черновик, не пре-релиз)." -ForegroundColor Yellow
Write-Host "  3. Приложите оба файла, имена менять нельзя:" -ForegroundColor Yellow
Write-Host "     $AppName-Setup.exe      — по этому имени приложение находит обновление" -ForegroundColor Yellow
Write-Host "     $AppName-portable.zip   — для тех, кто не хочет ставить" -ForegroundColor Yellow
Write-Host "  4. GitHub сам посчитает SHA-256; сверьте с строкой выше, если хотите." -ForegroundColor Yellow
