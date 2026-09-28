$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class BtEnum {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct BLUETOOTH_DEVICE_INFO {
        public int dwSize;
        public ulong Address;
        public uint ulClassofDevice;
        public bool fConnected;
        public bool fRemembered;
        public bool fAuthenticated;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 248)] public string szName;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct BLUETOOTH_DEVICE_SEARCH_PARAMS {
        public int dwSize;
        public bool fReturnAuthenticated;
        public bool fReturnRemembered;
        public bool fReturnUnknown;
        public bool fReturnUnauthenticated;
        public bool fIssueInquiry;
        public byte cTimeoutMultiplier;
        public IntPtr hRadio;
    }
    [DllImport("BluetoothApis.dll", SetLastError = true)]
    public static extern IntPtr BluetoothFindFirstDevice(ref BLUETOOTH_DEVICE_SEARCH_PARAMS pSearch, ref BLUETOOTH_DEVICE_INFO pbtdi);
    [DllImport("BluetoothApis.dll", SetLastError = true)]
    public static extern bool BluetoothFindNextDevice(IntPtr hFind, ref BLUETOOTH_DEVICE_INFO pbtdi);
    [DllImport("BluetoothApis.dll")] public static extern bool BluetoothFindDeviceClose(IntPtr hFind);
}
"@
$params = New-Object BtEnum+BLUETOOTH_DEVICE_SEARCH_PARAMS
$params.dwSize = [Runtime.InteropServices.Marshal]::SizeOf($params)
$params.fReturnAuthenticated = $true
$params.fReturnRemembered = $true
$params.fReturnUnknown = $true
$params.fReturnUnauthenticated = $true
$params.fIssueInquiry = $false
$params.cTimeoutMultiplier = 1
$params.hRadio = [IntPtr]::Zero
$di = New-Object BtEnum+BLUETOOTH_DEVICE_INFO
$di.dwSize = [Runtime.InteropServices.Marshal]::SizeOf($di)
$di.szName = [String]::new([char]0, 248)
$h = [BtEnum]::BluetoothFindFirstDevice([ref]$params, [ref]$di)
if ($h -eq [IntPtr]::Zero) { Write-Output "no devices / err"; exit }
do {
    $mac = ("{0:X2}" -f (($di.Address -shr 40) -band 0xFF)) + ":" + ("{0:X2}" -f (($di.Address -shr 32) -band 0xFF)) + ":" + ("{0:X2}" -f (($di.Address -shr 24) -band 0xFF)) + ":" + ("{0:X2}" -f (($di.Address -shr 16) -band 0xFF)) + ":" + ("{0:X2}" -f (($di.Address -shr 8) -band 0xFF)) + ":" + ("{0:X2}" -f ($di.Address -band 0xFF))
    if ($di.szName -like "*aperang*" -or $di.szName -like "*iaoMiaoJi*") {
        Write-Output ("P1: " + $di.szName + " mac=" + $mac + " connected=" + $di.fConnected + " remembered=" + $di.fRemembered + " AUTHENTICATED=" + $di.fAuthenticated)
    }
    $di.dwSize = [Runtime.InteropServices.Marshal]::SizeOf($di)
} while ([BtEnum]::BluetoothFindNextDevice($h, [ref]$di))
[BtEnum]::BluetoothFindDeviceClose($h) | Out-Null
