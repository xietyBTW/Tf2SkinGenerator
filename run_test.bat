@echo off
chcp 65001 >nul
echo ========================================
echo TF2 Skin Generator - Тестовое приложение
echo ========================================
echo.

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден!
    echo Установите Python 3.8 или выше.
    pause
    exit /b 1
)

REM Проверяем наличие библиотеки vpk
python -c "import vpk" >nul 2>&1
if errorlevel 1 (
    echo Предупреждение: Библиотека vpk не установлена.
    echo Устанавливаем библиотеку vpk...
    python -m pip install vpk
    if errorlevel 1 (
        echo ОШИБКА: Не удалось установить библиотеку vpk!
        echo Установите вручную: pip install vpk
        pause
        exit /b 1
    )
    echo Библиотека vpk успешно установлена.
    echo.
)

echo Запуск тестового приложения...
echo.

REM Запускаем тестовое приложение
python mainTest.py

if errorlevel 1 (
    echo.
    echo ОШИБКА: Приложение завершилось с ошибкой!
    pause
    exit /b 1
)

echo.
echo Тест завершен.
pause

