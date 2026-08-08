# IntegratedDataTool v1.2.0

## What changed

- Added bounded, cancellable process probes for diagnostics, task preflight, Office, OCR, browser, SMTP, and backup-folder checks.
- Improved scheduled task validation so errors identify the affected feature, the failed check, and the corrective action.
- Added portable backup provenance that records original file names without storing absolute paths and restores safely around name collisions.
- Made backup-folder scanning asynchronous and added exact-history versus legacy-backup indicators.
- Completed the Phase 1–5 stability, localization, scheduling, tray, icon, and recovery regression pass.
- Updated the launcher and in-app updater to use the canonical `KwangBeomPark/05_FileOperation` release repository directly.

## Validation

- Full automated test suite, source compilation, dependency checks, Ruff fatal-error checks, and Git whitespace checks passed.
- A PyInstaller-packaged executable completed the diagnostics workflow successfully.
- Backup provenance, legacy fallback, duplicate-name restore behavior, scheduled preflight, cancellation, and timeout paths were verified.

## Known boundaries

- Active conversion and synchronization jobs use cooperative cancellation and are not force-killed, to avoid partial or corrupted output.
- Real disconnected SMB shares, Windows sleep/resume, lock-screen transitions, and Office first-run or licensing dialogs require environment-specific testing.
- Windows binaries are currently unsigned. Verify downloads using the included SHA-256 manifest; Windows SmartScreen or Smart App Control may warn or block execution.
