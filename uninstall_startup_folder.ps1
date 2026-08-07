# Retire le lanceur VBS place dans le dossier de demarrage Windows.
$StartupDir = [Environment]::GetFolderPath("Startup")
$LauncherPath = Join-Path $StartupDir "JobScraperDashboard.vbs"

if (Test-Path $LauncherPath) {
    # Remove-Item supprime uniquement le fichier de lancement, pas le projet.
    Remove-Item -LiteralPath $LauncherPath
    Write-Host "Removed startup launcher:"
    Write-Host $LauncherPath
} else {
    Write-Host "Startup launcher was not found."
}
