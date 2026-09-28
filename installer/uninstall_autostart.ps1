Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name PaperangP1Tray -ErrorAction SilentlyContinue
if (Get-ScheduledTask -TaskName 'PaperangP1Tray' -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName 'PaperangP1Tray' -Confirm:$false
}
