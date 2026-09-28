$ErrorActionPreference = "SilentlyContinue"
Get-Printer | Select-Object Name, DriverName, PortName, PrinterStatus, Shared |
    Format-Table -AutoSize | Out-String -Width 200
Get-PrinterPort | Where-Object { $_.Name -like "*USB*" -or $_.Name -like "Paperang*" } |
    Select-Object Name, Description | Format-Table -AutoSize | Out-String -Width 200
