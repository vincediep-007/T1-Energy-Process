@echo off
title 1-Click Master QC Report Merger
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
    py merge_to_master.py %*
) else (
    python merge_to_master.py %*
)
if %errorlevel% neq 0 pause
