# Collect sync validation — 2026-10-27

All development is on `feature/collect-sync` in the dedicated collect worktree.
The main checkout and its local AI_CODE_MAP.md are read-only.
No version bump, merge to main, signing, push, tag or publication is authorized.

## Stages

1. Engine: progress, cooperative cancellation with saved mapping, read-only temp cleanup,
   group-level I/O errors and defensive state parsing. 20 engine tests passed.
2. Typed settings and atomic ConfigManager roundtrip/failure injection.
3. Independent group editor and QThread execution; daily scheduler and lifecycle integration.
4. Three languages, manual, full accumulated regressions and offscreen visual review.

Raw command outputs are retained under `tools/_local/collect-sync/` during validation.

## Safety checkpoint

The red tests reproduced six failure paths before fixes; subsequent coverage includes interrupted commit,
unrelated target creation after scan, failed-copy ownership, actual Windows junction and modal editor/reentrancy tests.
Full accumulated output (phase1-full.log):

```text
----------------------------------------------------------------------
Ran 358 tests in 7.921s

OK (skipped=1)
```

The native-installer fixture remains skipped. No installed EXE/Office/prolonged-share-outage claim is made.
Pending new-copy journal entries are intentionally fail-closed after an uncertain interruption.
Do not delete the state to force retries: the full report and diagnostic log must be reviewed for recovery.
Target path aliases (drive vs UNC), archive retention and manually added identical files retain the stated limitations.
AI_CODE_MAP follow-up entries are listed in COLLECT_SYNC_LINT_PLAN.md; the main file was not edited.

## Import and expression checkpoints

Commits: d14f95d (feature), 234d3f7 (imports), 9e8d142 (equivalent expressions).
Full raw log: `tools/_local/collect-sync/phase3-full.log`.

```text
----------------------------------------------------------------------
Ran 363 tests in 7.948s

OK (skipped=1)
```

Full Ruff JSON: `tools/_local/collect-sync/phase3-ruff.json`.
Baseline comparison output:

```text
Baseline Ruff diagnostics: 324
Current Ruff diagnostics: 198
New diagnostics: 0
PASS: no added diagnostics
```

`git diff --check` passed at each checkpoint. Full Ruff itself still exits 1.
The current ko/en/pl real-widget previews were rendered with synthetic paths/results and inspected;
no real user file conversion or settings modification is performed by the preview tool.
The 18:12 Europe/Warsaw Opus cross-review is a one-time app heartbeat, not a completed review.
Exception cleanup is pending module-level review, including an explicit user decision about
the legacy Windows encryption-to-Base64 fallback. No cryptographic policy change has been made.

## Opus follow-up checkpoint

Latest raw output is `tools/_local/collect-sync/review-fixes-full-final.log`:

```text
----------------------------------------------------------------------
Ran 396 tests in 8.860s

OK (skipped=1)
```

Ruff final JSON: `review-fixes-ruff-final.json`, 198 baseline diagnostics remain, zero introduced.
Opus raw review: `opus-recovery-review-20261027.jsonl` (actual claude-opus-5-5, exit 0/completed).
Review findings are independently adjudicated in COLLECT_SYNC_REVIEW_FOLLOWUP.md; the timer-refusal claim
was an incomplete-context false positive, while persisted native-start rollback was corrected and tested.
SMTP/DPAPI policy changes are excluded by the user. No installed app, live Office, prolonged SMB outage or publication was run.
