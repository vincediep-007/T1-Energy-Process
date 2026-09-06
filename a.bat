@echo off
title AOI & EL Dashboard - QC Defect Suite
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
    py main.py
) else (
    python main.py
)
if %errorlevel% neq 0 pause
