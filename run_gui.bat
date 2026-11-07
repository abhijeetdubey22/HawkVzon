@echo off
title HawkVzon Surveillance Desktop GUI
cd /d "%~dp0"
echo ========================================================
echo Starting HawkVzon Desktop GUI Application (Python 3.10)...
echo ========================================================
"C:\Users\Abhijeet\AppData\Local\Programs\Python\Python310\python.exe" gui_app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with code %ERRORLEVEL%.
    pause
)

