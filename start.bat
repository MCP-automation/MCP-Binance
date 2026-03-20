@echo off
setlocal EnableDelayedExpansion

title Binance MCP Trading Server

cd /d "%~dp0"

set PYTHON=

:: Check known user-install locations first (avoids .lnk shortcuts in PATH)
for %%V in (314 313 312 311) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set PYTHON=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe
        goto :python_found
    )
)

:: Check system-wide installs
for %%V in (314 313 312 311) do (
    if exist "C:\Python%%V\python.exe" (
        set PYTHON=C:\Python%%V\python.exe
        goto :python_found
    )
)

:: Last resort: try py launcher
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON=py
    goto :python_found
)

echo ERROR: Python 3.11+ not found.
echo Install from https://www.python.org/downloads/
pause
exit /b 1

:python_found
for /f "tokens=2 delims= " %%v in ('"%PYTHON%" --version 2^>^&1') do set PYVER=%%v
echo Python: %PYTHON%
echo Version: %PYVER%

if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    "%PYTHON%" -m venv venv
    if !ERRORLEVEL! NEQ 0 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo Upgrading pip...
python -m pip install --upgrade pip -q

echo Checking dependencies...
pip install -q -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo Starting Binance MCP Trading Server...
echo.
python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Server exited with error code %ERRORLEVEL%.
    pause
)
