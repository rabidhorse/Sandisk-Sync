@echo off
rem Plug in the player, then double-click this to sync podcasts and music.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m sandisk_sync %*) else (python -m sandisk_sync %*)
pause
