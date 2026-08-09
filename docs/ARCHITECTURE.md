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
- `tools/App05_FileOps.pyw` intentionally repeats the repository constants so the launcher stays standalone; a regression test enforces parity with `release_config.py`.
- `tools/build_all.py` creates the PyInstaller version resource, calls Inno Setup with the same version, runs tests, and writes an installer checksum manifest.
- The in-app updater and `App05_FileOps` accept only the exact versioned setup filename from GitHub Releases, verify trusted redirect hosts, and verify the published SHA-256 digest before execution.
- Authenticode signing is a release requirement for public distribution; see `docs/RELEASE.md`.
