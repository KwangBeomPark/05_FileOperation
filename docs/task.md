# v1.4.3 signed publication (user authorized 2026-10-07)

- [x] 1. Set v1.4.3 and document App05 naming, preserved UserSetting, and the one-time manual v1.4.2 upgrade.
- [x] 2. Re-run regression/static checks and prepare the reviewed main-branch source commit: 229 tests, Ruff, compile/dependency checks, and PowerShell syntax passed.
- [ ] 3. Build/sign with the user's active SimplySign session; verify all signatures, timestamps, packaged sources, and checksums.
- [ ] 4. Push main and the matching tag; publish verified artifacts and compare GitHub asset digests.

Publication is authorized. A visible certificate is not proof of private-key access.
Native clean-PC installation/upgrade checks remain a separate manual gate.
The signing attempt stopped before building: SCardSvr is stopped and the agent
session is not elevated. The user must run sign.ps1 in their administrator
PowerShell with SimplySign logged in. No signed v1.4.3 artifacts are claimed yet.

# App05 normalization and PL Suite pipeline (2026-10-06)

- [x] 1. Normalize identity/EXE/spec/launcher to App05; keep old names centralized for compatibility.
- [x] 2. Add standard PowerShell entry points, signed-only staging/promotion, and explicit non-clobber publishing.
- [x] 3. Delete 38 confirmed obsolete release files (2,007,781,004 bytes), protecting the latest signatures/data.
- [x] 4. Prepare the four-file local v1.4.2 dual-alias set; preserve original signed files/provenance. Alias-only is not a rebuilt App05 binary and cannot be republished.
- [x] 5. 229 regression tests, Ruff/compile/dependency/PowerShell syntax gates passed. Actual unsigned app/launcher/Inno build and packaged sources/icons match. Opus 5.5 reviewed twice; promotion/custom-upgrade/verifier/dev-stage issues fixed, manual v1.4.2 transition documented, no remaining code blockers found. See APP05_PIPELINE_VALIDATION.md for untested signing/native-install boundaries and non-blocking follow-ups.

This task does not replace public v1.4.2. A new signed normalized release requires a new
version decision and the user's active SimplySign session. UserSetting and the stable
Windows identities remain unchanged. See RELEASE.md for staging/alias provenance.

# Historical App005 naming and layout cleanup

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
- [x] Verify regression tests, source/package layout, and release prerequisites. Signing gates and isolated test settings added; 205 tests passed again after signing. The user resolved the agent-session private-key access limitation by executing the canonical signing wrapper directly in administrator PowerShell.
- [x] Commit the approved changes on main and build/sign/verify all three executables. Build source commit: 5f417c605fe31a30c6fea544627cca0aab8d9c41. All files are Authenticode Valid with the selected signer and DigiCert timestamp; SignTool /pa /all /v has zero warnings/errors. Packaged app (49 modules plus main), launcher sources, icons, and checksums match.
- [x] Push main and matching tag, publish only verified artifacts, and check GitHub state/digests. v1.4.2 is published as Latest, not draft/prerelease; all four uploaded assets match local sizes and SHA-256. Current updater/launcher select the published canonical installer and digest. See RELEASE_VALIDATION_v1.4.2.md.
