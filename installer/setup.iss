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
#ifndef AppCloseApplications
  #error "AppCloseApplications must be supplied by scripts/build_all.py."
#endif
#ifndef LegacyShortcutsFile
  #error "LegacyShortcutsFile must be supplied by scripts/build_all.py."
#endif
AppId={#AppInstallerId}
AppName=FileOps Hub
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppInstallDir}
; New installs use Programs/FileOps; upgrades keep the actual existing folder/data.
UsePreviousAppDir=yes
DisableDirPage=no
DefaultGroupName=FileOps Hub
UninstallDisplayIcon={app}\{#AppProductId}.exe
OutputDir=..\dist\packaging
OutputBaseFilename={#AppProductId}-Setup_v{#AppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
CloseApplicationsFilter={#AppCloseApplications}

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
; Remove only old shortcut and EXE leaves, never user folders/data.
; Historical names are injected from the central compatibility lists.
#include LegacyShortcutsFile

[Run]
Filename: "{app}\{#AppProductId}.exe"; Description: "{cm:LaunchProgram,FileOps Hub}"; Flags: nowait postinstall skipifsilent
