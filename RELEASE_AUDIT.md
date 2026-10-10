# Release audit — App05 FileOps Hub

Audit date: 2026-10-10. Baseline HEAD: `41a33bf1ad049819da3c112915307aee593185c4`.
Independent Codex review of the Gemini handoff; release code did not require changes in this pass.

## Contract

Exactly three directly uploaded assets:
- `App05_FileOps_Setup_v<version>.exe`
- `build-manifest.json`
- `SHA256SUMS.txt`

The product identifier is `App05_FileOps`; the repository directory name is not the installer product name. The previous audit's `App05_FileOperation_Setup` name was incorrect.

`scripts/publish_release.py::validate_release` delegates to the existing release-directory validation. `validate_remote_assets` checks exact asset count, tag, draft/prerelease state, unique expected names, uploaded state, sizes and SHA-256 digests. Publication creates a draft, verifies it, publishes it, verifies the public assets and confirms latest release identity. Internal application entries in the build manifest do not add uploaded assets.

## Verification

`python -m unittest tools.test_release_pipeline tools.test_release_layout -q` — **35 tests passed**. Tests use isolated fixtures/mocked signatures and external commands; any installer compilation is fixture-only. No user settings, production installation, certificate/private key or GitHub state was modified.

The official `release/` ACL was not changed. Source tests do not substitute for read access to actual official bytes or their signature verification in the user's signing session.

## Remaining gates

Published v1.4.3 and its files/tags must remain intact. This pass changed only this audit document and does not require replacing that release. For any future binary change, use a new approved version, a clean reviewed commit, interactive KSP signing and remote-byte verification. Installation/upgrade acceptance on an isolated Windows machine remains a separate gate.
