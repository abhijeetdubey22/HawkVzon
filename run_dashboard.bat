@echo off
title Face & Emotion Recognition Dashboard
echo =========================================================
echo    Starting Face & Emotion Recognition Dashboard
echo =========================================================
"C:\Users\Abhijeet\AppData\Local\Programs\Python\Python310\python.exe" gui_app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
