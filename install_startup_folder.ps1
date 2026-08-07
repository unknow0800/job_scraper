$ErrorActionPreference = "Stop"

# Dossier du projet: on part de l'emplacement de ce script.
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerScript = Join-Path $ProjectDir "run_dashboard_server.ps1"
# Dossier Windows "Startup": tout raccourci place ici se lance a la connexion.
$StartupDir = [Environment]::GetFolderPath("Startup")
$LauncherPath = Join-Path $StartupDir "JobScraperDashboard.vbs"

# Le fichier VBS lance PowerShell en fenetre cachee pour demarrer le dashboard discretement.
$EscapedServerScript = $ServerScript.Replace('"', '""')
$Command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """"$EscapedServerScript"""""
$Vbs = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "$Command", 0, False
"@

# Ecrit le lanceur dans le dossier de demarrage Windows.
Set-Content -Path $LauncherPath -Value $Vbs -Encoding ASCII

Write-Host "Installed startup launcher:"
Write-Host $LauncherPath
Write-Host "The server will start automatically when you log in to Windows."
Write-Host "Dashboard URL: http://127.0.0.1:8000/"
