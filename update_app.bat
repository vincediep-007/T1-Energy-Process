@echo off
title Updating T1-Energy-Process from GitHub
cd /d "%~dp0"
echo ===================================================
echo   Pulling latest updates from GitHub ...
echo ===================================================
git pull origin main
echo.
echo Checking/updating dependencies...
pip install -r requirements.txt
echo.
echo [DONE] Project is up to date!
pause
