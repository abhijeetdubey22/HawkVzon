@echo off
cd /d "%~dp0"
title AI Face & Emotion Command Center (Web Edition)

set "PYTHON_EXE=C:\Users\Abhijeet\AppData\Local\Programs\Python\Python310\python.exe"
if not exist "%PYTHON_EXE%" (
    where py >nul 2>&1 && (set "PYTHON_EXE=py -3.10") || (set "PYTHON_EXE=python")
)

set "PORT=%~1"
if "%PORT%"=="" set "PORT=5000"

echo =================================================================
echo        AI SURVEILLANCE & ATTENDANCE COMMAND CENTER
echo =================================================================
echo.
echo  [1/2] Starting High-Performance Server on http://localhost:%PORT%
echo  [2/2] Browser (Chrome / Edge) will launch automatically...
echo.
echo  [TIP] Press F11 in your browser for cinema-grade presentation!
echo  [TIP] Press Ctrl+C in this terminal window to stop the server.
echo.
echo =================================================================
%PYTHON_EXE% web_server.py %PORT%
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Server exited with error code %ERRORLEVEL%.
    pause
)
