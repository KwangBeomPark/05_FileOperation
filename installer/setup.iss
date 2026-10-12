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
#ifndef LegacyInstallDirs
  #error "LegacyInstallDirs must be supplied by scripts/build_all.py."
#endif
#ifndef LegacyConfigNames
  #error "LegacyConfigNames must be supplied by scripts/build_all.py."
#endif
#ifndef LegacyShortcutNames
  #error "LegacyShortcutNames must be supplied by scripts/build_all.py."
#endif
AppId={#AppInstallerId}
AppName=FileOps Hub
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppInstallDir}
; Do not inherit IntegratedDataTool from the old uninstall registration.
UsePreviousAppDir=no
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

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[LangOptions]
korean.LanguageCodePage=0
korean.DialogFontName=Segoe UI
korean.DialogFontSize=9
polish.LanguageCodePage=0
polish.DialogFontName=Segoe UI
polish.DialogFontSize=9

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
MigrationUnsafe=Settings migration could not be verified. Setup stopped without deleting the old settings. Check permissions, disk space and symbolic links, then retry.
MigrationConflict=The new location already contains settings, or more than one old settings file was found. No settings will be overwritten. Back up both locations and resolve the conflict before retrying.
MigrationChanged=Old files changed during migration. The old folder is retained. Close FileOps Hub and retry.
MigrationMultiple=More than one legacy installation was found. Setup will not choose settings automatically. Back up and consolidate the old folders before retrying.
MigrationRetained=Some old files were retained. Settings were copied, but unrelated or locked files were not deleted. Check the old folder manually.
MigrationNotice=Old location: %1%2New location: %3%2Only UserSetting (or the old settings JSON) is copied. Known old program files are removed after verified installation. Other files are retained.
korean.UpgradeBlocked=트레이 아이콘을 포함하여 FileOps Hub를 종료한 뒤 다시 설치해 주세요. 기존 실행 파일이 사용 중이거나 교체할 수 없습니다.
korean.MigrationUnsafe=설정 이전을 검증하지 못했습니다. 기존 설정을 삭제하지 않고 설치를 중단합니다. 권한, 디스크 공간, 폴더 연결을 확인한 뒤 다시 시도해 주세요.
korean.MigrationConflict=새 위치에 설정이 있거나 예전 설정 파일이 여러 개 있습니다. 덮어쓰지 않습니다. 양쪽 설정을 백업하고 충돌을 정리한 뒤 다시 시도해 주세요.
korean.MigrationChanged=이전 중 기존 파일이 변경되어 예전 폴더를 남겼습니다. FileOps Hub를 종료하고 다시 시도해 주세요.
korean.MigrationMultiple=예전 설치 폴더가 여러 개 있습니다. 설정을 임의로 선택하지 않습니다. 백업한 뒤 이전할 폴더를 하나로 정리해 주세요.
korean.MigrationRetained=일부 예전 파일을 남겼습니다. 관련 없는 파일이나 잠긴 파일은 삭제하지 않습니다. 예전 폴더를 확인해 주세요.
korean.MigrationNotice=기존 위치: %1%2새 위치: %3%2UserSetting(또는 예전 설정 JSON)만 복사합니다. 설치 검증 후 확인된 예전 프로그램 파일을 정리하며 다른 파일은 남깁니다.
polish.UpgradeBlocked=Zamknij FileOps Hub (także ikonę w zasobniku) i ponów instalację. Stary plik jest używany lub nie można go zastąpić.
polish.MigrationUnsafe=Nie udało się zweryfikować migracji. Stare ustawienia nie zostały usunięte. Sprawdź uprawnienia, wolne miejsce i dowiązania.
polish.MigrationConflict=Nowa lokalizacja zawiera ustawienia lub znaleziono kilka starych plików ustawień. Nic nie zostanie nadpisane. Zrób kopie i rozwiąż konflikt.
polish.MigrationChanged=Stare pliki zmieniły się podczas migracji. Zachowano stary folder. Zamknij FileOps Hub i spróbuj ponownie.
polish.MigrationMultiple=Znaleziono kilka starych instalacji. Instalator nie wybierze ustawień automatycznie. Zrób kopie i uporządkuj stare foldery.
polish.MigrationRetained=Zachowano niektóre stare pliki. Obce lub zablokowane pliki nie zostały usunięte. Sprawdź stary folder.
polish.MigrationNotice=Stara lokalizacja: %1%2Nowa lokalizacja: %3%2Kopiowany jest tylko UserSetting (lub stary JSON ustawień). Po weryfikacji instalacji usuwane są znane stare pliki programu; inne pozostają.

