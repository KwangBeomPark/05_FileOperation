# FileOps Hub Development Notes

## 2026-08-08 — Phase 1: Scheduled-run reliability

### Implemented decisions

- Persist separate timestamps for the latest schedule attempt, worker start, success, and failure.
- Retry only failures that happen before a task worker starts: 10-minute delay, maximum three attempts per day.
- Never automatically retry after a worker starts. File conversion or synchronization may have partially changed files, so an automatic second run could duplicate or repeat destructive work.
- Show the next run or retry, the last outcome, and the requirement that FileOps Hub remain running.
- Offer an unchecked installer option that starts FileOps Hub with Windows in hidden tray mode.
- Enforce one running instance. A later desktop or launcher invocation activates the existing window instead of creating a second scheduler.

### Follow-up observations

1. The Windows startup shortcut runs only after the user signs in. Logged-out or pre-login execution still needs a future Windows Task Scheduler/service mode.
2. Existing installations must run a future installer and select the startup option; the current Settings screen cannot toggle startup registration yet.
3. Persistent run history is still a separate planned phase. The new schedule summary shows only the latest success or failure.
4. Real suspend/resume, overnight network-share availability, and locked-screen Office COM behavior still need environment testing even though deterministic time-boundary tests now pass.
5. The source QA process used roughly 230–240 MB while idle. This is acceptable for the current desktop scope but should be measured again before broad workstation deployment.

### Next planned phase

Protect source files in Convert Files: default to keeping originals, add a destructive-action summary, and prefer recoverable backup/move behavior over permanent deletion.

## 2026-08-08 — Phase 2: Convert Files source protection

### Implemented decisions

- Keep every source file by default. Existing `bypass_delete_original=true` settings are deliberately ignored by the new safe default and the legacy key is persisted as `false`.
- Replace permanent deletion with an explicit, recoverable move to `Original Backup` under each source folder.
- Move a source only after the converter reports success and the output exists as a non-empty file.
- Treat backup-move failure as a visible partial failure while leaving both the converted output and the source in place.
- Ask for confirmation immediately before a direct conversion run. The confirmation lists file count, total size, and source, output, and backup folders; `No` is the default.
- Preserve an existing backup by generating a numbered backup filename instead of overwriting it.

### Audit status

- **Fixed:** permanent source deletion and the unsafe default inherited from older settings.
- **Fixed:** source/output path equality when a file is converted to its current extension. The output now receives `_converted` and never aliases the source.
- **Fixed:** two source files in one run resolving to the same output filename. Output paths are reserved while the plan is built.
- **Fixed:** overwriting a pre-existing output at the core converter boundary.
- **Mitigated:** scheduled runs expose backup moves as preflight warnings. The action remains recoverable, but scheduled execution cannot display the direct-run confirmation dialog.
- **Open:** real Office COM conversions on locked workstations and network shares still require environment validation.

### Follow-up observations before Phase 3

1. Do not add automatic backup expiry yet. Retention cleanup is destructive and should wait until run history and a recovery/cleanup screen can show exactly what will be removed.
2. A future scheduling UI should include a separate `Allow scheduled source backup moves` consent. For now, the checked Convert Files option and preflight warning are the stored consent path.
3. The next planned phase should be a run-readiness/history view: selected features, last outcome per feature, pending retry, and source-backup action should be visible before unattended scheduling is enabled.

## 2026-08-08 — Phase 3: Run readiness and latest-result dashboard

### Implemented decisions

- Expand the Run Tasks grid to show selection, feature, readiness, current status, and the latest persisted result.
- Check only selected features. Configuration errors are shown against the responsible feature instead of opening unrelated validation messages.
- Persist one compact latest-result snapshot per feature: status, completion count, total count, timestamp, and a short detail. Full reports remain in the existing report/log path.
- Require a separate, persistent consent before a scheduled Convert Files run may move sources to `Original Backup`.
- Revoke that consent whenever the Convert Files source action changes or Convert Files is newly selected for scheduling.
- Hide the consent control unless daily scheduling, Convert Files selection, and source backup movement are all active.
- Convert an unexpected worker exception into a visible failure completion so the UI and other feature tabs are always unlocked.

