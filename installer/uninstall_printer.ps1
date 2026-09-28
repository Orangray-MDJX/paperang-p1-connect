$ErrorActionPreference = "Stop"
$name = "Paperang P1 (服务)"
$p = Get-Printer -Name $name -ErrorAction SilentlyContinue
if ($p) {
    $port = $p.PortName
    Remove-Printer -Name $name
    if (-not (Get-Printer | Where-Object { $_.PortName -eq $port })) {
        Remove-PrinterPort -Name $port -ErrorAction SilentlyContinue
    }
}
