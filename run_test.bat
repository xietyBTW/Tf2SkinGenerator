@echo off
chcp 65001 >nul
echo ========================================
echo TF2 Skin Generator - Тестовое приложение
echo ========================================
echo.

set VENV_PATH=.venv
set PYTHON_EXE=%VENV_PATH%\Scripts\python.exe

REM Проверяем наличие .venv
if not exist "%VENV_PATH%" (
    echo ОШИБКА: Виртуальное окружение не найдено!
    echo Создайте виртуальное окружение:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM Проверяем наличие Python в .venv
if not exist "%PYTHON_EXE%" (
    echo ОШИБКА: Python не найден в .venv!
    echo Виртуальное окружение может быть повреждено.
    echo Пересоздайте его:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM Проверяем наличие библиотеки vpk
%PYTHON_EXE% -c "import vpk" >nul 2>&1
if errorlevel 1 (
    echo Предупреждение: Библиотека vpk не установлена в .venv.
    echo Устанавливаем библиотеку vpk...
    %PYTHON_EXE% -m pip install vpk
    if errorlevel 1 (
        echo ОШИБКА: Не удалось установить библиотеку vpk!
        echo Установите вручную: %PYTHON_EXE% -m pip install vpk
        pause
        exit /b 1
    )
    echo Библиотека vpk успешно установлена.
    echo.
)

echo Запуск тестового приложения...
echo.

REM Запускаем тестовое приложение
%PYTHON_EXE% mainTest.py

if errorlevel 1 (
    echo.
    echo ОШИБКА: Приложение завершилось с ошибкой!
    pause
    exit /b 1
)

echo.
echo Тест завершен.
pause

