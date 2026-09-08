@echo off
echo ==============================================================
echo Pushing local repository and tags to GitHub (T1-Energy-Process)
echo ==============================================================
git push -u origin main --tags
echo.
if %errorlevel% equ 0 (
    echo [SUCCESS] Repository successfully pushed to https://github.com/vincediep-007/T1-Energy-Process
) else (
    echo [ERROR] Push encountered an issue. Please verify credentials.
)
pause