### Audit status

- **Fixed:** no feature-level readiness view before starting an unattended run.
- **Fixed:** latest outcomes disappeared from the dashboard after restarting the app.
- **Fixed:** scheduled source backup movement relied only on the general Convert Files checkbox.
- **Fixed:** an unhandled worker exception could leave the entire application locked in a running state.
- **Mitigated:** readiness checks Office package availability without launching every Office COM app. The execution preflight still performs the deep launch check.
- **Open:** the dashboard stores only the latest result per feature, not a browsable multi-run history.

### Follow-up observations before Phase 4

1. The most useful next increment is a diagnostics and recovery screen rather than adding more automation: test network folders, Office COM, OCR, SMTP, and open the relevant settings from each failure.
2. Full multi-run history should reuse the existing report files and add an `Open report` action instead of putting large logs in the configuration JSON.
3. `Original Backup` recovery and cleanup should be added together. Cleanup must remain manual until the user can preview files and restore them from the same screen.
4. Real network-share disconnect/reconnect, Windows lock-screen Office automation, and overnight resume behavior remain environment-validation items before a commercial rollout.

## 2026-08-08 — Phase 4: Diagnostics and recovery routing

### Implemented decisions

- Add a dedicated Diagnostics and Recovery dialog instead of adding another permanent table to the Run Tasks dashboard.
- Diagnose only selected features and reuse their current typed run configurations.
- Keep diagnostics non-destructive: inspect file/folder accessibility, but never create probe files in business folders.
- Launch and close required Office COM applications, launch the EML headless browser, and validate the configured OCR engine in a background diagnostics thread.
- Test SMTP with a five-second TCP connection only. Diagnostics never authenticate and never send a test message.
- Show configuration-validation failures alongside runtime dependency failures and route each failed/warning row to its feature tab, Run Tasks consent, or Settings.
- Prevent unexpected diagnostics exceptions from escaping the worker and leaving the dialog without a result.

### Audit status

- **Fixed:** dependency failures were visible only when the full task run was already being started.
- **Fixed:** users had to infer which tab or settings page could resolve a preflight failure.
- **Fixed:** SMTP configuration had no safe connection-only test.
- **Fixed:** diagnostic Office, browser, and network checks would otherwise block the main UI thread.
- **Mitigated:** folder write access uses Windows access checks without creating files. Actual writes can still fail later because of SMB disconnects, quota, or concurrent permission changes.
- **Open:** a stalled OS network call or Office first-run/license dialog can keep the diagnostics worker busy longer than expected; hard process-level timeouts are still needed before commercial rollout.

### Follow-up observations before Phase 5

1. Add `Original Backup` recovery before cleanup: preview backed-up files, restore with collision-safe names, and open the containing folder. Do not add deletion yet.
2. A future explicit `Send test email` action may validate TLS and authentication, but it must be separate from passive diagnostics because it creates an external message.
3. Isolate Office and network probes in timeout-controlled helper processes so a broken COM server or disconnected share cannot hold diagnostics indefinitely.
4. Full multi-run history should continue to use report files, with filters and an `Open report` action rather than expanding the settings JSON.

## 2026-08-08 — Phase 5: Original Backup recovery

### Implemented decisions

- Add a dedicated recovery dialog from Convert Files instead of mixing backup contents into the conversion scan table.
- Preview the actual backup file name, size, modified time, and proposed restore target before any file operation.
- Restore only explicitly selected rows after a confirmation dialog whose default action is `No`.
- Never overwrite a source file. When the source name already exists, restore to a numbered `_restored_N` name.
- Reject paths outside the selected source folder's direct `Original Backup` directory and ignore symbolic links.
- Continue restoring independent files after one failure; failed items remain in `Original Backup` and are reported by name.
- Allow opening the backup folder in Explorer, but do not create, clean, expire, or delete backups from this screen.
- Keep compatibility with backups made before recovery history existed. Their real backup names are displayed instead of guessing an earlier filename.

