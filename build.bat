@echo off
echo === Building PawPoller ===
echo.
pyinstaller inkbunny_analytics.spec --noconfirm
echo.
if %ERRORLEVEL% EQU 0 (
    echo Build succeeded! Output: dist\PawPoller\PawPoller.exe
) else (
    echo Build failed with error code %ERRORLEVEL%
)
pause
