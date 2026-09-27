@echo off
title CardioCrypt
cd /d "%~dp0"

echo ================================================
echo   CardioCrypt - ECG/PPG Biometric Auth System
echo ================================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found: venv\Scripts\python.exe
    echo.
    echo Please create it first:
    echo     python -m venv venv
    echo     venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Starting server, first launch takes about 10 seconds...
echo.
echo   Home    : http://127.0.0.1:5000
echo   Admin   : http://127.0.0.1:5000/manage/login
echo             default account: admin / admin123
echo   Stop    : close this window, or press Ctrl+C
echo ------------------------------------------------
echo.

venv\Scripts\python.exe web_auth\app.py

echo.
echo Server stopped.
pause
