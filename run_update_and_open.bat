@echo off
cd /d "%~dp0"
if not exist Output mkdir Output
echo Nifty 500 Sector Intelligence - full-universe update
echo If Input CSV has fewer than 400 rows, updater will try the official Nifty 500 list.
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)
python fetch_data.py --no-open
if errorlevel 1 (
  echo Update failed. Check Output\update.log.
  pause
  exit /b 1
)
if not exist "Output\index.html" (
  echo Output\index.html was not created.
  pause
  exit /b 1
)
start "" "%~dp0Output\index.html"
