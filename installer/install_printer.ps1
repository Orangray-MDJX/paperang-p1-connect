# Install the loopback IPP queue using the inbox IPP class driver.
param([int]$Port = 8631)
$ErrorActionPreference = "Stop"
$printerName = "Paperang P1 (服务)"
$url = "http://127.0.0.1:$Port/ipp/print"
$existing = Get-Printer -Name $printerName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.DriverName -ne 'Microsoft IPP Class Driver') {
        throw "Queue name is occupied by a different driver: $($existing.DriverName)"
    }
    $existingPort = Get-PrinterPort -Name $existing.PortName -ErrorAction Stop
    if ($existingPort.Description -ne 'IPP Port') { throw 'Existing queue is not an IPP queue.' }
    Write-Output "IPP queue already exists."
    $existing | Format-List Name, DriverName, PortName
    exit 0
}
if (-not (Get-Command Add-Printer).Parameters.ContainsKey('IppURL')) {
    throw 'This Windows version does not expose Add-Printer -IppURL.'
}
Add-Printer -Name $printerName -IppURL $url -ErrorAction Stop
Get-Printer -Name $printerName | Format-List Name, DriverName, PortName
