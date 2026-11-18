# FileOps Hub v1.7.2

- Faster two-way folder sync previews: an identical file pair is read once instead of twice within the same analysis. This applies to ordinary files and filenames with numeric versions such as `v1.2`.
- Approval rechecks and copy verification are unchanged. If a file changes or the operation is cancelled, the previous comparison is not reused.
- One-way sync and the separate filename-date mode (`vYYYYMMDD`) are unchanged.
