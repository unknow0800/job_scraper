$ErrorActionPreference = "Stop"

# Ce script cree une tache planifiee Windows qui demarre le serveur a la connexion.
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $ProjectDir "run_dashboard_server.ps1"
$TaskName = "JobScraperDashboard"
# Action executee par la tache: lancer PowerShell sur run_dashboard_server.ps1.
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn
# Reglages: autoriser la batterie et redemarrer automatiquement si le serveur tombe.
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2)
# -Force remplace une ancienne tache du meme nom si elle existe deja.
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Starts Job Scraper Dashboard, hourly sprint, and automatic email digest at Windows logon." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "It will start automatically when you log in to Windows."
Write-Host "Dashboard URL: http://127.0.0.1:8000/"
