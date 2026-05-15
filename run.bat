@echo off
set PYTHON_EXE=.venv\Scripts\python.exe
set MODE=%1
if "%MODE%"=="" set MODE=main

if not exist ".venv" (
    echo ERROR: .venv not found. Run: python -m venv .venv
    pause & exit /b 1
)
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found in .venv. Recreate environment.
    pause & exit /b 1
)

goto %MODE%

:main
"%PYTHON_EXE%" main.py
if errorlevel 1 ( echo. & echo Error. & pause & exit /b 1 )
goto end

:test
"%PYTHON_EXE%" mainTest.py
if errorlevel 1 ( echo. & echo Error. & pause & exit /b 1 )
goto end

:install
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install -r requirements.txt
echo Done. & pause
goto end

:end
