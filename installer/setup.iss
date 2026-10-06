[Setup]
#ifndef AppVersion
  #error "AppVersion must be supplied by scripts/build_all.py."
#endif
#ifndef AppProductId
  #error "AppProductId must be supplied by scripts/build_all.py."
#endif
#ifndef AppExeSource
  #error "AppExeSource must be supplied by scripts/build_all.py."
#endif
#ifndef AppInstallDir
  #error "AppInstallDir must be supplied by scripts/build_all.py."
#endif
#ifndef AppInstallerId
  #error "AppInstallerId must be supplied by scripts/build_all.py."
#endif
#ifndef AppWindowsId
  #error "AppWindowsId must be supplied by scripts/build_all.py."
#endif
AppId={#AppInstallerId}
AppName=FileOps Hub
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppInstallDir}
; Start with the approved Programs/FileOps default, also when upgrading.
UsePreviousAppDir=no
DisableDirPage=no
DefaultGroupName=FileOps Hub
UninstallDisplayIcon={app}\{#AppProductId}.exe
OutputDir=..\tools\_local\development-release
OutputBaseFilename={#AppProductId}_Setup_v{#AppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
CloseApplicationsFilter={#AppProductId}.exe,App05_FileOps.exe,IntegratedDataTool.exe

[Files]
Source: "{#AppExeSource}"; DestDir: "{app}"; DestName: "{#AppProductId}.exe"; Flags: ignoreversion

[Dirs]
; Generated user settings/logs/history are not bundled or removed on uninstall.
Name: "{app}\UserSetting"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\FileOps Hub"; Filename: "{app}\{#AppProductId}.exe"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppProductId}.exe"; AppUserModelID: "{#AppWindowsId}"
Name: "{userdesktop}\FileOps Hub"; Filename: "{app}\{#AppProductId}.exe"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppProductId}.exe"; AppUserModelID: "{#AppWindowsId}"; Tasks: desktopicon
Name: "{userstartup}\FileOps Hub"; Filename: "{app}\{#AppProductId}.exe"; Parameters: "--tray"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppProductId}.exe"; AppUserModelID: "{#AppWindowsId}"; Tasks: startup

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start FileOps Hub automatically when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[InstallDelete]
; Remove only shortcuts with the previous product names, never user data.
Type: files; Name: "{userdesktop}\App05_FileOps.lnk"
Type: files; Name: "{userdesktop}\IntegratedDataTool.lnk"
Type: files; Name: "{userprograms}\App05_FileOps\App05_FileOps.lnk"
Type: files; Name: "{userprograms}\IntegratedDataTool\IntegratedDataTool.lnk"

[Run]
Filename: "{app}\{#AppProductId}.exe"; Description: "{cm:LaunchProgram,FileOps Hub}"; Flags: nowait postinstall skipifsilent
