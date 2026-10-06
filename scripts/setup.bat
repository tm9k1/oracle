@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

echo ======================================================
echo           🔮 Setting up Oracle (Windows)
echo ======================================================

if not exist .venv (
    echo Creating virtual environment in .venv...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
echo Installing dependencies...
python -m pip install --upgrade pip -q
pip install -r scripts\requirements.txt -q

python scripts\onboard.py %*