[Code]
var
  KnownNames, PreviousHashes: TStringList;
  PreviousInstallOwned: Boolean;
  MigrationCandidate, MigrationDetectionError: String;
  MigrationConfigNames: TStringList;
  MigrationOwnsUninstaller: Boolean;

#include "legacy_migration.iss"

function SetEnvironmentVariable(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function InitializeSetup: Boolean;
begin
  { v1.4.5 and older start setup with their PyInstaller _PYI_* variables. Without a
    reset, the [Run] relaunch reuses that app's deleted _MEI folder and fails to load
    python3xx.dll. }
  if not SetEnvironmentVariable('PYINSTALLER_RESET_ENVIRONMENT', '1') then
    Log('PyInstaller environment reset could not be requested.');
  Result := True;
end;

function PreviousInstallLocation: String;
var
  Key: String;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#PreviousAppId}_is1';
  Result := '';
  if not RegQueryStringValue(HKCU32, Key, 'InstallLocation', Result) and IsWin64 then
    RegQueryStringValue(HKCU64, Key, 'InstallLocation', Result);
end;

function CanCleanLegacyShortcutsBeforeInstall: Boolean;
begin
  { A migration failure must leave the old shortcuts usable. }
  Result := MigrationCandidate = '';
end;

procedure CleanupMigratedShortcut(Path: String);
var
  Shell, Link: Variant;
  Target: String;
  I: Integer;
begin
  if not FileExists(Path) then Exit;
  MigrationCheckPlainPath(Path);
  Shell := CreateOleObject('WScript.Shell');
  Link := Shell.CreateShortcut(Path);
  Target := RemoveBackslash(ExpandFileName(Link.TargetPath));
  if CompareText(ExtractFileDir(Target), MigrationCandidate) <> 0 then Exit;
  for I := 0 to KnownNames.Count - 1 do
    if CompareText(ExtractFileName(Target), KnownNames[I]) = 0 then begin
      if not DeleteFile(Path) then RaiseException(CustomMessage('MigrationRetained'));
      Exit;
    end;
end;

procedure CleanupMigratedShortcuts;
var
  Names: TStringList;
  I: Integer;
begin
  Names := TStringList.Create;
  try
    Names.Delimiter := ',';
    Names.StrictDelimiter := True;
    Names.DelimitedText := '{#LegacyShortcutNames}';
    for I := 0 to Names.Count - 1 do begin
      CleanupMigratedShortcut(ExpandConstant('{userdesktop}\') + Names[I] + '.lnk');
      CleanupMigratedShortcut(ExpandConstant('{userstartup}\') + Names[I] + '.lnk');
      CleanupMigratedShortcut(ExpandConstant('{userprograms}\') + Names[I] + '\' + Names[I] + '.lnk');
      CleanupMigratedShortcut(ExpandConstant('{userprograms}\FileOps Hub\') + Names[I] + '.lnk');
    end;
  finally
    Names.Free;
  end;
end;

procedure DetectLegacyMigration;
var
  Folders: TStringList;
  Standard: String;
begin
  MigrationCandidate := '';
  MigrationDetectionError := '';
  Standard := RemoveBackslash(ExpandConstant('{localappdata}\Programs\{#AppInstallDir}'));
  Folders := TStringList.Create;
  try
    Folders.Delimiter := ',';
    Folders.StrictDelimiter := True;
    Folders.DelimitedText := '{#LegacyInstallDirs}';
    MigrationCandidate := MigrationFindSource(ExpandConstant('{localappdata}'), Standard,
      Folders, KnownNames, MigrationConfigNames);
  finally
    Folders.Free;
  end;
  MigrationOwnsUninstaller := (MigrationCandidate <> '') and
    (CompareText(AddBackslash(PreviousInstallLocation), AddBackslash(MigrationCandidate)) = 0);
end;

procedure InitializeWizard;
begin
  KnownNames := TStringList.Create;
  PreviousHashes := TStringList.Create;
  KnownNames.Delimiter := ',';
  KnownNames.StrictDelimiter := True;
  KnownNames.DelimitedText := '{#AppCloseApplications}';
  MigrationConfigNames := TStringList.Create;
  MigrationConfigNames.Delimiter := ',';
  MigrationConfigNames.StrictDelimiter := True;
  MigrationConfigNames.DelimitedText := '{#LegacyConfigNames}';
  try
    DetectLegacyMigration;
  except
    MigrationDetectionError := GetExceptionMessage;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + MemoGroupInfo + NewLine + MemoTasksInfo;
  if MigrationCandidate <> '' then
    Result := Result + NewLine + NewLine + FmtMessage(CustomMessage('MigrationNotice'), [MigrationCandidate, NewLine, ExpandConstant('{app}')]);
end;

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
  try
    DetectLegacyMigration;
    if MigrationCandidate <> '' then begin
      MigrationValidateRoots(MigrationCandidate, ExpandConstant('{app}'));
      { If the target UserSetting already contains files, keep them and skip legacy migration. }
      if not MigrationEmptyDirectory(ExpandConstant('{app}\UserSetting')) then begin
        Log('Target UserSetting already exists; preserving existing settings and skipping legacy migration.');
        MigrationCandidate := '';
      end;
    end;
  except
    Result := GetExceptionMessage;
    Exit;
  end;
  if MigrationDetectionError <> '' then begin
    Result := MigrationDetectionError;
    Exit;
  end;
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
    if MigrationCandidate <> '' then begin
      Target := AddBackslash(MigrationCandidate) + KnownNames[I];
      if FileExists(Target) then begin
#if VER >= EncodeVer(7, 0, 0)
        RegisterExtraCloseApplicationsResource(Target);
#else
        RegisterExtraCloseApplicationsResource(False, Target);
#endif
      end;
    end;
  end;
end;

procedure EnsureUpgradeReady;
var
  I, Location: Integer;
  Target: String;
  Probe: TFileStream;
begin
  { First payload callback runs after Restart Manager's normal-close request. }
  for I := 0 to KnownNames.Count - 1 do begin
    for Location := 0 to 1 do begin
      Target := ExpandConstant('{app}\') + KnownNames[I];
      if Location = 1 then begin
        if MigrationCandidate = '' then Continue;
        Target := AddBackslash(MigrationCandidate) + KnownNames[I];
      end;
      MigrationCheckPlainPath(Target);
      if FileExists(Target) then begin
      try
        Probe := TFileStream.Create(Target, fmOpenReadWrite or fmShareExclusive);
        Probe.Free;
      except
        MsgBox(CustomMessage('UpgradeBlocked'), mbError, MB_OK);
        Abort;
      end;
      end;
    end;
  end;
  MigrationPrepare(MigrationCandidate, ExpandConstant('{app}'), KnownNames,
    MigrationConfigNames, MigrationOwnsUninstaller);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  I: Integer;
  Target: String;
begin
  if (CurStep = ssPostInstall) and (MigrationCandidate <> '') then begin
    if CompareText(GetSHA256OfFile(ExpandConstant('{app}\{#AppProductId}.exe')), '{#ExpectedAppHash}') <> 0 then
      RaiseException(CustomMessage('MigrationChanged'));
    MigrationActivate(ExpandConstant('{app}'));
    try
      MigrationCleanup;
    except
      Log(GetExceptionMessage);
      if not WizardSilent then
        MsgBox(CustomMessage('MigrationRetained') + #13#10 + MigrationCandidate, mbInformation, MB_OK);
    end;
    try
      CleanupMigratedShortcuts;
    except
      Log('Legacy shortcut cleanup skipped: ' + GetExceptionMessage);
    end;
  end;
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
  if MigrationConfigNames <> nil then MigrationConfigNames.Free;
  MigrationReleaseLists;
end;
