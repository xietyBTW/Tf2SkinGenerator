# Build script for Tf2SkinGenerator
# Собирает приложение через PyInstaller и создает zip-архив для релиза

$ErrorActionPreference = "Stop"

# Параметры проекта
$AppName = "Tf2SkinGenerator"
$EntryScript = "main.py"
$VenvPath = ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$RequirementsFile = "requirements.txt"
$DistDir = "dist"
$OutputDir = Join-Path $DistDir $AppName
$ZipFileName = "${AppName}-windows.zip"
$ZipPath = Join-Path $DistDir $ZipFileName

Write-Host "=== Building $AppName ===" -ForegroundColor Green

# Проверка существования .venv
if (-not (Test-Path $VenvPath)) {
    Write-Host "ERROR: Virtual environment not found at $VenvPath" -ForegroundColor Red
    Write-Host "Please create virtual environment first:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

# Проверка python.exe в .venv
if (-not (Test-Path $PythonExe)) {
    Write-Host "ERROR: Python executable not found at $PythonExe" -ForegroundColor Red
    Write-Host "Virtual environment may be corrupted. Please recreate it." -ForegroundColor Yellow
    exit 1
}

# Проверка requirements.txt
if (-not (Test-Path $RequirementsFile)) {
    Write-Host "ERROR: requirements.txt not found" -ForegroundColor Red
    exit 1
}

# Проверка main.py
if (-not (Test-Path $EntryScript)) {
    Write-Host "ERROR: Entry script $EntryScript not found" -ForegroundColor Red
    exit 1
}

Write-Host "`n[1/4] Installing dependencies..." -ForegroundColor Cyan
& $PythonExe -m pip install --upgrade pip | Out-Null
& $PythonExe -m pip install -r $RequirementsFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install dependencies" -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/4] Cleaning previous build..." -ForegroundColor Cyan
if (Test-Path $DistDir) {
    Remove-Item -Recurse -Force $DistDir
}
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}

Write-Host "`n[3/4] Building with PyInstaller (onedir mode)..." -ForegroundColor Cyan

# PyInstaller команда
$PyInstallerArgs = @(
    $EntryScript,
    "--name=$AppName",
    "--onedir",
    "--windowed",
    "--clean",
    "--noconfirm",
    "--distpath=$DistDir",
    "--workpath=build",
    "--specpath=."
)

# Добавляем папку tools в данные (если существует)
if (Test-Path "tools") {
    $PyInstallerArgs += "--add-data"
    $PyInstallerArgs += "tools;tools"
    Write-Host "Including 'tools' directory in build" -ForegroundColor Gray
}

# Добавляем папку config в данные (если существует и нужна)
if (Test-Path "config") {
    $PyInstallerArgs += "--add-data"
    $PyInstallerArgs += "config;config"
    Write-Host "Including 'config' directory in build" -ForegroundColor Gray
}

# Добавляем иконку (если существует)
$IconPath = "installer\assets\icon.ico"
if (Test-Path $IconPath) {
    $PyInstallerArgs += "--icon"
    $PyInstallerArgs += $IconPath
    Write-Host "Including icon: $IconPath" -ForegroundColor Gray
} else {
    Write-Host "Warning: Icon not found at $IconPath, building without icon" -ForegroundColor Yellow
}

& $PythonExe -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: PyInstaller build failed" -ForegroundColor Red
    exit 1
}

# Проверка результата
$ExePath = Join-Path $OutputDir "${AppName}.exe"
if (-not (Test-Path $ExePath)) {
    Write-Host "ERROR: Executable not found at $ExePath" -ForegroundColor Red
    exit 1
}

# Копируем tools в выходную папку (PyInstaller --add-data помещает их в _internal, но нам нужны в корне)
if (Test-Path "tools") {
    Write-Host "`n[3.5/4] Copying tools directory to output..." -ForegroundColor Cyan
    $ToolsDest = Join-Path $OutputDir "tools"
    if (Test-Path $ToolsDest) {
        Remove-Item -Recurse -Force $ToolsDest
    }
    Copy-Item -Path "tools" -Destination $ToolsDest -Recurse -Force
    Write-Host "Tools directory copied successfully" -ForegroundColor Gray
}

Write-Host "`n[4/4] Creating zip archive..." -ForegroundColor Cyan

# Удаляем старый zip если существует
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}

# Создаем zip архив (важно: архив должен содержать корневую папку Tf2SkinGenerator)
$CurrentLocation = Get-Location
try {
    Set-Location $DistDir
    Compress-Archive -Path $AppName -DestinationPath $ZipFileName -Force
}
finally {
    Set-Location $CurrentLocation
}

if (-not (Test-Path $ZipPath)) {
    Write-Host "ERROR: Failed to create zip archive" -ForegroundColor Red
    exit 1
}

$ZipSize = (Get-Item $ZipPath).Length / 1MB
Write-Host "`n=== Build completed successfully ===" -ForegroundColor Green
Write-Host "Output directory: $OutputDir" -ForegroundColor Cyan
Write-Host "Zip archive: $ZipPath ($([math]::Round($ZipSize, 2)) MB)" -ForegroundColor Cyan
Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "  1. Upload $ZipFileName to GitHub Releases" -ForegroundColor Yellow
Write-Host "  2. Build installer with: .\installer\build-installer.ps1" -ForegroundColor Yellow

