# FileOps Hub v1.3.1

## What changed

- Changed the Convert Files in-place option into an explicit source-replacement workflow. For XLSX-to-XLSM conversion, the verified XLSM remains in the source folder and the old XLSX is moved to Windows Recycle Bin.
- Added a disclosed permanent-delete fallback when the Recycle Bin is unavailable. If both recycling and deletion fail, the old source remains and the item is reported as failed.
- Added format-aware Office/ZIP/PDF validation, source-change detection, source/output path checks, target-extension checks, and collision-safe output naming before any source replacement.
- Excluded files already in the selected target format from in-place scans to prevent repeated same-format replacement.
- Made source replacement available only as a reviewed direct action in Convert Files. Run Tasks and daily schedules reject it before execution; separate-output and `Original Backup` workflows remain available.
- Added localized source-action explanations, a replacement preview, a final confirmation that defaults to No, updated per-tab manual content, and clear result messages in English, Korean, and Polish.
- Added latest scheduled-run start time, end time, duration, and result to the Run Tasks schedule status. A run with a start but no end record is shown as unfinished instead of being confused with an older result.

## Validation

- All 158 automated tests passed.
- Python compilation, dependency integrity, Ruff `E9/F/B`, localization parity/leakage, and Git whitespace checks passed.
- Offscreen layout review covered the Korean Convert Files replacement notice and the Run Tasks start/end schedule summary at 1400×850.
- Release build verification covers PyInstaller packaging, launcher and installer version metadata, icons, artifact hashes, and the SHA-256 manifest.

## Known boundaries

- Microsoft Excel COM is unavailable on the build machine, so a real licensed-Excel XLSX-to-XLSM scenario still requires workstation validation. The app preflight blocks Office conversion when the required COM application cannot start.
- Recycle Bin behavior depends on the source volume and Windows shell. The confirmation explicitly discloses the permanent-delete fallback for paths that cannot be recycled.
- The Windows release executables are unsigned and may trigger Microsoft Defender SmartScreen or Smart App Control warnings.
