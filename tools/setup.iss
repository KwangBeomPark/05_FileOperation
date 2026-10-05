[Setup]
#ifndef AppVersion
  #error "AppVersion must be supplied by tools/build_all.py."
#endif
AppId={{2A0D58B7-8D1D-44B1-9C3A-2B33F4F3DF11}
AppName=App05_FileOps
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\App05_FileOps
; Preserve registered install paths on upgrade, including legacy/custom locations.
UsePreviousAppDir=yes
DefaultGroupName=App05_FileOps
UninstallDisplayIcon={app}\App05_FileOps.exe
OutputDir=..\release
OutputBaseFilename=App05_FileOps_v{#AppVersion}
SetupIconFile=..\src\assets\icon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
CloseApplicationsFilter=App05_FileOps.exe

[Files]
Source: "..\dist\App05_FileOps.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\App05_FileOps"; Filename: "{app}\App05_FileOps.exe"; IconFilename: "{app}\App05_FileOps.exe"; AppUserModelID: "fileops.hub.desktop.v1"
Name: "{userdesktop}\App05_FileOps"; Filename: "{app}\App05_FileOps.exe"; IconFilename: "{app}\App05_FileOps.exe"; AppUserModelID: "fileops.hub.desktop.v1"; Tasks: desktopicon
Name: "{userstartup}\FileOps Hub"; Filename: "{app}\App05_FileOps.exe"; Parameters: "--tray"; WorkingDir: "{app}"; IconFilename: "{app}\App05_FileOps.exe"; AppUserModelID: "fileops.hub.desktop.v1"; Tasks: startup

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start FileOps Hub automatically when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Run]
Filename: "{app}\App05_FileOps.exe"; Description: "{cm:LaunchProgram,App05_FileOps}"; Flags: nowait postinstall skipifsilent
