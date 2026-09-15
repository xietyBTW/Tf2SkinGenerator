# Собирает tools/meshoptimizer/meshoptimizer.dll из исходников zeux/meshoptimizer.
#
# Зачем своя сборка: у pypi-пакета meshoptimizer нет wheel под Windows (только
# sdist-альфа, требующая компилятор у КАЖДОГО, кто ставит зависимости), а нам из
# всей библиотеки нужен один вызов — meshopt_simplifyWithAttributes: упрощение
# сетки с сохранением UV для моделей «из интернета» (mesh_import_service).
# Поэтому DLL лежит в репозитории рядом с VTFLib и собирается этим скриптом
# только при обновлении версии.
#
# Нужен Visual Studio 2022 (Build Tools достаточно). Запуск из корня репозитория:
#   powershell -ExecutionPolicy Bypass -File scripts/build_meshoptimizer.ps1

$ErrorActionPreference = 'Stop'
$Version = '1.2'
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root 'tools\meshoptimizer'
$Work = Join-Path $env:TEMP "meshoptimizer-build-$Version"

New-Item -ItemType Directory -Force $Work | Out-Null
$Zip = Join-Path $Work 'src.zip'
if (-not (Test-Path $Zip)) {
    Invoke-WebRequest "https://github.com/zeux/meshoptimizer/archive/refs/tags/v$Version.zip" -OutFile $Zip
}
Expand-Archive -Force $Zip $Work
$Src = Join-Path $Work "meshoptimizer-$Version\src"

$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$VsPath = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $VsPath) { throw 'Visual Studio с C++ не найдена' }
$VcVars = Join-Path $VsPath 'VC\Auxiliary\Build\vcvars64.bat'

New-Item -ItemType Directory -Force $Out | Out-Null
# Только упрощение и его аллокатор: остальное приложению не нужно.
$Cmd = "call `"$VcVars`" >nul && cd /d `"$Work`" && cl /nologo /O2 /EHsc /DNDEBUG " +
       "/DMESHOPTIMIZER_API=__declspec(dllexport) /LD " +
       "`"$Src\simplifier.cpp`" `"$Src\allocator.cpp`" /Fe:`"$Out\meshoptimizer.dll`""
cmd /c $Cmd
if ($LASTEXITCODE -ne 0) { throw "cl.exe завершился с кодом $LASTEXITCODE" }

Copy-Item (Join-Path $Work "meshoptimizer-$Version\LICENSE.md") (Join-Path $Out 'LICENSE.md') -Force
Get-ChildItem $Out
Write-Host "meshoptimizer $Version собран: $Out\meshoptimizer.dll"
