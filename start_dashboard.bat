@echo off
title PawPoller Dashboard
cd /d "C:\Users\rhysc\claude\inkbunny_analytics"

:: Kill any stale process on port 8420
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "8420.*LISTENING"') do (
    echo Killing stale process on port 8420 (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 >nul

echo Starting PawPoller Dashboard...
echo Dashboard: http://127.0.0.1:8420
start http://127.0.0.1:8420
python dashboard.py
pause
