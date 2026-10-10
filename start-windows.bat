@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe setup_local.py
if errorlevel 1 goto fail
echo.
echo Open http://127.0.0.1:5000 in your browser. Press Ctrl+C to stop.
.venv\Scripts\python.exe run.py
pause
exit /b
:fail
echo Setup failed. Check the message above. Python 3.12 or newer is required.
pause
