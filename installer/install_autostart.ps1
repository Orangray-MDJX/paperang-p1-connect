# Start tray and background service, independent of login working directory.
# Default targets this checkout (venv python + run_tray.py). Installed builds
# pass -Entry <service exe> to register the packaged executable instead.
param([switch]$UseRunKey, [string]$TaskName = 'PaperangP1Tray', [string]$Entry)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if ($Entry) {
    $command = '"' + $Entry + '"'
    $action = New-ScheduledTaskAction -Execute $Entry -WorkingDirectory (Split-Path -Parent $Entry)
} else {
    $py = Join-Path $repo ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $py)) { throw "Missing Python runtime: $py" }
    $launcher = Join-Path $repo "scripts\run_tray.py"
    $command = '"' + $py + '" "' + $launcher + '"'
    $action = New-ScheduledTaskAction -Execute $py -Argument ('"' + $launcher + '"') -WorkingDirectory $repo
}
if ($UseRunKey) {
    New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $TaskName -Value $command -PropertyType String -Force | Out-Null
    Write-Output $command
    exit 0
}
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$trigger.Delay = 'PT15S'
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Paperang P1 local print bridge: tray and background service.' -Force | Out-Null
# Keep the old login entry if task registration fails.
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $TaskName -ErrorAction SilentlyContinue
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
