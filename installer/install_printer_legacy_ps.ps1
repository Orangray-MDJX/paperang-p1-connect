# Create the "Paperang P1 (服务)" virtual printer:
#   Microsoft PS Class Driver + Standard TCP/IP port -> 127.0.0.1:9100 (our spool service)
# Requires administrator. ASCII only (PS5.1 safe).
$ErrorActionPreference = "Continue"
$log = Join-Path $env:APPDATA "PaperangP1\install_printer.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Start-Transcript -Path $log -Force | Out-Null

$portName = "PaperangP1_TCP"
$printerName = "Paperang P1 (服务)"

Write-Output "== cleanup old queue/port"
Remove-Printer -Name $printerName -ErrorAction SilentlyContinue
Remove-PrinterPort -Name $portName -ErrorAction SilentlyContinue

Write-Output "== pick inbox PS class driver"
$driver = $null
foreach ($name in @("Microsoft PS Class Driver", "Microsoft PS Class Driver II")) {
    if (Get-PrinterDriver -Name $name -ErrorAction SilentlyContinue) {
        $driver = $name; break
    }
}
if (-not $driver) {
    Write-Output "PS Class Driver not found, trying to add from store..."
    try {
        Add-PrinterDriver -Name "Microsoft PS Class Driver" -ErrorAction Stop
        $driver = "Microsoft PS Class Driver"
    } catch {
        Write-Output ("FAILED to add PS driver: " + $_.Exception.Message)
    }
}
Write-Output ("driver: " + $driver)

if ($driver) {
    Write-Output "== create TCP port $portName -> 127.0.0.1:9100 (RAW)"
    try {
        Add-PrinterPort -Name $portName -PrinterHostAddress "127.0.0.1" -PortNumber 9100 -ErrorAction Stop
    } catch {
        Write-Output ("Add-PrinterPort: " + $_.Exception.Message)
    }
    # disable SNMP probing (avoid fake offline status)
    try {
        $reg = "HKLM:\SYSTEM\CurrentControlSet\Control\Print\Monitors\Standard TCP/IP Port\Ports\$portName"
        if (Test-Path $reg) {
            Set-ItemProperty -Path $reg -Name "SNMPEnabled" -Value 0 -Type DWord
            Write-Output "SNMP disabled on port"
        }
    } catch { Write-Output ("SNMP reg: " + $_.Exception.Message) }

    Write-Output "== create printer queue"
    try {
        Add-Printer -Name $printerName -DriverName $driver -PortName $portName -ErrorAction Stop
        Write-Output "queue created"
    } catch {
        Write-Output ("Add-Printer FAILED: " + $_.Exception.Message)
    }

    Write-Output "== add 58mm custom form and set as default paper"
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class PaperangForms {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct FORM_INFO_1 {
        public int Flags;
        [MarshalAs(UnmanagedType.LPWStr)] public string pName;
        public SIZEL Size;
        public RECTL ImageableArea;
    }
    [StructLayout(LayoutKind.Sequential)] public struct SIZEL { public int cx, cy; }
    [StructLayout(LayoutKind.Sequential)] public struct RECTL { public int left, top, right, bottom; }
    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool AddForm(IntPtr hPrinter, int level, ref FORM_INFO_1 form);
    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool DeleteForm(IntPtr hPrinter, string pName);
    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr OpenPrinter(string pName, out IntPtr hPrinter, IntPtr pDefault);
    [DllImport("winspool.drv")] public static extern bool ClosePrinter(IntPtr hPrinter);
}
"@
    $h = [IntPtr]::Zero
    [PaperangForms]::OpenPrinter($printerName, [ref]$h, [IntPtr]::Zero) | Out-Null
    if ($h -ne [IntPtr]::Zero) {
        [PaperangForms]::DeleteForm($h, "Paperang 58mm") | Out-Null
        $form = New-Object PaperangForms+FORM_INFO_1
        $form.Flags = 0  # FORM_USER
        $form.pName = "Paperang 58mm"
        $form.Size.cx = 58000     # 58mm in 0.001mm
        $form.Size.cy = 100000    # 100mm
        $form.ImageableArea.left = 5000
        $form.ImageableArea.top = 2000
        $form.ImageableArea.right = 55000
        $form.ImageableArea.bottom = 98000
        $ok = [PaperangForms]::AddForm($h, 1, [ref]$form)
        Write-Output ("AddForm(58mm): " + $ok)
        [PaperangForms]::ClosePrinter($h) | Out-Null
        try {
            Set-PrintConfiguration -PrinterName $printerName -PaperSize "Paperang 58mm" -ErrorAction Stop
            Write-Output "default paper set to Paperang 58mm"
        } catch {
            Write-Output ("Set-PrintConfiguration: " + $_.Exception.Message)
        }
    }
}

Write-Output "== final"
Get-Printer -Name $printerName -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Output ("  {0} | {1} | {2}" -f $_.Name, $_.DriverName, $_.PortName) }
Stop-Transcript | Out-Null
Write-Output "DONE. Log: $log"
