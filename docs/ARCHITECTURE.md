# FileOps Hub Architecture

## Runtime Boundaries

```text
PyQt tabs -> typed RunConfig -> RunPlan -> preflight -> TaskRunner -> core converters
                    |                         |
                    +-> validation errors      +-> RunReport -> UI worker signals
                                                       |
                                                       +-> RunJournal -> reports/*.json + *.txt
```

- Each tab converts only its visible state into a typed `build_run_config()` result.
- `TaskTab` combines active configs into a `RunPlan`, then runs common dependency checks before work starts.
- `TaskRunner` is PyQt-free and owns sequential execution, cancellation state, and reporting.
- `TaskWorker` is the only Qt adapter for the integrated runner.
- `RunJournal` atomically stores compact metadata and one readable report for every started manual or scheduled run. The settings JSON keeps only the existing latest-per-feature summary.
- `manual_content.py` is the single localized source for Getting Started and per-feature guidance. `ManualDialog` opens the same content from the Help menu, `F1`, or the current-tab help entry point.
- Feature tabs own their prerequisite state. They disable only dependent actions while preserving typed validation for direct and scheduled execution.
- UI progress and status signals also update the journal heartbeat. Five minutes without a signal is shown as `Possibly stalled`; it does not force-kill a real file or Office operation.
- Direct tab actions reuse the same preflight contract where external dependencies can cause destructive work, notably Office conversion.
- `probe_runner` accepts only named allow-listed probes and runs them in disposable spawned processes with fixed time budgets. This termination boundary never wraps real conversion or synchronization work.

## External Dependencies

- OCR uses Tesseract first and Windows OCR as a fallback.
- EML rendering requires the Playwright driver and Chromium runtime.
- Office conversion requires the specific Excel, Word, or PowerPoint COM application for the selected source files.
- SMTP is optional. Reports are always saved locally before optional email delivery.

## Recovery Boundaries

- Successful source backup moves append portable provenance to `Original Backup/.fileops-backup.jsonl`.
- Provenance stores file names and timestamps, never absolute business paths. Missing, malformed, or unsupported records fall back to legacy stored-name recovery.
- Restore targets are collision-safe, and recovery never overwrites an existing source file.

## Distribution Boundaries

- `src/version.py` is the single release-version source.
- `src/core/release_config.py` owns the installed application's default GitHub repository and release URL construction.
- `src/app_identity.py` owns product ID `App05_FileOps`, executable/dual-installer/launcher names, approved default install folder `Programs/FileOps`, and centralized legacy compatibility.
- `scripts/App05_FileOps_Launcher.pyw` bundles the dependency-free identity and release configuration modules; it does not depend on an existing installation.
- `scripts/build.ps1` / `scripts/sign.ps1` wrap the Python build engine. Independent staging, actual Windows signature checks, complete manifest/checksum validation, and rollback-protected promotion keep unsigned builds out of release/. `publish_release.py` additionally requires a clean matching source commit and never replaces a published version.
- The in-app updater and launcher share the accepted installer names, verify trusted redirect hosts and SHA-256 before execution, and do not mistake pre-v1.4.1 launchers for installers.
- Runtime and packaging use the single root `assets/` directory, including inside the frozen application.
- Fresh configuration, logs, and run history live in `%LOCALAPPDATA%/Programs/FileOps/UserSetting`; old IntegratedDataTool or LocalAppData/FileOps data is not imported. Frozen custom installations use UserSetting beside the actual app executable. Source runs use the approved default. The installer creates UserSetting, excludes it from the payload, and preserves it on uninstall. Fresh installations default to Programs/FileOps with a visible directory page; upgrades retain the existing install folder and UserSetting.
- Authenticode signing is a release requirement for public distribution; see `docs/RELEASE.md`.
