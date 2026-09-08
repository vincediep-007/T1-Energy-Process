@echo off
echo =======================================================
echo Pushing local repository and tags to GitHub (T1-Process)
echo =======================================================
git push -u origin main --tags
echo.
if %errorlevel% equ 0 (
    echo [SUCCESS] Repository successfully pushed to https://github.com/vincediep-007/T1-Process
) else (
    echo [ERROR] Push failed. Make sure:
    echo 1. You created the repository 'T1-Process' at https://github.com/new
    echo 2. You are signed into GitHub.
)
pause