### Audit status

- **Fixed (P1):** source backup movement had no in-app return path, forcing manual Explorer operations.
- **Fixed (P1):** a manual restore could overwrite a new file with the same name; recovery now always selects a free target name.
- **Fixed (P2):** users could not preview recovery destinations or isolate a subset of files.
- **Fixed (P2):** one locked or unavailable backup file could obscure the outcome for other files; results are now per file.
- **Mitigated (P2):** direct-child validation and symlink rejection prevent the recovery service from moving arbitrary paths supplied outside the dialog.
- **Open (P2):** legacy collision-numbered backups do not contain their pre-move original filename. The dialog exposes the real restore target and does not infer potentially wrong names.
- **Open (P2):** listing a very large or unavailable network backup folder is synchronous. A process-isolated scan with a timeout is still recommended for commercial hardening.

### Follow-up observations before Phase 6

1. Record a small, append-only backup manifest for future moves so recovery can show both the original path and stored backup name. Manifest failure must never turn a successful conversion into source loss.
2. Add process-level timeouts for network-folder, Office COM, and diagnostics probes as one reliability phase rather than separate thread-only fixes.
3. Add a report-backed multi-run history view before considering manual retention cleanup. Cleanup must remain a separate, explicit action with preview and no automatic default.
4. Keep the current recovery dialog separate from conversion execution; its different intent and confirmation boundary are clearer than adding more states to the scan table.

## 2026-08-08 — Phase 6: bounded probes and portable backup provenance

### Implemented decisions

- Preserve Phases 1–5 in local checkpoint commit `375f102` after all 97 baseline tests passed.
- Execute only an allow-listed set of non-destructive probes in disposable spawned processes; arbitrary callables cannot be submitted to the worker.
- Apply fixed budgets: folder and backup listing 8 seconds, SMTP socket 5 seconds, OCR/browser 15 seconds, and Office COM 20 seconds.
- Terminate the probe process tree on timeout or cancellation. Do not apply this kill policy to real conversions or synchronization jobs.
- Run Diagnostics in a cancellable thread and process combination. Closing a running diagnostics dialog requests cancellation instead of destroying a live thread.
- Keep direct-run preflight responsive with a cancellable progress dialog; scheduled preflight uses a hidden nested event loop so tray and Qt events continue to be processed.
- Scan Original Backup asynchronously with a generation token so cancelled or late results cannot replace a newer folder selection.
- Store future backup provenance in `.fileops-backup.jsonl` beside the backup files. Records contain only schema, event, stored name, original name, size, and UTC time—never an absolute source path.
- Treat manifest writes as best-effort recovery metadata. A manifest failure produces a warning but never reverses a completed source move or marks the source as lost.
- Replay backup and restore events, ignore malformed/unsupported lines, reject path-like names and manifest symlinks, and fall back to legacy stored-name recovery.

### Audit status

- **Fixed (P1):** Office, browser, OCR, SMTP, or disconnected-folder checks could wait indefinitely inside the application process.
- **Fixed (P1):** a running diagnostics thread could not be cancelled safely and prevented the dialog from closing.
- **Fixed (P2):** backup listing could block the recovery dialog on an unavailable network share.
- **Fixed (P2):** collision-numbered future backups could not be mapped back to their exact original file name.
- **Fixed (P2):** a late backup scan result could conceptually replace a newer selection; results now carry a generation token.
- **Mitigated (P2):** direct and scheduled preflight remain synchronous from the caller's perspective, but execute work off the UI thread while the Qt event loop stays responsive.
- **Open (P2):** real conversion and synchronization workers are cooperative and may still wait on a blocked OS or Office operation. Hard-killing them is intentionally excluded because outputs may be partially written.
- **Open (P2):** real disconnected SMB shares, Windows lock/unlock, Office first-run dialogs, and sleep/resume require environment testing outside unit tests.

