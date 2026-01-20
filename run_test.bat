@echo off
chcp 65001 >nul
echo ========================================
echo TF2 Skin Generator - Test Application
echo ========================================
echo.

set VENV_PATH=.venv
set PYTHON_EXE=%VENV_PATH%\Scripts\python.exe

REM Check if .venv exists
if not exist "%VENV_PATH%" (
    echo ERROR: Virtual environment not found!
    echo Create virtual environment:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM Check if Python exists in .venv
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found in .venv!
    echo Virtual environment may be corrupted.
    echo Recreate it:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM Check if vpk library is installed
%PYTHON_EXE% -c "import vpk" >nul 2>&1
if errorlevel 1 (
    echo Warning: vpk library is not installed in .venv.
    echo Installing vpk library...
    %PYTHON_EXE% -m pip install vpk
    if errorlevel 1 (
        echo ERROR: Failed to install vpk library!
        echo Install manually: %PYTHON_EXE% -m pip install vpk
        pause
        exit /b 1
    )
    echo vpk library installed successfully.
    echo.
)

echo Starting test application...
echo.

REM Run test application (without output redirection to see errors)
%PYTHON_EXE% mainTest.py
set PYTHON_RESULT=%ERRORLEVEL%

if not %PYTHON_RESULT%==0 (
    echo.
    echo ========================================
    echo ERROR: Application exited with error code %PYTHON_RESULT%!
    echo ========================================
    echo.
    pause
    exit /b %PYTHON_RESULT%
)

echo.
echo ========================================
echo Test completed successfully.
echo ========================================
pause
