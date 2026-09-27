@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Run Launch.cmd for the simulator or Launch-Live.cmd for real controls.
pause
exit /b 0
:failed
echo Setup failed. Install Python with Tk support and try again.
pause
exit /b 1
