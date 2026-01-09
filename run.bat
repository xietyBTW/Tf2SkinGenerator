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

set PYTHON_CMD=python
set PYTHON_VERSION=3.13

REM Определяем режим работы
set MODE=%1
if "%MODE%"=="" set MODE=main

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден!
    echo Установите Python 3.8 или выше.
    pause
    exit /b 1
)

REM Пытаемся использовать Python 3.13 если доступен
py -3.13 --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=py -3.13
    echo Используется Python 3.13
) else (
    echo Предупреждение: Python 3.13 не найден, используется системный Python
    python --version
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
echo Установка зависимостей для Python %PYTHON_VERSION%
echo ========================================
echo.

REM Проверяем наличие Python 3.13
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
%PYTHON_CMD% -c "import sys; print('Python:', sys.version.split()[0]); import PySide6; print('PySide6:', PySide6.__version__); import cv2; print('OpenCV:', cv2.__version__); import numpy; print('NumPy:', numpy.__version__); import PIL; print('Pillow:', PIL.__version__); print('Все библиотеки установлены успешно!')" 2>nul
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
echo - OpenCV:
%PYTHON_CMD% -c "import cv2; print('  OK -', cv2.__version__)" 2>nul || echo   ОШИБКА: не установлен
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

