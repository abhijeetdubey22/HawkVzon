@echo off
title Face & Emotion Real-Time Recognition
echo =========================================================
echo    Starting Face & Emotion Real-Time Recognition
echo    (Press 'q' in the camera window to exit)
echo =========================================================
"C:\Users\Abhijeet\AppData\Local\Programs\Python\Python310\python.exe" face_emotion_combined.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Script exited with error code %ERRORLEVEL%.
    pause
)
