@echo off
title PawPoller Poller
cd /d "C:\Users\rhysc\claude\inkbunny_analytics"
echo Starting PawPoller Poller (hourly)...
echo Press Ctrl+C to stop.
echo.
python poll_service.py
pause
