[Setup]
#ifndef AppVersion
  #error "AppVersion must be supplied by tools/build_all.py."
#endif
AppId={{2A0D58B7-8D1D-44B1-9C3A-2B33F4F3DF11}
AppName=IntegratedDataTool
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\IntegratedDataTool
DefaultGroupName=IntegratedDataTool
UninstallDisplayIcon={app}\IntegratedDataTool.exe
OutputDir=..\release
OutputBaseFilename=IntegratedDataTool_Setup_v{#AppVersion}
SetupIconFile=..\src\assets\icon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
CloseApplicationsFilter=IntegratedDataTool.exe

[Files]
Source: "..\dist\IntegratedDataTool.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\IntegratedDataTool"; Filename: "{app}\IntegratedDataTool.exe"; IconFilename: "{app}\IntegratedDataTool.exe"; AppUserModelID: "fileops.hub.desktop.v1"
Name: "{userdesktop}\IntegratedDataTool"; Filename: "{app}\IntegratedDataTool.exe"; IconFilename: "{app}\IntegratedDataTool.exe"; AppUserModelID: "fileops.hub.desktop.v1"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\IntegratedDataTool.exe"; Description: "{cm:LaunchProgram,IntegratedDataTool}"; Flags: nowait postinstall skipifsilent
