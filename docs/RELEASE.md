# Release Procedure

1. Update `APP_VERSION` in `src/version.py` and record user-visible changes.
2. Close `IntegratedDataTool.exe`, then run `python tools/build_all.py --require-signature`.
3. Configure `FILEOPS_SIGN_CERT_SHA1` and make `signtool` available on `PATH` before requiring a signature. `FILEOPS_SIGNTOOL_PATH` and `FILEOPS_TIMESTAMP_URL` can override those defaults.
4. Test `dist/IntegratedDataTool_Setup_vX.Y.Z.exe` in Windows Sandbox or a clean PC: install, first launch, OCR fallback, EML Chromium setup, and any required Office conversion.
5. The build creates the signed `App05_FileOps_vX.Y.Z.exe` launcher at the repository root. Upload it with the signed setup EXE and its `.sha256` manifest to the GitHub Release. Publish the matching `vX.Y.Z` tag only after the artifact checks pass.

`--require-signature` intentionally fails without a valid code-signing certificate. Do not replace it with an unsigned public release.

## Smart App Control

Windows Smart App Control blocks unknown unsigned executables by design. A development build can therefore be blocked even when it was compiled locally. Do not disable Smart App Control as a release test workaround.

Use a public CA-issued Authenticode certificate for every executable distributed with a release: `IntegratedDataTool.exe`, `IntegratedDataTool_Setup_vX.Y.Z.exe`, and `App05_FileOps_vX.Y.Z.exe`. A self-signed or internal-only certificate does not establish public trust on a separate PC. Before uploading, verify each file with:

```powershell
Get-AuthenticodeSignature .\path\to\artifact.exe
```

The status must be `Valid`, with a signer certificate that has a private key at signing time and a trusted public chain on the target PC.
