@echo off
REM Se placer dans le dossier du script, meme si le terminal est ouvert ailleurs.
cd /d "%~dp0"
echo Starting Job Scraper Dashboard...
echo.
echo Open this URL in your browser:
echo http://127.0.0.1:8001/
echo.
REM Lance FastAPI avec uvicorn sur le port 8001.
python -m uvicorn app:app --host 127.0.0.1 --port 8001
echo.
echo Server stopped. If there is an error above, send it to Codex.
pause
