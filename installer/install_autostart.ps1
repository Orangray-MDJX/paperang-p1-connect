# Start tray and background service from this checkout, independent of login working directory.
param([switch]$UseRunKey)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $py)) { throw "Missing Python runtime: $py" }
$launcher = Join-Path $repo "scripts\run_tray.py"
$command = '"' + $py + '" "' + $launcher + '"'
if ($UseRunKey) {
    New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name PaperangP1Tray -Value $command -PropertyType String -Force | Out-Null
    Write-Output $command
    exit 0
}
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $py -Argument ('"' + $launcher + '"') -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$trigger.Delay = 'PT15S'
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'PaperangP1Tray' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Paperang P1 local print bridge: tray and background service.' -Force | Out-Null
# Keep the old login entry if task registration fails.
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name PaperangP1Tray -ErrorAction SilentlyContinue
Get-ScheduledTask -TaskName 'PaperangP1Tray' | Select-Object TaskName, State
