@echo off
cd /d "%~dp0"
python fetch_data.py --no-open >> Output\scheduled_task_console.log 2>&1
