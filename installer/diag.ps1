# Diagnose present paperang USB nodes. ASCII only.
Write-Output "=== all VID_4348 / USBPRINT nodes (present only) ==="
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match "VID_4348|USBPRINT" } | ForEach-Object {
    Write-Output ("STATUS={0} CLASS={1} PROBLEM={2}" -f $_.Status, $_.Class, $_.Problem)
    Write-Output ("  NAME: " + $_.FriendlyName)
    Write-Output ("  ID:   " + $_.InstanceId)
    $pc = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName "DEVPKEY_Device_ProblemCode" -ErrorAction SilentlyContinue).Data
    Write-Output ("  ProblemCode: " + $pc)
}
Write-Output "=== USB controller view ==="
Get-PnpDevice -PresentOnly -Class USB -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -match "VID_4348" } | ForEach-Object {
        Write-Output ("{0} | {1} | {2}" -f $_.Status, $_.FriendlyName, $_.InstanceId)
    }
