@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Oracle Discord Bot

echo ======================================================
echo           🔮 Starting Oracle Discord Bot
echo ======================================================

if exist .venv\Scripts\python.exe (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist .venv\bin\python (
    set "PYTHON_EXE=.venv\bin\python"
) else (
    set "PYTHON_EXE=python"
)

echo Using Python: !PYTHON_EXE!
"!PYTHON_EXE!" scripts\oracle_bot.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo Oracle exited with error code %ERRORLEVEL%.
    pause
)
