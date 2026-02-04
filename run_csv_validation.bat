@echo off
REM CSV Validation Cronjob Runner for Windows Task Scheduler
REM This script activates the virtual environment and runs the validation command

cd /d "%~dp0"

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Set environment variable
set USE_LOCAL_FAKE_S3=true

REM Run validation command
python manage.py validate_yesterday_csvs

REM Log completion
echo CSV Validation completed at %date% %time% >> logs\cronjob_runs.log

pause
