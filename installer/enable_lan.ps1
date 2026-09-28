param([string]$Address, [string]$Network, [int]$Port = 8631)
$ErrorActionPreference = 'Stop'
if (-not $Address) {
    # Auto-detect: the LAN IPv4 of this machine (the first connected, non-loopback one)
    $Address = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
        Select-Object -First 1).IPAddress
    if (-not $Address) { throw 'No LAN IPv4 detected, please specify -Address <this machine IP> -Network <subnet>/24' }
}
if (-not $Network) {
    $prefix = ($Address -split '\.')[0..2] -join '.'
    $Network = "$prefix.0/24"
}
$configuration = @{lan_enabled=$true;lan_address=$Address;lan_network=$Network} | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/config' -Method Put -ContentType 'application/json' -Body $configuration | Out-Null
foreach ($name in @('PaperangP1-LAN-IPP','PaperangP1-LAN-mDNS')) {
    Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}
New-NetFirewallRule -Name 'PaperangP1-LAN-IPP' -DisplayName 'Paperang P1 LAN IPP' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -LocalAddress $Address -RemoteAddress $Network -Profile Any | Out-Null
New-NetFirewallRule -Name 'PaperangP1-LAN-mDNS' -DisplayName 'Paperang P1 LAN mDNS' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 5353 -RemoteAddress $Network -Profile Any | Out-Null
Get-NetFirewallRule -Name 'PaperangP1-LAN-IPP','PaperangP1-LAN-mDNS' | Select-Object Name,Enabled,Action

Write-Output "Restart the background service to apply the LAN bind/discovery configuration."
