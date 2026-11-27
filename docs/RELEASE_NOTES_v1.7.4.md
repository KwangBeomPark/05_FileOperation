# FileOps Hub v1.7.4

- **Folder Sync:** Review changes in the tab and select the green Synchronize button once. The separate confirmation popup and checkbox are no longer part of this manual workflow.
- The preview shows new copies, updates, archives, conflict backups, and held items. All groups are checked again before writes; if the displayed plan or observed files changed, refresh the preview to continue.
- Office owner files starting with `~$` are always skipped in folder sync, even with custom exclusion patterns. Opening or closing a workbook does not invalidate the preview merely because its owner file appeared or disappeared.
- Numeric filename versions such as `v1_5_3` and `v1.5.3` are compared the same way in ordinary sync and manual old-version cleanup, without renaming files. The date-only sync mode still requires `vYYYYMMDD`.
- Existing per-file checks, archive-only sync, and the separate manual old-version cleanup workflow are unchanged.
- **Run Tasks:** Short table columns use only the width they need, and the rightmost folder/rule summary uses the remaining space.
- **Custom task order:** Use Move up and Move down to set the order for checked tasks in manual and in-app scheduled runs. Custom runs skip later tasks after failure or partial failure. New manual sync writes require a focused review; approved unchanged actions and scheduled runs do not show an extra confirmation.
- Zero-padded numeric names are compared component by component: `v2_02` is newer than `v2_01`.
