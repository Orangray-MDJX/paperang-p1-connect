; Inno Setup script for Paperang P1 Connect (service + WinUI app).
; Components: core (always), autostart task, printer queue (admin, optional).
#define AppName "Paperang P1 Connect"
#define AppExeName "PaperangP1.exe"

[Setup]
AppId={{8E7B6C1A-52D4-4B8E-9C3F-P1CONNECT01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Orangray-MDJX
AppPublisherURL=https://github.com/Orangray-MDJX/paperang-p1-connect
DefaultDirName={autopf}\PaperangP1
DefaultGroupName=Paperang P1
PrivilegesRequired=admin
OutputDir={#OutRoot}
OutputBaseFilename=PaperangP1-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile={#RepoRoot}\LICENSE
UninstallDisplayIcon={app}\app\{#AppExeName}

[Components]
Name: "core"; Description: "Print service and management app (required)"; Types: full compact custom; Flags: fixed
Name: "autostart"; Description: "Start tray at logon (scheduled task)"; Types: full; Flags: checkablealone
Name: "printerqueue"; Description: "Install Windows printer queue (Paperang P1 via local IPP)"; Types: full; Flags: checkablealone

[Files]
; WinUI app (self-contained)
Source: "{#OutRoot}\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion
; PyInstaller service
Source: "{#OutRoot}\PaperangP1Service\*"; DestDir: "{app}\service"; Flags: recursesubdirs ignoreversion
; Support scripts for components
Source: "{#RepoRoot}\installer\install_autostart.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\uninstall_autostart.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\install_printer.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\uninstall_printer.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"; Flags: uninsalwaysuninstall

[Icons]
Name: "{group}\Paperang P1"; Filename: "{app}\app\{#AppExeName}"
Name: "{group}\Uninstall Paperang P1"; Filename: "{uninstallexe}"

[Run]
Filename: "powershell"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\installer\install_autostart.ps1"" -TaskName PaperangP1Tray -Entry ""{app}\service\PaperangP1Service.exe"""; Components: autostart; Flags: runhidden; StatusMsg: "Registering logon autostart..."
Filename: "powershell"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\installer\install_printer.ps1"""; Components: printerqueue; Flags: runhidden; StatusMsg: "Installing printer queue..."; AfterInstall: QueueWarningIfFailed

Filename: "{app}\app\{#AppExeName}"; Description: "Launch Paperang P1"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\installer\uninstall_printer.ps1"""; RunOnceId: "DelQueue"; Flags: runhidden
Filename: "powershell"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\installer\uninstall_autostart.ps1"""; RunOnceId: "DelAuto"; Flags: runhidden

[Code]
var
  QueueWarn: string;

procedure QueueWarningIfFailed;
begin
  { Add-Printer -IppURL needs recent Windows; failures are warnings only. }
end;

function InitializeSetup: Boolean;
begin
  Result := True;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoComponentsInfo + NewLine +
    'Printer queue installation requires Windows with Add-Printer -IppURL support.' + NewLine +
    'If it fails, install it later from the Start Menu folder.';
end;
