@echo off
rem Shows what a sync would remove, download and copy without changing the player.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m sandisk_sync --dry-run %*) else (python -m sandisk_sync --dry-run %*)
pause
