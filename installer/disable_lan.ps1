$ErrorActionPreference = 'Stop'
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/config' -Method Put -ContentType 'application/json' -Body '{"lan_enabled":false}' | Out-Null
foreach ($name in @('PaperangP1-LAN-IPP','PaperangP1-LAN-mDNS')) {
    Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}
Write-Output "LAN requests are disabled. Restart service to withdraw DNS-SD and bind loopback only."
