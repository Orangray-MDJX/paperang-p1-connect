Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -match 'USBPRINT'
} | ForEach-Object {
    Write-Output ("STATUS: {0} | CLASS: {1}" -f $_.Status, $_.Class)
    Write-Output ("  NAME: {0}" -f $_.FriendlyName)
    Write-Output ("  ID:   {0}" -f $_.InstanceId)
}
Write-Output "--- 可用打印端口 ---"
Get-PrinterPort | Select-Object -ExpandProperty Name
