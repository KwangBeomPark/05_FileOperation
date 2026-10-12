; Test-only installer: no uninstall registration, shortcuts, services or real paths.
#ifndef FixtureRoot
  #error "FixtureRoot is required."
#endif
#ifndef MigrationInclude
  #error "MigrationInclude is required."
#endif
[Setup]
AppId=FileOpsMigrationFixtureOnly
AppName=FileOps Migration Fixture
AppVersion=1.0
DefaultDirName={#FixtureRoot}
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
OutputBaseFilename=migration_fixture
Compression=none
[CustomMessages]
MigrationUnsafe=unsafe migration
MigrationConflict=settings conflict
MigrationChanged=changed files
MigrationMultiple=multiple old installations
MigrationRetained=old files retained
[Code]
#include MigrationInclude

procedure CurStepChanged(Step: TSetupStep);
var
  Root, Source, Target, Scenario, Error: String;
  ExecutableNames, ConfigNames, Folders: TStringList;
begin
  if Step <> ssInstall then Exit;
  Scenario := ExpandConstant('{param:Scenario|normal}');
  Root := ExpandConstant('{#FixtureRoot}\{param:Case|normal}');
  Target := Root + '\Programs\FileOps';
  ExecutableNames := TStringList.Create;
  ConfigNames := TStringList.Create;
  Folders := TStringList.Create;
  try
    ExecutableNames.Add('IntegratedDataTool.exe');
    ConfigNames.Add('setting_integrated.json');
    Folders.Add('IntegratedDataTool');
    Folders.Add('App005_FileOps');
    Folders.Add('FileOps');
    try
      Source := MigrationFindSource(Root, Target, Folders, ExecutableNames, ConfigNames);
      MigrationPrepare(Source, Target, ExecutableNames, ConfigNames, Scenario = 'owned_uninstaller');
      if Scenario = 'before_payload_failure' then RaiseException('simulated payload failure');
      if Scenario = 'stage_tamper' then
        SaveStringToFile(MigrationStage + '\settings.json', 'tampered', False);
      if Scenario = 'target_race' then begin
        ForceDirectories(Target + '\UserSetting');
        SaveStringToFile(Target + '\UserSetting\settings.json', 'new settings appeared', False);
      end;
      ForceDirectories(Target);
      SaveStringToFile(Target + '\App05_FileOps.exe', 'verified new payload fixture', False);
      MigrationActivate(Target);
      if Scenario = 'source_tamper' then
        SaveStringToFile(Source + '\UserSetting\settings.json', 'changed old settings', False);
      if Scenario = 'target_tamper' then
        SaveStringToFile(Target + '\UserSetting\settings.json', 'changed new settings', False);
      if Scenario = 'program_tamper' then
        SaveStringToFile(Source + '\IntegratedDataTool.exe', 'changed old program', False);
      MigrationCleanup;
      SaveStringToFile(Root + '\outcome.txt', 'ok', False);
    except
      Error := GetExceptionMessage;
      SaveStringToFile(Root + '\outcome.txt', Error, False);
    end;
  finally
    ExecutableNames.Free;
    ConfigNames.Free;
    Folders.Free;
    MigrationReleaseLists;
  end;
end;
