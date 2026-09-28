# Clean up paperang USB devnodes: remove phantoms, ensure enabled, rescan. ASCII only.
$log = Join-Path $env:TEMP "p1_fix_usb_out.txt"
Start-Transcript -Path $log -Force | Out-Null

Write-Output "== remove phantom/devnode of VID_4348 and USBPRINT"
Get-PnpDevice | Where-Object { $_.InstanceId -match "VID_4348|USBPRINT" } | ForEach-Object {
    Write-Output ("node: " + $_.InstanceId + " status=" + $_.Status)
    if ($_.Status -ne "OK") {
        pnputil /remove-device $_.InstanceId 2>&1 | Select-Object -First 2
    } else {
        Enable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
        Write-Output ("  enabled: " + $_.FriendlyName)
    }
}

Write-Output "== rescan"
pnputil /scan-devices 2>&1 | Select-Object -First 3
Start-Sleep -Seconds 4

Write-Output "== after rescan"
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match "VID_4348|USBPRINT" } | ForEach-Object {
    Write-Output ("{0} | {1} | {2}" -f $_.Status, $_.FriendlyName, $_.InstanceId)
}
Stop-Transcript | Out-Null
