{ Shared, dependency-free Pascal migration engine. The fixture tests compile this
  exact code, but never run the production installer against real user folders. }
var
  MigrationSourceRoot, MigrationStage, MigrationDataRoot, MigrationTargetRoot, MigrationRootConfig: String;
  MigrationFiles, MigrationHashes, MigrationDirectories: TStringList;
  MigrationProgramFiles, MigrationProgramHashes: TStringList;
  MigrationBytes: Int64;
  MigrationPrepared, MigrationActivated: Boolean;

function MigrationFileAttributes(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function MigrationLastError: LongWord;
  external 'GetLastError@kernel32.dll stdcall';

procedure MigrationCheckPlainPath(Path: String);
var
  Parent: String;
  Attributes, Error: LongWord;
begin
  Path := RemoveBackslash(ExpandFileName(Path));
  while Path <> '' do begin
    Attributes := MigrationFileAttributes(Path);
    if Attributes = $FFFFFFFF then begin
      Error := MigrationLastError;
      if (Error <> 2) and (Error <> 3) then
        RaiseException(CustomMessage('MigrationUnsafe') + #13#10 + Path);
    end;
    if (Attributes <> $FFFFFFFF) and
       ((Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0) then
      RaiseException(CustomMessage('MigrationUnsafe') + #13#10 + Path);
    Parent := ExtractFileDir(Path);
    if Parent = Path then Break;
    Path := Parent;
  end;
end;

function MigrationLeaf(Name: String): Boolean;
begin
  Result := (Name <> '') and (Name <> '.') and (Name <> '..') and
    (ExtractFileName(Name) = Name) and (Pos(':', Name) = 0) and
    (Pos('*', Name) = 0) and (Pos('?', Name) = 0);
end;

function MigrationFindSource(Base, Standard: String; Folders, ExecutableNames, ConfigNames: TStringList): String;
var
  I, J, Prefix: Integer;
  Path, Root: String;
  Found: Boolean;
begin
  Result := '';
  for Prefix := 0 to 1 do begin
    Root := AddBackslash(Base);
    if Prefix = 1 then Root := Root + 'Programs\';
    for I := 0 to Folders.Count - 1 do begin
      if not MigrationLeaf(Folders[I]) then
        RaiseException(CustomMessage('MigrationUnsafe'));
      Path := RemoveBackslash(ExpandFileName(Root + Folders[I]));
      if CompareText(Path, RemoveBackslash(ExpandFileName(Standard))) <> 0 then begin
        MigrationCheckPlainPath(Path);
        Found := DirExists(AddBackslash(Path) + 'UserSetting');
        for J := 0 to ExecutableNames.Count - 1 do
          Found := Found or FileExists(AddBackslash(Path) + ExecutableNames[J]);
        for J := 0 to ConfigNames.Count - 1 do
          Found := Found or FileExists(AddBackslash(Path) + ConfigNames[J]);
        if Found then begin
          if (Result <> '') and (CompareText(Result, Path) <> 0) then
            RaiseException(CustomMessage('MigrationMultiple'));
          Result := Path;
        end;
      end;
    end;
  end;
end;

procedure MigrationValidateRoots(SourceRoot, TargetRoot: String);
begin
  SourceRoot := RemoveBackslash(ExpandFileName(SourceRoot));
  TargetRoot := RemoveBackslash(ExpandFileName(TargetRoot));
  if (Length(SourceRoot) <= 3) or (Length(TargetRoot) <= 3) or
    (Pos(Lowercase(AddBackslash(SourceRoot)), Lowercase(AddBackslash(TargetRoot))) = 1) or
    (Pos(Lowercase(AddBackslash(TargetRoot)), Lowercase(AddBackslash(SourceRoot))) = 1) then
    RaiseException(CustomMessage('MigrationUnsafe'));
  MigrationCheckPlainPath(SourceRoot);
  MigrationCheckPlainPath(TargetRoot);
end;

function MigrationEmptyDirectory(Path: String): Boolean;
var
  Entry: TFindRec;
begin
  MigrationCheckPlainPath(Path);
  Result := True;
  if not DirExists(Path) then Exit;
  if not FindFirst(AddBackslash(Path) + '*', Entry) then
    RaiseException(CustomMessage('MigrationUnsafe') + #13#10 + Path);
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
        Result := False;
        Exit;
      end;
    until not FindNext(Entry);
  finally
    FindClose(Entry);
  end;
end;

procedure MigrationCollect(Path, Relative: String; Files, Hashes, Directories: TStringList; Depth: Integer);
var
  Entry: TFindRec;
  Child, Key: String;
begin
  if (Depth > 64) or (Directories.Count >= 10000) then
    RaiseException(CustomMessage('MigrationUnsafe'));
  MigrationCheckPlainPath(Path);
  Directories.Add(Path);
  if not FindFirst(AddBackslash(Path) + '*', Entry) then
    RaiseException(CustomMessage('MigrationUnsafe') + #13#10 + Path);
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
        if (Entry.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then
          RaiseException(CustomMessage('MigrationUnsafe'));
        Child := AddBackslash(Path) + Entry.Name;
        Key := Relative + Entry.Name;
        if (Entry.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          MigrationCollect(Child, Key + '\', Files, Hashes, Directories, Depth + 1)
        else begin
          MigrationBytes := MigrationBytes + Int64(Entry.SizeHigh) * 4294967296 + Entry.SizeLow;
          if (Files.Count >= 10000) or (MigrationBytes > 10737418240) then
            RaiseException(CustomMessage('MigrationUnsafe'));
          Files.Add(Key);
          Hashes.Add(GetSHA256OfFile(Child));
        end;
      end;
    until not FindNext(Entry);
  finally
    FindClose(Entry);
  end;
end;

procedure MigrationReleaseLists;
begin
  if MigrationFiles <> nil then MigrationFiles.Free;
  if MigrationHashes <> nil then MigrationHashes.Free;
  if MigrationDirectories <> nil then MigrationDirectories.Free;
  if MigrationProgramFiles <> nil then MigrationProgramFiles.Free;
  if MigrationProgramHashes <> nil then MigrationProgramHashes.Free;
  MigrationFiles := nil;
  MigrationHashes := nil;
  MigrationDirectories := nil;
  MigrationProgramFiles := nil;
  MigrationProgramHashes := nil;
end;

procedure MigrationSnapshotProgram(Path: String);
begin
  MigrationCheckPlainPath(Path);
  if FileExists(Path) then begin
    MigrationProgramFiles.Add(Path);
    MigrationProgramHashes.Add(GetSHA256OfFile(Path));
  end;
end;

function MigrationCreateStage(TargetRoot: String): String;
var
  Attempt: Integer;
  Stamp: String;
begin
  Stamp := GetDateTimeString('yyyymmddhhnnsszzz', '-', ':');
  for Attempt := 1 to 100 do begin
    Result := AddBackslash(TargetRoot) + '.fileops-migration-' + Stamp + '-' + IntToStr(Attempt);
    if CreateDir(Result) then Exit;
    if not DirExists(Result) then RaiseException(CustomMessage('MigrationUnsafe'));
  end;
  RaiseException(CustomMessage('MigrationUnsafe'));
end;

procedure MigrationPrepare(SourceRoot, TargetRoot: String; ExecutableNames, ConfigNames: TStringList;
  OwnsOldUninstaller: Boolean);
var
  I, RootConfigCount: Integer;
  Source, Target, RootConfig: String;
begin
  MigrationPrepared := False;
  MigrationActivated := False;
  MigrationStage := '';
  MigrationReleaseLists;
  if SourceRoot = '' then Exit;
  SourceRoot := RemoveBackslash(ExpandFileName(SourceRoot));
  TargetRoot := RemoveBackslash(ExpandFileName(TargetRoot));
  MigrationValidateRoots(SourceRoot, TargetRoot);
  MigrationRootConfig := '';
  MigrationSourceRoot := SourceRoot;
  MigrationDataRoot := AddBackslash(SourceRoot) + 'UserSetting';
  MigrationFiles := TStringList.Create;
  MigrationHashes := TStringList.Create;
  MigrationDirectories := TStringList.Create;
  MigrationProgramFiles := TStringList.Create;
  MigrationProgramHashes := TStringList.Create;
  MigrationBytes := 0;
  RootConfigCount := 0;
  MigrationTargetRoot := TargetRoot;
  if DirExists(MigrationDataRoot) then
    MigrationCollect(MigrationDataRoot, '', MigrationFiles, MigrationHashes, MigrationDirectories, 0)
  else begin
    MigrationDataRoot := SourceRoot;
    RootConfigCount := 0;
    for I := 0 to ConfigNames.Count - 1 do begin
      if not MigrationLeaf(ConfigNames[I]) then RaiseException(CustomMessage('MigrationUnsafe'));
      Source := AddBackslash(SourceRoot) + ConfigNames[I];
      MigrationCheckPlainPath(Source);
      if FileExists(Source) then begin
        RootConfigCount := RootConfigCount + 1;
        RootConfig := Source;
      end;
    end;
    if RootConfigCount > 1 then RaiseException(CustomMessage('MigrationConflict'));
    if RootConfigCount = 1 then begin
      { v1.3 used this root JSON name; preserve its bytes, including DPAPI values. }
      MigrationDataRoot := SourceRoot;
      MigrationRootConfig := RootConfig;
      MigrationFiles.Add('settings.json');
      MigrationHashes.Add(GetSHA256OfFile(RootConfig));
    end;
  end;
  for I := 0 to ExecutableNames.Count - 1 do begin
    if not MigrationLeaf(ExecutableNames[I]) then RaiseException(CustomMessage('MigrationUnsafe'));
    MigrationSnapshotProgram(AddBackslash(SourceRoot) + ExecutableNames[I]);
  end;
  if OwnsOldUninstaller then begin
    MigrationSnapshotProgram(AddBackslash(SourceRoot) + 'unins000.exe');
    MigrationSnapshotProgram(AddBackslash(SourceRoot) + 'unins000.dat');
    MigrationSnapshotProgram(AddBackslash(SourceRoot) + 'unins000.msg');
  end;
  Target := AddBackslash(TargetRoot) + 'UserSetting';
  if ((MigrationFiles.Count > 0) or (MigrationDirectories.Count > 0)) and not MigrationEmptyDirectory(Target) then
    RaiseException(CustomMessage('MigrationConflict') + #13#10 + Target);
  if (MigrationFiles.Count > 0) or (MigrationDirectories.Count > 0) then begin
    if not ForceDirectories(TargetRoot) then RaiseException(CustomMessage('MigrationUnsafe'));
    MigrationStage := MigrationCreateStage(TargetRoot);
    Log('Legacy settings staging: ' + MigrationStage);
    { Atomic CreateDir reserves a unique sibling. Never reuse another staging. }
    for I := 0 to MigrationDirectories.Count - 1 do begin
      Source := MigrationDirectories[I];
      Target := MigrationStage + Copy(Source, Length(MigrationDataRoot) + 1, Length(Source));
      if not ForceDirectories(Target) then RaiseException(CustomMessage('MigrationUnsafe'));
    end;
    for I := 0 to MigrationFiles.Count - 1 do begin
      Source := AddBackslash(MigrationDataRoot) + MigrationFiles[I];
      if RootConfigCount = 1 then Source := RootConfig;
      Target := AddBackslash(MigrationStage) + MigrationFiles[I];
      MigrationCheckPlainPath(Source);
      MigrationCheckPlainPath(Target);
      if not ForceDirectories(ExtractFileDir(Target)) or
         not CopyFile(Source, Target, True) then RaiseException(CustomMessage('MigrationUnsafe'));
      if (GetSHA256OfFile(Source) <> MigrationHashes[I]) or
         (GetSHA256OfFile(Target) <> MigrationHashes[I]) then
        RaiseException(CustomMessage('MigrationChanged'));
    end;
  end;
  MigrationPrepared := True;
end;

procedure MigrationActivate(TargetRoot: String);
var
  I: Integer;
  Target: String;
begin
  if not MigrationPrepared then Exit;
  if CompareText(RemoveBackslash(ExpandFileName(TargetRoot)), MigrationTargetRoot) <> 0 then
    RaiseException(CustomMessage('MigrationUnsafe'));
  if MigrationStage <> '' then begin
    MigrationCheckPlainPath(TargetRoot);
    MigrationCheckPlainPath(MigrationStage);
    for I := 0 to MigrationFiles.Count - 1 do
      if GetSHA256OfFile(AddBackslash(MigrationStage) + MigrationFiles[I]) <> MigrationHashes[I] then
        RaiseException(CustomMessage('MigrationChanged'));
    Target := AddBackslash(TargetRoot) + 'UserSetting';
    if not MigrationEmptyDirectory(Target) then
      RaiseException(CustomMessage('MigrationConflict') + #13#10 + Target);
    if DirExists(Target) then
      if not RemoveDir(Target) then RaiseException(CustomMessage('MigrationUnsafe'));
    if not RenameFile(MigrationStage, Target) then RaiseException(CustomMessage('MigrationUnsafe'));
    MigrationStage := '';
  end;
  MigrationActivated := True;
end;

procedure MigrationCleanup;
var
  I, Index: Integer;
  Files, Hashes, Directories: TStringList;
  Source: String;
begin
  if not MigrationActivated then Exit;
  { Fail closed if the old source changed after its verified copy. No DelTree. }
  MigrationCheckPlainPath(MigrationSourceRoot);
  MigrationCheckPlainPath(MigrationTargetRoot);
  for I := 0 to MigrationFiles.Count - 1 do
    if GetSHA256OfFile(AddBackslash(MigrationTargetRoot) + 'UserSetting\' + MigrationFiles[I]) <> MigrationHashes[I] then
      RaiseException(CustomMessage('MigrationChanged'));
  if MigrationDataRoot <> MigrationSourceRoot then begin
    Files := TStringList.Create;
    Hashes := TStringList.Create;
    Directories := TStringList.Create;
    try
      MigrationBytes := 0;
      MigrationCollect(MigrationDataRoot, '', Files, Hashes, Directories, 0);
      if (Files.Count <> MigrationFiles.Count) or
         (Directories.Count <> MigrationDirectories.Count) then
        RaiseException(CustomMessage('MigrationChanged'));
      for I := 0 to Files.Count - 1 do begin
        Index := MigrationFiles.IndexOf(Files[I]);
        if Index < 0 then RaiseException(CustomMessage('MigrationChanged'));
        if Hashes[I] <> MigrationHashes[Index] then
          RaiseException(CustomMessage('MigrationChanged'));
      end;
      for I := 0 to Directories.Count - 1 do
        if MigrationDirectories.IndexOf(Directories[I]) < 0 then
          RaiseException(CustomMessage('MigrationChanged'));
    finally
      Files.Free;
      Hashes.Free;
      Directories.Free;
    end;
  end else if MigrationRootConfig <> '' then begin
    MigrationCheckPlainPath(MigrationRootConfig);
    if GetSHA256OfFile(MigrationRootConfig) <> MigrationHashes[0] then
      RaiseException(CustomMessage('MigrationChanged'));
  end;
  for I := 0 to MigrationProgramFiles.Count - 1 do begin
    MigrationCheckPlainPath(MigrationProgramFiles[I]);
    if GetSHA256OfFile(MigrationProgramFiles[I]) <> MigrationProgramHashes[I] then
      RaiseException(CustomMessage('MigrationChanged'));
  end;
  for I := 0 to MigrationProgramFiles.Count - 1 do begin
    MigrationCheckPlainPath(MigrationProgramFiles[I]);
    if not DeleteFile(MigrationProgramFiles[I]) then
      RaiseException(CustomMessage('MigrationRetained'));
  end;
  if MigrationDataRoot <> MigrationSourceRoot then begin
    for I := 0 to MigrationFiles.Count - 1 do begin
      Source := AddBackslash(MigrationDataRoot) + MigrationFiles[I];
      MigrationCheckPlainPath(Source);
      if GetSHA256OfFile(Source) <> MigrationHashes[I] then
        RaiseException(CustomMessage('MigrationChanged'));
      if not DeleteFile(Source) then
        RaiseException(CustomMessage('MigrationRetained'));
    end;
    for I := MigrationDirectories.Count - 1 downto 0 do
      if not RemoveDir(MigrationDirectories[I]) then
        RaiseException(CustomMessage('MigrationRetained'));
  end else if MigrationRootConfig <> '' then begin
    MigrationCheckPlainPath(MigrationRootConfig);
    if GetSHA256OfFile(MigrationRootConfig) <> MigrationHashes[0] then
      RaiseException(CustomMessage('MigrationChanged'));
    if not DeleteFile(MigrationRootConfig) then RaiseException(CustomMessage('MigrationRetained'));
  end;
  { Unknown files/subfolders are deliberately retained; only an empty root goes. }
  if not RemoveDir(MigrationSourceRoot) then RaiseException(CustomMessage('MigrationRetained'));
end;
