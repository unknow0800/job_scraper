# Supprime la tache planifiee creee par install_autostart_task.ps1.
$TaskName = "JobScraperDashboard"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task: $TaskName"
