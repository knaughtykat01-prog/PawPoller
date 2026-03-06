@echo off
title PawPoller
cd /d "C:\Users\rhysc\claude\inkbunny_analytics"

echo Checking for stale processes on port 8420...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "8420.*LISTENING" 2^>nul') do (
    echo Killing PID %%a...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 >nul

echo Starting poller in background...
start "IB Poller" /min cmd /c ""C:\Program Files\Python310\python.exe" poll_service.py"
timeout /t 2 >nul

echo Starting dashboard at http://127.0.0.1:8420
echo Press Ctrl+C to stop.
echo.
start "" http://127.0.0.1:8420
"C:\Program Files\Python310\python.exe" dashboard.py

echo.
echo === Dashboard stopped ===
pause
