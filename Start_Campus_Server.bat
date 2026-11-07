@echo off
title AI Campus Surveillance & Attendance Command Center
color 0B
echo =================================================================
echo   AI CAMPUS SURVEILLANCE & ATTENDANCE 24/7 AUTO-WATCHDOG
echo =================================================================
echo   [INIT] Checking environment and launching server...
echo   [PORT] Web Portal will be available at: http://localhost:5000
echo =================================================================

cd /d "%~dp0"

:loop
echo [%date% %time%] Launching AI Vision & Attendance Server...
python web_server.py
echo.
echo [WARNING] Server stopped or exited at %date% %time%!
echo [WATCHDOG] Restarting server automatically in 5 seconds...
echo Press Ctrl+C if you wish to stop the watchdog completely.
timeout /t 5
goto loop

