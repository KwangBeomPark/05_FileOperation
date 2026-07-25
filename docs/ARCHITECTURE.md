# FileOps Hub Architecture

## Runtime Boundaries

```text
PyQt tabs -> typed RunConfig -> RunPlan -> preflight -> TaskRunner -> core converters
                    |                         |
                    +-> validation errors      +-> RunReport -> UI worker signals
```

- Each tab converts only its visible state into a typed `build_run_config()` result.
- `TaskTab` combines active configs into a `RunPlan`, then runs common dependency checks before work starts.
- `TaskRunner` is PyQt-free and owns sequential execution, cancellation state, and reporting.
- `TaskWorker` is the only Qt adapter for the integrated runner.
- Direct tab actions reuse the same preflight contract where external dependencies can cause destructive work, notably Office conversion.

## External Dependencies

- OCR uses Tesseract first and Windows OCR as a fallback.
- EML rendering requires the Playwright driver and Chromium runtime.
- Office conversion requires the specific Excel, Word, or PowerPoint COM application for the selected source files.
- SMTP is optional; report delivery falls back to a local report file.

## Distribution Boundaries

- `src/version.py` is the single release-version source.
- `tools/build_all.py` creates the PyInstaller version resource, calls Inno Setup with the same version, runs tests, and writes an installer checksum manifest.
- The in-app updater and `App05_FileOps` accept only the exact versioned setup filename from GitHub Releases, verify trusted redirect hosts, and verify the published SHA-256 digest before execution.
- Authenticode signing is a release requirement for public distribution; see `docs/RELEASE.md`.
