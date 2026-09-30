# Build the Windows installer: WinUI app (self-contained) + service exe +
# autostart/printer-queue components. ASCII only for PowerShell 5.1.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot | Split-Path -Parent
$out = Join-Path $PSScriptRoot "output"
$service = Join-Path $out "service"
$app = Join-Path $out "app"
New-Item -ItemType Directory -Force -Path $service, $app | Out-Null

Write-Output "== 1/3 publish WinUI app (self-contained, no .NET runtime needed)"
dotnet publish (Join-Path $root "winui\PaperangP1\PaperangP1.csproj") `
    -c Release -r win-x64 -p:SelfContained=true `
    -o $app
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }

Write-Output "== 2/3 PyInstaller service exe"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
& $venvPy -m pip install pyinstaller --quiet --disable-pip-version-check
$env:PAPERANG_NO_MIRRORS = "1"
& $venvPy -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name PaperangP1Service `
    --distpath $out --workpath (Join-Path $out "build") `
    --specpath $PSScriptRoot `
    --hidden-import "uvicorn.logging" `
    --hidden-import "uvicorn.loops.auto" `
    --hidden-import "uvicorn.protocols.http.auto" `
    --hidden-import "paperang_p1.vendor_helper" `
    (Join-Path $PSScriptRoot "service_entry.py")
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

Write-Output "== 3/3 Inno Setup"
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup not found at $iscc" }
$version = "0.2.2"
& $iscc "/DAppVersion=$version" "/DRepoRoot=$root" "/DOutRoot=$out" `
    (Join-Path $PSScriptRoot "paperang.iss")
if ($LASTEXITCODE -ne 0) { throw "iscc failed" }
Write-Output ("Setup: " + (Join-Path $out "PaperangP1-Setup-$version.exe"))
