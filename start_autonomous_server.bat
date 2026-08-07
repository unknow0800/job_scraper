@echo off
REM Se placer dans le dossier du projet avant d'appeler PowerShell.
cd /d "%~dp0"
echo Starting autonomous Job Scraper server...
echo Dashboard: http://127.0.0.1:8000/
echo Logs: logs\server.log
echo.
REM Delegue le vrai demarrage au script PowerShell, qui configure aussi les logs.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_dashboard_server.ps1"
pause
