# 检查 Paperang USB 设备（VID 0x4348）是否在位及其当前驱动绑定
Write-Output "=== USB 设备 (VID_4348 / VID_0483) ==="
Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -match 'VID_4348' -or $_.InstanceId -match 'VID_0483'
} | ForEach-Object {
    Write-Output ("{0} | {1} | {2}" -f $_.Status, $_.Class, $_.InstanceId)
    Write-Output ("  -> {0}" -f $_.FriendlyName)
}

Write-Output ""
Write-Output "=== USB 打印类设备 ==="
Get-PnpDevice -PresentOnly -Class USB, Printer 2>$null | Where-Object {
    $_.InstanceId -match 'USB'
} | ForEach-Object {
    Write-Output ("{0} | {1} | {2} | {3}" -f $_.Status, $_.Class, $_.FriendlyName, $_.InstanceId)
}
