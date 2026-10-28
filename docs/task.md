# SA Team nested tabs (user authorized 2026-10-25)

- [x] 1. Reorder top tabs to Tasks / Sync / Convert Files / SA Team, nesting EML / PDF / OCR under SA Team. Preserve existing widget instances, settings and execution order.
- [x] 2. Update localized labels, current-screen/F1 help, diagnostic navigation and nested-tab locking. Nine new layout tests and 24 related manual/i18n/task-selection checks passed. Rendered the real MainWindow with in-memory settings in Korean and reviewed both navigation levels.
- [x] 3. 349 regression tests OK (one existing native-installer fixture class skipped), 32 backup assertions, Ruff/compileall/pip check and Inno compilation passed. Updated multilingual README/manual/navigation docs. No version bump, signing, installation, GitHub push or publication in this UI-only step. Live Office/scheduled job execution was not performed.

# Run change summary (user authorized 2026-10-22)

- [x] 1. Add a read-only, typed-plan change analyzer using the existing sync dry run. Distinguish copies, conversion inputs, renames, backup moves and permanent deletion; never invent future output counts. 16 isolated analyzer tests passed.
- [x] 2. Add a shared localized confirmation to manual unified and individual runs. Analyze off the GUI thread with cancellation/timeouts; recheck after confirmation. Scheduled runs log estimates without a popup; unavailable estimates do not change the existing scheduled preflight/consent policy.
- [x] 3. 340 regression tests OK (one pre-existing native-installer fixture class skipped), 32 backup assertions, Ruff, compileall, pip check and Inno compilation passed. Rendered/reviewed the real Qt dialog in Korean/English/Polish using fictional data. Added close/cancel guards, unknown-count handling and OCR TXT overwrite warnings. No version bump/publication. Live Office/shared-drive performance and packaged frozen execution remain untested. See RUN_CHANGE_SUMMARY.md.

# Legacy install migration (user authorized 2026-10-12)

- [x] 1. Default to Programs/FileOps and identify only known legacy folders. Copy UserSetting or the old setting_integrated.json; never merge conflicting settings.
- [x] 2. Implement staging, SHA-256 verification and post-install activation/cleanup. Remove only known unchanged old leaves; keep unrelated files, changed files, and failure sources. Actual production-user folders were not mutated.
- [x] 3. Add UTF-8 BOM and Korean/English/Polish setup messages, migration documentation and 15 native fixture scenarios. Production/fixture Inno compilation passed; 254 regression tests, 32 backup assertions, Ruff/compile/dependency checks passed.
- [ ] 4. Execute native fixture migrations and inspect the rendered Korean installer in a signed or policy-approved isolated Windows environment. Here Application Control WinError 4551 blocks unsigned execution (one test class skipped; its 15 scenarios are NOT claimed passed). Do this before releasing a new installer.

This changes future installers only. Do not move/delete actual user folders while testing,
or replace the published v1.4.3 installer. Signing/publication remain separate actions.
The existing Windows PowerShell backup gate initially could not auto-load Get-FileHash.
The build wrapper now explicitly imports the built-in Utility module from PSHOME;
the actual Windows PowerShell 5.1 backup gate passed again without changing policy.

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


# Suite standardization phase 1 (2026-10-07)

- [x] Record the six-app baseline and compatibility exceptions in docs/SUITE_STANDARDIZATION.md.
- [x] Confirm UserSetting exclusion and add local environment/private-key protection.
- [x] Review tracked sensitive paths, known private references, and installation sources; record the scope and deferred runtime checks in docs/STANDARDIZATION_PHASE1_REVIEW.md.

This phase does not change App05 runtime code, installation behavior, user data, or published artifacts. Existing release tasks above are preserved.

# Suite standardization phase 2 (2026-10-07)

- [x] Retain stable identities and previous installation folders; defer obsolete EXE cleanup until successful installation and payload hash verification.
- [x] Register compatibility EXEs for normal closure; block the first payload copy if an executable remains locked, without force termination.
- [x] Run isolated regression, compiler, dependency and lint gates: 230 tests passed; record independent review in STANDARDIZATION_PHASE2_REVIEW.md.
- [ ] Signed/native running-upgrade, refusal, failure/cancel, uninstall preservation and published asset verification remain release gates.

Existing signing/publication tasks and protected release-folder permissions remain unchanged.

# Suite standardization phases 3–5 (2026-10-08)

- [x] Preserve complete settings and in-memory values on write/encryption failures; distinguish read errors from corruption and preserve unique corruption backups.
- [x] Validate the entire settings dialog before a single atomic save; retain the dialog and show a translated failure message.
- [x] Move canonical PyInstaller spec to installer/ with a compatibility wrapper; update build paths and public/local code maps.
- [x] Add backup/restore documentation and connect isolated backup safety checks to the build gate.
- [x] Run isolated source and failure-injection regressions; record evidence in STANDARDIZATION_PHASE3_5_REVIEW.md.
- [ ] Same-user DPAPI/native workflow, locked installed settings and signed install/upgrade checks remain release gates.


# Single-installer release preparation (2026-10-09)

- [x] Preserve user build_all.py changes and keep unused version 1.4.3 after read-only tag/release checks.
- [x] Generate App05_FileOps_Setup_v<version>.exe once, retain historical reader names, and align installer/manifest checksum production with validation.
- [x] Run 250 isolated regression tests, 32 backup safety assertions and lint/diff checks; see RELEASE_CHECKLIST.md.
- [ ] Approved clean source commit, actual KSP signing, native startup/DPAPI/upgrade/uninstall checks and publication remain separate gates.
