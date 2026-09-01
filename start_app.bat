@echo off
title AOI & EL Dashboard - QC Defect Suite
echo ===================================================
echo   Starting AOI & EL Dashboard v18.6 ...
echo ===================================================
echo.

where py >nul 2>nul
if %errorlevel% equ 0 (
    py main.py
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        python main.py
    ) else (
        echo [ERROR] Python not found in PATH!
        echo Please ensure Python is installed.
        pause
    )
)

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] App closed with error code %errorlevel%.
    pause
)
