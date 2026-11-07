@echo off
title HawkVzon Surveillance Web Server
cd /d "%~dp0"
echo ========================================================
echo Starting HawkVzon Surveillance Web Server (Python 3.10)...
echo ========================================================
"C:\Users\Abhijeet\AppData\Local\Programs\Python\Python310\python.exe" web_server.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Server exited with code %ERRORLEVEL%.
    pause
)

