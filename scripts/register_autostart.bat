@echo off
setlocal

set TASK_NAME=BinanceMCPTradingServer
set SCRIPT_DIR=%~dp0
set SCRIPT_PATH=%SCRIPT_DIR%start.bat

echo Registering Binance MCP as a Windows Scheduled Task...
echo Task name: %TASK_NAME%
echo Script:    %SCRIPT_PATH%
echo.

schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Removing existing task...
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
)

schtasks /create /tn "%TASK_NAME%" ^
    /tr "cmd /c \"%SCRIPT_PATH%\"" ^
    /sc onlogon ^
    /rl highest ^
    /f ^
    /delay 0001:00

if %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS: Task registered. Server will start automatically at logon.
    echo To run immediately: schtasks /run /tn "%TASK_NAME%"
) else (
    echo.
    echo ERROR: Failed to register task. Run this script as Administrator.
)

pause
