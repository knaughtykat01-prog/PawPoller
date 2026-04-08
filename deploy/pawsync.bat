@echo off
REM Thin wrapper around deploy/pawsync.py.
REM
REM The original .bat-based pawsync was rewritten in Python on 2026-04-08
REM after hitting two intermittent bugs that wasted a session of debugging:
REM   1. Windows tar's "Cannot connect to C:" silent failure
REM      (interprets C:\... as a remote SSH host without --force-local)
REM   2. gcloud compute scp/ssh hanging silently when invoked from a .bat
REM      file context — never returning control to cmd.exe even after the
REM      upload completed. The same gcloud commands worked fine inline
REM      via cmd /c "..." but not from inside a .bat. --quiet, < nul, and
REM      every other workaround failed to dislodge the hang.
REM
REM Python's tarfile module + subprocess.run with stdin=DEVNULL is
REM deterministic and bypasses both gotchas. See deploy/pawsync.py.
python "%~dp0pawsync.py" %*
exit /b %errorlevel%
