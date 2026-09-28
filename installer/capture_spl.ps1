# Bidi-off + print + capture spool with spooler stopped. ASCII only.
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $env:TEMP "p1_capture_out.txt"
Start-Transcript -Path $log -Force | Out-Null
$py = Join-Path $root ".venv\Scripts\python.exe"

Write-Output "== purge"
Get-PrintJob -PrinterName "Paperang P1" -ErrorAction SilentlyContinue | Remove-PrintJob

Write-Output "== bidi off"
& $py (Join-Path $root "scripts\set_bidi.py") "Paperang P1" off

Write-Output "== print"
"Capture Test bidi-off 12345" | Out-Printer -Name "Paperang P1"
Start-Sleep -Seconds 10
Get-PrintJob -PrinterName "Paperang P1" -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Output ("job " + $_.Id + ": " + $_.JobStatus) }

Write-Output "== stop spooler and copy spl"
Stop-Service Spooler -Force
Start-Sleep -Seconds 2
$dst = Join-Path $env:TEMP "p1_spool_capture"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item "$env:windir\System32\spool\PRINTERS\*" $dst -Force -ErrorAction SilentlyContinue
Get-ChildItem $dst | ForEach-Object { Write-Output ("  " + $_.Name + " " + $_.Length) }
Start-Service Spooler
Start-Sleep -Seconds 3
Write-Output ("printer status: " + (Get-Printer -Name "Paperang P1").PrinterStatus)
Stop-Transcript | Out-Null
