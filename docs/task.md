# App005 naming and layout cleanup

- [x] 1. Centralize product names and restore legacy installation/update detection. 31 targeted tests passed.
- [x] 2. Move packaging to installer/, automation to scripts/, and consolidate assets/.
- [x] 3. Unify build/signing, remove fixed versions/other-repository paths, and add release metadata.
- [x] 4. Update current documentation and remove confirmed duplicates; recoverably archive old generated folders.
- [x] 5. Run regression/static/package checks and record remaining manual installation checks. 201 tests passed; app/launcher/installer builds passed. EXE bytecode matches current path-handling sources; both bundled icons match their originals. Checksums verified. Native install/upgrade/startup/uninstall remain manual checks.

Preserve the installer AppId, single-instance identity, and historical release
binaries. Default all installer runs to Programs/FileOps without reusing prior
paths. User explicitly requested fresh
settings/logs/history in %LOCALAPPDATA%/Programs/FileOps/UserSetting without importing old data.
No repository folder/remote rename, actual installation migration, or publication
is part of this cleanup.

## v1.4.2 signed publication (user authorized 2026-10-06)

- [x] Set the release version and document the fresh UserSetting contract.
- [x] Verify regression tests, source/package layout, and release prerequisites. Signing gates and isolated test settings added; 205 tests passed. Certificate/SimpleSign present, but the agent session fails the private-key filter. User will execute the canonical signing wrapper directly in administrator PowerShell.
- [ ] Commit the approved changes on main and build/sign/verify all three executables.
- [ ] Push main and matching tag, publish only verified artifacts, and check GitHub state/digests.
