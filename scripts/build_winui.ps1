$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root 'winui\PaperangP1\PaperangP1.csproj'
$output = Join-Path $root 'winui\PaperangP1\bin\x64\Release\net8.0-windows10.0.19041.0\win-x64'
dotnet build $project -c Release -p:Platform=x64 -p:NuGetAudit=false --ignore-failed-sources
if ($LASTEXITCODE -ne 0) { throw 'WinUI 3 build failed' }
Write-Host "WinUI 3 app: $output\PaperangP1.exe"
