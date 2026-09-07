[Setup]
AppId={{B5F25F76-0D77-4B5A-9C12-6A4A8D5B2A91}
AppName=SaveSales
AppVersion=1.0.0
AppPublisher=SaveSales
DefaultDirName={autopf}\SaveSales
DefaultGroupName=SaveSales
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=SaveSales-Setup
SetupIconFile=savesales.ico
UninstallDisplayIcon={app}\SaveSales.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Files]
Source: "SaveSales.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SaveSales"; Filename: "{app}\SaveSales.exe"
Name: "{autodesktop}\SaveSales"; Filename: "{app}\SaveSales.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
; Allow SaveSales peers on the same LAN. Program rule covers the random HTTP sync port;
; UDP 54545 is the discovery broadcast port.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""SaveSales LAN Program"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""SaveSales LAN Discovery"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""SaveSales LAN Program"" dir=in action=allow program=""{app}\SaveSales.exe"" enable=yes profile=any remoteip=localsubnet"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""SaveSales LAN Discovery"" dir=in action=allow protocol=UDP localport=54545 enable=yes profile=any remoteip=localsubnet"; Flags: runhidden
Filename: "{app}\SaveSales.exe"; Description: "Launch SaveSales"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""SaveSales LAN Program"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""SaveSales LAN Discovery"""; Flags: runhidden