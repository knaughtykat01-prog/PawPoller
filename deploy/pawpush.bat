@echo off
REM Alias for pawsync — push story archive from local to server.
REM Usage:
REM   pawpush.bat              (full sync)
REM
REM This is the inverse of pawpull.bat.
REM   pawpush = local -> server (upload)
REM   pawpull = server -> local (download)
python "%~dp0pawsync.py" %*
exit /b %errorlevel%
