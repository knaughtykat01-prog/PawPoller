@echo off
REM Reverse sync: pull story archive from GCP server to local.
REM Usage:
REM   pawpull.bat              (full sync)
REM   pawpull.bat _Test_Story  (single story)
python "%~dp0pawpull.py" %*
exit /b %errorlevel%
