; Inno Setup 6 script. Built automatically by packaging\build_exe.bat when Inno Setup is installed.
#define AppName "KeepFrame"
#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

[Setup]
AppId={{501FDE3E-6834-4B16-8754-98075CD66F73}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=KeepFrame contributors
AppPublisherURL=https://github.com/omerbek/keepframe
AppSupportURL=https://github.com/omerbek/keepframe/issues
LicenseFile=..\LICENSE
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=KeepFrame-Setup-{#AppVersion}
SetupIconFile=keepframe.ico
UninstallDisplayIcon={app}\KeepFrame.exe
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\KeepFrame\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\KeepFrame.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\KeepFrame.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\KeepFrame.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
