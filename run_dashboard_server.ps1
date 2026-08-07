$ErrorActionPreference = "Stop"

# Toujours se placer dans le dossier du projet avant de lancer Python.
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

# Les logs permettent de diagnostiquer un lancement automatique qui echoue.
$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Variables lues par app.py pour activer le sprint automatique et les emails.
$env:AUTO_SPRINT_ENABLED = "true"
$env:AUTO_SPRINT_INTERVAL_SECONDS = "3600"
$env:AUTO_EMAIL_ENABLED = "true"
$env:AUTO_EMAIL_SINCE_HOURS = "1"

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$Timestamp] Starting Job Scraper Dashboard on http://127.0.0.1:8000/" | Tee-Object -FilePath (Join-Path $LogDir "server.log") -Append

# uvicorn demarre l'application FastAPI app:app sur le port local 8000.
python -m uvicorn app:app --host 127.0.0.1 --port 8000 2>&1 | Tee-Object -FilePath (Join-Path $LogDir "server.log") -Append
