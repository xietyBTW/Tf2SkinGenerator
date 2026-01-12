@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ========================================
REM TF2 Skin Generator - Универсальный скрипт запуска
REM ========================================
REM Использование:
REM   run.bat              - запуск основного приложения
REM   run.bat test         - запуск тестового приложения
REM   run.bat install      - установка зависимостей
REM   run.bat check        - проверка окружения
REM ========================================

set VENV_PATH=.venv
set PYTHON_EXE=%VENV_PATH%\Scripts\python.exe
set PYTHON_VERSION=3.13

REM Определяем режим работы
set MODE=%1
if "%MODE%"=="" set MODE=main

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

set PYTHON_CMD=%PYTHON_EXE%

REM Проверяем версию Python
%PYTHON_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Не удалось запустить Python из .venv!
    pause
    exit /b 1
)

goto %MODE%

:main
echo ========================================
echo Запуск основного приложения
echo ========================================
echo.
%PYTHON_CMD% main.py
if errorlevel 1 (
    echo.
    echo ОШИБКА: Приложение завершилось с ошибкой!
    pause
    exit /b 1
)
goto end

:test
echo ========================================
echo Запуск тестового приложения
echo ========================================
echo.

REM Проверяем наличие библиотеки vpk
%PYTHON_CMD% -c "import vpk" >nul 2>&1
if errorlevel 1 (
    echo Предупреждение: Библиотека vpk не установлена.
    echo Устанавливаем библиотеку vpk...
    %PYTHON_CMD% -m pip install vpk
    if errorlevel 1 (
        echo ОШИБКА: Не удалось установить библиотеку vpk!
        echo Установите вручную: pip install vpk
        pause
        exit /b 1
    )
    echo Библиотека vpk успешно установлена.
    echo.
)

%PYTHON_CMD% mainTest.py
if errorlevel 1 (
    echo.
    echo ОШИБКА: Тестовое приложение завершилось с ошибкой!
    pause
    exit /b 1
)
echo.
echo Тест завершен.
goto end

:install
echo ========================================
echo Установка зависимостей в .venv
echo ========================================
echo.

REM Проверяем версию Python
echo Версия Python:
%PYTHON_CMD% --version
echo.

echo Обновление pip...
%PYTHON_CMD% -m pip install --upgrade pip
echo.

echo Установка зависимостей из requirements.txt...
%PYTHON_CMD% -m pip install -r requirements.txt
echo.

echo ========================================
echo Проверка установленных библиотек...
echo ========================================
%PYTHON_CMD% -c "import sys; print('Python:', sys.version.split()[0]); import PySide6; print('PySide6:', PySide6.__version__); import numpy; print('NumPy:', numpy.__version__); import PIL; print('Pillow:', PIL.__version__); print('Все библиотеки установлены успешно!')" 2>nul
if errorlevel 1 (
    echo Предупреждение: Не все библиотеки доступны для проверки
)

echo.
echo ========================================
echo Установка завершена!
echo ========================================
goto end

:check
echo ========================================
echo Проверка окружения
echo ========================================
echo.

echo Версия Python:
%PYTHON_CMD% --version
echo.

echo Проверка зависимостей:
echo - PySide6: 
%PYTHON_CMD% -c "import PySide6; print('  OK -', PySide6.__version__)" 2>nul || echo   ОШИБКА: не установлен
echo - Pillow:
%PYTHON_CMD% -c "import PIL; print('  OK -', PIL.__version__)" 2>nul || echo   ОШИБКА: не установлен
echo - NumPy:
%PYTHON_CMD% -c "import numpy; print('  OK -', numpy.__version__)" 2>nul || echo   ОШИБКА: не установлен
echo - qdarkstyle:
%PYTHON_CMD% -c "import qdarkstyle; print('  OK')" 2>nul || echo   ОШИБКА: не установлен (опционально)
echo - vpk:
%PYTHON_CMD% -c "import vpk; print('  OK')" 2>nul || echo   ОШИБКА: не установлен (опционально)

echo.
echo Проверка инструментов:
if exist "tools\VTF\VTFCmd.exe" (
    echo - VTFCmd.exe: OK
) else (
    echo - VTFCmd.exe: ОШИБКА - не найден
)

if exist "tools\VPK\vpk.exe" (
    echo - vpk.exe: OK
) else (
    echo - vpk.exe: ОШИБКА - не найден
)

if exist "tools\crowbar\CrowbarCommandLineDecomp.exe" (
    echo - Crowbar: OK
) else (
    echo - Crowbar: ОШИБКА - не найден
)

echo.
goto end

:end
if "%MODE%"=="check" pause
if "%MODE%"=="install" pause
endlocal

