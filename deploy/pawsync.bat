@echo off
echo === PawPoller Story Sync ===
echo.
echo Packing stories...
cd /d "C:\Users\rhysc\claude\m_x\Archives\Complete_Stories"
tar -czf "%TEMP%\story-archive.tar.gz" --exclude="*/Backups/*" --exclude="*/Drafts/*" --exclude="*/Styled_HTML/*" --exclude="*/SquidgeWorld/*" .
echo Uploading to GCP...
gcloud compute scp --zone=us-east1-c "%TEMP%\story-archive.tar.gz" kithetiger@pawpoller:/tmp/story-archive.tar.gz
echo Extracting on server...
gcloud compute ssh pawpoller --zone=us-east1-c --command="cd /home/kithetiger/story-archive && tar xzf /tmp/story-archive.tar.gz && sudo chmod -R o+rX /home/kithetiger/story-archive && rm -f /tmp/story-archive.tar.gz"
echo.
echo Done! Stories synced to server.
del "%TEMP%\story-archive.tar.gz" 2>nul
pause