### Follow-up observations before Phase 7

1. Add report-backed multi-run history with filters and an `Open report` action; do not expand settings JSON with full logs.
2. Add step heartbeats and a user-visible `Possibly stalled` state before considering any force-stop policy for real file operations.
3. Keep retention cleanup separate until recovery manifests and report history have been used in real environments. Cleanup must remain manual, previewed, and default to no selection.
4. An explicit SMTP authentication/test-message action remains separate from passive diagnostics because it sends external data.

## 2026-08-09 — Maintenance pass 1: naming and extension boundaries

### Implemented decisions

- Keep this pass behavior-neutral: no workflow, storage schema, timeout, file-operation, or UI interaction changes.
- Centralize the installed application's canonical GitHub repository and URL construction in `src/core/release_config.py`.
- Keep the bootstrap launcher self-contained instead of importing the application package. Document that duplication and enforce constant parity with a regression test.
- Replace ambiguous temporary names in probe dispatch, preflight checks, backup scanning, and the hidden Qt event-loop bridge with role-specific names.
- Add boundary documentation for disposable probes, cooperative real jobs, backup provenance, and collision-safe restore behavior.

### Audit status

- **Fixed (P2):** repository defaults and release URL formatting were repeated across application modules and could drift during a future rename.
- **Fixed (P3):** generic names such as `result`, `state`, `ctx`, and `req` obscured ownership in asynchronous and process-boundary code.
- **Mitigated (P2):** the standalone launcher still repeats repository constants by design; parity is now executable documentation through tests.
- **Open (P2):** diagnostic and preflight localization still contains inline multilingual strings and a legacy replacement table. Moving these into the shared i18n catalog should be a separate behavior-reviewed pass.
- **Open (P2):** probe dispatch is intentionally a closed conditional allow-list. If the probe set grows substantially, introduce a typed registry while preserving the same security boundary.

## 2026-08-09 — Maintenance pass 2: localization boundaries and language QA

### Implemented decisions

- Keep saved synchronization group names independent from the display language. Recognized legacy default names are translated only in the combo box; custom names remain user data.
- Let workflow step labels be retranslated without resetting pending, active, or completed state.
- Complete the Polish startup text for Sync, PDF, OCR, Convert Files, EML task setup, Settings, and preflight issue summaries, including Polish diacritics.
- Keep file paths, extensions, product names, and user-provided task/group names unchanged during localization.
- Enforce identical catalog keys and format placeholders across English, Korean, and Polish with regression tests.

### Audit status

- **Fixed (P1):** changing the display language could rewrite and save the legacy default synchronization group name.
- **Fixed (P2):** Polish workflow steps, live counts, Convert Files headers, default sync group, and common empty-state warnings fell back to English.
- **Fixed (P2):** Polish preflight blockers and warnings used English headings and primary messages.
- **Fixed (P3):** four Polish static labels omitted required diacritics.
- **Verified:** 122 automated tests pass, and actual Windows rendering at 1400×900 shows correct Korean/Polish glyphs with no clipping in the reviewed main tabs and Polish Settings dialog.
- **Open (P2):** detailed per-file progress, completion, and failure messages in legacy feature workers still use the documented English fallback when a dedicated Polish string is absent. Consolidate those inline strings into the shared catalog in a separate behavior-reviewed pass.

### Follow-up observations

1. Move remaining worker/toast/message-box strings into `MESSAGES` so translation completeness can be measured by key coverage instead of AST heuristics.
2. Add screenshot snapshots for stable empty states at one normal and one high-DPI scale; keep real file operations outside visual tests.
3. Add a translator-facing glossary for recurring terms such as source, output, backup, dry run, and preflight before expanding beyond the current three languages.
