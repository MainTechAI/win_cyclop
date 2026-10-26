@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Install Python 3.12 from python.org, including the Python Launcher.
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 (
  echo Dependency installation failed. Check the error above.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m cyclop_windows
if errorlevel 1 pause
