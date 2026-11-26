@echo off
title Google Drive Selective File Transfer
cd /d "%~dp0"
echo Starting Google Drive File Transfer UI...
python gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo An error occurred while running the application.
    pause
)
