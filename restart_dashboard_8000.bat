@echo off
REM Se placer dans le dossier du projet.
cd /d "%~dp0"
echo Restarting Job Scraper Dashboard on http://127.0.0.1:8000/
echo.
REM Cherche un processus qui écoute déjà sur le port 8000 et le stoppe.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
  echo Stopping existing server process %%a on port 8000...
  taskkill /PID %%a /F
)
echo.
REM Redemarre le dashboard sur le port standard 8000.
python -m uvicorn app:app --host 127.0.0.1 --port 8000
echo.
echo Server stopped. If there is an error above, send it to Codex.
pause
