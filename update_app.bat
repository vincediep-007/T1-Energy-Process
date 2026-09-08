@echo off
title Updating T1-Energy-Process
cd /d "%~dp0"
echo ===================================================
echo   Updating T1-Energy-Process to Latest Version
echo ===================================================

where git >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [INFO] Git detected. Pulling latest updates from GitHub...
    git pull origin main
) else (
    echo [INFO] Git not found. Downloading update via built-in web connection...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/vincediep-007/T1-Energy-Process/archive/refs/heads/main.zip' -OutFile 'update_pkg.zip'"
    if exist update_pkg.zip (
        echo [INFO] Extracting latest code...
        powershell -Command "Expand-Archive -Path 'update_pkg.zip' -DestinationPath 'temp_update' -Force"
        if exist "temp_update\T1-Energy-Process-main" (
            xcopy /s /e /y /q "temp_update\T1-Energy-Process-main\*" "."
        )
        rd /s /q "temp_update" >nul 2>&1
        del /f /q "update_pkg.zip" >nul 2>&1
        echo [SUCCESS] Updated all files successfully from GitHub!
    ) else (
        echo [ERROR] Could not download update package.
    )
)

echo.
where pip >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Checking/updating dependencies...
    pip install -r requirements.txt
)
echo.
echo ===================================================
echo   [DONE] Application is updated and ready to run!
echo ===================================================
pause

