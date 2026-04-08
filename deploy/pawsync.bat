@echo off
echo === PawPoller Story Sync ===
echo.
echo Removing any stale archive...
del "%TEMP%\story-archive.tar.gz" 2>nul
echo Packing stories...
cd /d "C:\Users\rhysc\claude\m_x\Archives\Complete_Stories"
REM --force-local stops Windows tar from interpreting "C:\..." as a remote SSH host
tar --force-local -czf "%TEMP%\story-archive.tar.gz" --exclude="*/Backups/*" --exclude="*/Drafts/*" --exclude="*/Styled_HTML/*" .
if errorlevel 1 (
    echo ERROR: tar failed, aborting before upload
    exit /b 1
)
if not exist "%TEMP%\story-archive.tar.gz" (
    echo ERROR: archive file not created, aborting
    exit /b 1
)
echo Uploading to GCP...
gcloud compute scp --zone=us-east1-c "%TEMP%\story-archive.tar.gz" kithetiger@pawpoller:/tmp/story-archive.tar.gz
if errorlevel 1 (
    echo ERROR: scp failed
    exit /b 1
)
echo Extracting on server...
gcloud compute ssh pawpoller --zone=us-east1-c --command="cd /home/kithetiger/story-archive && tar xzf /tmp/story-archive.tar.gz && sudo chmod -R o+rX /home/kithetiger/story-archive && rm -f /tmp/story-archive.tar.gz"
echo.
echo Done! Stories synced to server.
del "%TEMP%\story-archive.tar.gz" 2>nul
pause
