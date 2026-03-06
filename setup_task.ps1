# setup_task.ps1 — Register PawPoller as a Windows Task Scheduler job
# Run: powershell -ExecutionPolicy Bypass -File setup_task.ps1

$TaskName = "PawPoller"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = (Get-Command python).Source
$Script = Join-Path $ProjectDir "poll_service.py"

# Check if task already exists
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Task '$TaskName' already exists. Removing it first..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the action — run poll_service.py --once
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "--% --once" `
    -WorkingDirectory $ProjectDir

# Fix the argument to include the script path
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$Script`" --once" `
    -WorkingDirectory $ProjectDir

# Trigger: every 1 hour, starting now
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 365)

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "PawPoller - Hourly polling service" `
    -RunLevel Limited

Write-Host ""
Write-Host "=== Task Scheduler Setup Complete ===" -ForegroundColor Green
Write-Host "  Task Name: $TaskName"
Write-Host "  Runs every: 1 hour"
Write-Host "  Script: $Script --once"
Write-Host "  Working Dir: $ProjectDir"
Write-Host ""
Write-Host "Manage with:"
Write-Host "  View:    Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Run now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Disable: Disable-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Remove:  Unregister-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
