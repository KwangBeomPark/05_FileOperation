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
OutputBaseFilename={#AppProductId}_Setup_v{#AppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter={#AppCloseApplications}

[Files]
Source: "{#AppExeSource}"; DestDir: "{app}"; DestName: "{#AppProductId}.exe"; Flags: ignoreversion; BeforeInstall: EnsureUpgradeReady

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
; Remove only old shortcuts. EXEs are retained until verified successful install.
; Historical names are injected from the central compatibility lists.
#include LegacyShortcutsFile

[Run]
Filename: "{app}\{#AppProductId}.exe"; Description: "{cm:LaunchProgram,FileOps Hub}"; Flags: nowait postinstall skipifsilent

#define PreviousAppId StringChange(SetupSetting("AppId"), "{{", "{")
#define ExpectedAppHash GetSHA256OfFile(AppExeSource)

[CustomMessages]
UpgradeBlocked=Close FileOps Hub (including the tray icon) and retry setup. An installed executable is still in use or cannot be replaced.

[Code]
var
  KnownNames, PreviousHashes: TStringList;
  PreviousInstallOwned: Boolean;

function HasPreviousOwnedInstall: Boolean;
var
  Key, Location: String;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#PreviousAppId}_is1';
  Result := False;
  if RegQueryStringValue(HKCU32, Key, 'InstallLocation', Location) then
    Result := CompareText(AddBackslash(Location), AddBackslash(ExpandConstant('{app}'))) = 0;
  if not Result and IsWin64 then
    if RegQueryStringValue(HKCU64, Key, 'InstallLocation', Location) then
      Result := CompareText(AddBackslash(Location), AddBackslash(ExpandConstant('{app}'))) = 0;
end;

function IsExecutableLeaf(Name: String): Boolean;
begin
  Result := (Name <> '') and (ExtractFileName(Name) = Name) and
    (Pos(':', Name) = 0) and (Pos('*', Name) = 0) and (Pos('?', Name) = 0) and
    (CompareText(Copy(Name, Length(Name) - 3, 4), '.exe') = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I: Integer;
  Target, Hash: String;
begin
  Result := '';
  if KnownNames = nil then begin
    KnownNames := TStringList.Create;
    PreviousHashes := TStringList.Create;
  end;
  KnownNames.Clear;
  PreviousHashes.Clear;
  KnownNames.Delimiter := ',';
  KnownNames.StrictDelimiter := True;
  KnownNames.DelimitedText := '{#AppCloseApplications}';
  { Snapshot ownership before setup writes the new uninstall registration. }
  PreviousInstallOwned := HasPreviousOwnedInstall;
  for I := 0 to KnownNames.Count - 1 do begin
    if not IsExecutableLeaf(KnownNames[I]) then begin
      Result := CustomMessage('UpgradeBlocked');
      Exit;
    end;
    Target := ExpandConstant('{app}\') + KnownNames[I];
    Hash := '';
    if PreviousInstallOwned and FileExists(Target) then begin
      try
        Hash := GetSHA256OfFile(Target);
      except
        Result := CustomMessage('UpgradeBlocked');
        Exit;
      end;
    end;
    PreviousHashes.Add(Hash);
  end;
end;

procedure RegisterExtraCloseApplicationsResources;
var
  I: Integer;
  Target: String;
begin
  if KnownNames = nil then Exit;
  for I := 0 to KnownNames.Count - 1 do begin
    Target := ExpandConstant('{app}\') + KnownNames[I];
    if FileExists(Target) then begin
#if VER >= EncodeVer(7, 0, 0)
      RegisterExtraCloseApplicationsResource(Target);
#else
      RegisterExtraCloseApplicationsResource(False, Target);
#endif
    end;
  end;
end;

procedure EnsureUpgradeReady;
var
  I: Integer;
  Target: String;
  Probe: TFileStream;
begin
  { First payload callback runs after Restart Manager's normal-close request. }
  for I := 0 to KnownNames.Count - 1 do begin
    Target := ExpandConstant('{app}\') + KnownNames[I];
    if FileExists(Target) then begin
      try
        Probe := TFileStream.Create(Target, fmOpenReadWrite or fmShareExclusive);
        Probe.Free;
      except
        RaiseException(CustomMessage('UpgradeBlocked'));
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  I: Integer;
  Target: String;
begin
  if (CurStep <> ssDone) or not PreviousInstallOwned then Exit;
  try
    if CompareText(GetSHA256OfFile(ExpandConstant('{app}\{#AppProductId}.exe')), '{#ExpectedAppHash}') <> 0 then Exit;
    for I := 0 to KnownNames.Count - 1 do
      if (CompareText(KnownNames[I], '{#AppProductId}.exe') <> 0) and (PreviousHashes[I] <> '') then begin
        Target := ExpandConstant('{app}\') + KnownNames[I];
        if FileExists(Target) then
          if CompareText(GetSHA256OfFile(Target), PreviousHashes[I]) = 0 then
            if not DeleteFile(Target) then Log('Obsolete application EXE retained: ' + KnownNames[I]);
      end;
  except
    Log('Obsolete application EXE cleanup skipped: ' + GetExceptionMessage);
  end;
end;

procedure DeinitializeSetup;
begin
  if KnownNames <> nil then KnownNames.Free;
  if PreviousHashes <> nil then PreviousHashes.Free;
end;
