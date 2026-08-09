# IntegratedDataTool v1.3.0

## What changed

- Added a localized user manual for Getting Started, Run Tasks, Sync Folders, EML, PDF, OCR, Convert Files, and Settings in English, Korean, and Polish.
- Added Help menu entries, `F1`, and a current-screen help button that opens guidance for the active tab.
- Added guided workflow steps and prerequisite-aware action buttons so users can see what must be configured before running a task.
- Made Sync require a current preview before manual synchronization and invalidate stale previews after folder or group changes.
- Made Convert Files invalidate stale scans after source or target-format changes and standardized the user-facing name as File Conversion.
- Added durable manual and scheduled run history, readable reports, interrupted-run recovery, and a non-destructive “possibly stalled” indicator.
- Added finer file/page progress reporting for integrated folder synchronization and PDF conversion.

## Validation

- All 142 automated tests passed.
- Python compilation, package dependency checks, Ruff `E9/F/B` checks, and Git whitespace checks passed.
- Korean, English, and Polish catalog parity and cross-language leakage checks passed.
- The localized main window, per-tab workflows, and manual dialog were rendered and inspected at the supported desktop size.
- The PyInstaller application, launcher, Inno Setup installer, embedded version/icon metadata, and SHA-256 manifest are verified during the release build.

## Known boundaries

- Active conversion and synchronization jobs use cooperative cancellation to avoid corrupting partial output.
- Disconnected SMB/SharePoint paths, Windows sleep/resume, Office first-run or licensing dialogs, and long tray-resident runs still require environment-specific testing.
- Public Windows release assets must be Authenticode-signed. Unsigned development artifacts may be blocked by Windows Smart App Control.
