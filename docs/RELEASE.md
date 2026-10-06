# Release Procedure

1. Update `APP_VERSION` in `src/version.py` and record user-visible changes.
2. Close `App005_FileOps.exe` and legacy `App05_FileOps.exe` / `IntegratedDataTool.exe`, then run `python scripts/build_all.py --require-signature`. Add `--build-launcher` for the optional launcher.
3. Configure `FILEOPS_SIGN_CERT_SHA1` and make `signtool` available on `PATH` before requiring a signature. `FILEOPS_SIGNTOOL_PATH` and `FILEOPS_TIMESTAMP_URL` can override those defaults.
4. Test `release/App005_FileOps_Setup_vX.Y.Z.exe` in Windows Sandbox or a clean PC: clean install, upgrade, shortcuts, tray auto-start, removal, first launch, OCR fallback, EML Chromium setup, and required Office conversion. Confirm the default program folder is `%LOCALAPPDATA%/Programs/FileOps` and settings/logs/history use its `UserSetting` subfolder without importing old data. A custom install must use its own UserSetting. Scheduling must initially be disabled; removal must preserve UserSetting.
5. Upload only the current version's signed installer, optional `App005_FileOps_Launcher_vX.Y.Z.exe`, `SHA256SUMS.txt`, and `build-manifest.json`. Do not upload historical/development artifacts with a wildcard. Publish the matching tag after checks pass.

`scripts/sign_and_release.ps1` wraps the same Python build/signing pipeline. It does not elevate, change Windows services, use another project's tools, push, tag, or publish. Version and identity come from `src/version.py` and `src/app_identity.py`.
The wrapper accepts `-CertificateThumbprint` and `-SignToolPath`. When not supplied,
it selects the only unexpired, non-self-issued code-signing certificate with a private
key and uses a verified Microsoft SignTool under `tools/_local/signing-tools` when
available. Ambiguous certificates require explicit selection. Environment overrides
are restored when the wrapper finishes; no certificate credential is stored.
For SimplySign key-access failures, the user must run this wrapper directly in their
own logged-in signing session; automatically creating an elevated child is not a fix.

`--require-signature` intentionally fails without a valid code-signing certificate. Do not replace it with an unsigned public release.

## Smart App Control

Windows Smart App Control blocks unknown unsigned executables by design. A development build can therefore be blocked even when it was compiled locally. Do not disable Smart App Control as a release test workaround.

Use a public CA-issued Authenticode certificate for `App005_FileOps.exe`, `App005_FileOps_Setup_vX.Y.Z.exe`, and the optional `App005_FileOps_Launcher_vX.Y.Z.exe`. A self-signed or internal-only certificate does not establish public trust on a separate PC. Signing alone does not guarantee the absence of SmartScreen or organization-policy warnings. Before uploading, verify each file with:

```powershell
Get-AuthenticodeSignature .\path\to\artifact.exe
```

The status must be `Valid`, with a signer certificate that has a private key at signing time and a trusted public chain on the target PC.

The canonical builder additionally requires `signtool verify /pa /all /v`,
Windows Authenticode `Valid`, a timestamp certificate, and the configured signer
thumbprint for every app, installer, and optional launcher. Signing/verification
failure stops the pipeline before checksums or a successful build manifest are emitted.
Automated tests receive temporary user-data and offscreen-Qt settings only in
their own subprocess. The signing process retains the user's real environment
so the SimplySign session is not redirected to temporary data.
