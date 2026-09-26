# FileOps Hub v1.4.0

## What changed

- **Generalization & Domain Independence**:
  - Replaced hardcoded promotion number regex with dynamic OCR extraction presets (`Invoice Number`, `Date YYYY-MM-DD`, `Digits`, `First Line`, `Custom Regex`, and `.txt` full-text export).
  - Added dynamic renaming template engine (`{date}`, `{match}`, `{original_name}`, `{seq}`).
  - Extended folder synchronization with `exclude_patterns` wildcard filters (`*.tmp`, `~$*`, etc.) and customizable, path-traversal-safe `archive_folder_name`.

- **Pipeline Flexibility & Step Chaining**:
  - Added selectable sync modes: Two-Way Synchronization (`two_way`) and One-Way Master Distribution (`one_way`).
  - Added recursive subfolder synchronization (`include_subfolders`) preserving directory tree hierarchies.
  - Added pipeline step output chaining (`chain_outputs`): Converted images from EML or PDF steps are automatically fed into OCR processing.

- **Advanced Scheduling & Real-time Event Triggers**:
  - Extended schedule evaluator to support periodic interval execution (`interval_minutes`) and day-of-week whitelist filtering (`weekdays`).
  - Implemented real-time `FolderWatcher` with 2-tier write-lock readiness check (`is_file_ready`) and debounce cooldown timer.
  - Added headless CLI execution mode (`python src/main.py --headless-run`) returning standard exit codes (0/1) for Windows Task Scheduler and automation scripts.

- **Workflow Presets & Multi-Channel Notifications**:
  - Added secure workflow preset manager (`preset_manager.py`) exporting and importing sanitized configuration profiles with defense-in-depth redaction of sensitive credentials (`SECURE_KEYS`, passwords, tokens, API keys) and transient state.
  - Added multi-channel notification dispatcher (`notifier.py`) supporting Slack, Microsoft Teams, Discord, and Generic JSON Webhooks alongside traditional SMTP email.

## Validation

- All 182 automated unit and integration tests passed.
- Full Python compilation (`py_compile`), dependency integrity (`pip check`), and Ruff `E9/F/B` static checks passed.
- Strict 3-language AST localization validation (`tools/test_i18n.py`) passed across English, Korean, and Polish.
- Release build packaging covers PyInstaller executable, launcher executable, Inno Setup installer, and SHA-256 checksum manifest.

## Known boundaries

- Microsoft Excel COM is unavailable on headless build environments; local licensed Excel is required for XLSX-to-XLSM conversion.
- Windows release executables are unsigned and may trigger Microsoft Defender SmartScreen warnings on first run.
