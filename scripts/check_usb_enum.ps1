Get-PnpDevice | Where-Object {
    $_.InstanceId -like '*VID_4348*' -or $_.FriendlyName -like '*Paperang*'
} | Select-Object Status, Class, FriendlyName, InstanceId | Format-List
