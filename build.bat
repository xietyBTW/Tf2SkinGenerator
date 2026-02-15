@echo off
chcp 65001 >nul
echo Запуск скрипта сборки build.ps1...
echo.

powershell.exe -ExecutionPolicy Bypass -File "build.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ОШИБКА: Произошла ошибка при выполнении скрипта.
    pause
    exit /b %ERRORLEVEL%
)

echo.
pause




