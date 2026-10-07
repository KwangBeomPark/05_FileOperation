"""Local aliases for an already-published signed set, never a new public release.

The original signed bytes and provenance are preserved; this does NOT rebuild
the embedded executable. The publisher refuses alias_only manifests.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_all as build
from src.app_identity import PRODUCT_ID, installer_filenames, installer_names_for_tag


def prepare(version: str) -> Path:
    folder = ROOT / "release"
    if folder.is_symlink() or folder.resolve().parent != ROOT.resolve():
        raise ValueError("Unsafe release folder.")
    original = folder / "build-manifest.json"
    if original.is_symlink():
        raise ValueError("Unsafe manifest.")
    manifest = json.loads(original.read_text(encoding="utf-8"))
    if (manifest.get("version") != version or manifest.get("authenticode_verified") is not True or
            manifest.get("alias_only")):
        raise ValueError("A matching original signed manifest is required.")
    candidates = [item for item in manifest["artifacts"]
                  if Path(item["path"]).name in installer_names_for_tag(version)]
    if len(candidates) != 1:
        raise ValueError("Exactly one original signed installer must be recorded.")
    item = candidates[0]
    installer = folder / Path(item["path"]).name
    if (installer.is_symlink() or not installer.is_file() or
            installer.stat().st_size != item["size"] or build.sha256(installer) != item["sha256"].upper()):
        raise ValueError("Original signed installer hash/size mismatch.")
    signer = manifest.get("signing_certificate_sha1") or ""
    signtool = build.find_signtool()
    if not signer or not signtool:
        raise ValueError("SignTool and original signer identity are required.")
    build.verify_signtool(signtool)
    build.run([signtool, "verify", "/pa", "/all", "/v", str(installer)])
    build.run(build.authenticode_verification_command(installer, signer))
    local = ROOT / "tools" / "_local"
    local.mkdir(parents=True, exist_ok=True)
    prepared = Path(tempfile.mkdtemp(prefix="legacy-aliases-", dir=local))
    names = installer_filenames(version)
    for name in names:
        shutil.copy2(installer, prepared / name)
        if build.sha256(prepared / name) != item["sha256"].upper():
            raise ValueError("Alias copy hash mismatch.")
        build.run([signtool, "verify", "/pa", "/all", "/v", str(prepared / name)])
        build.run(build.authenticode_verification_command(prepared / name, signer))
    payload = dict(manifest)
    payload.update(
        product_id=manifest["product_id"], alias_product_id=PRODUCT_ID,
        binary_product_id=manifest["product_id"], alias_only=True,
        source_manifest_sha256=build.sha256(original),
        note="Local filename aliases only. Embedded binary is unchanged. Never publish as a new build.",
        artifacts=[{"path": f"release/{name}", "size": item["size"], "sha256": item["sha256"]}
                   for name in names],
    )
    (prepared / "build-manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    all_names = [*names, "build-manifest.json"]
    (prepared / "SHA256SUMS.txt").write_text(
        "".join(f"{build.sha256(prepared / name)}  {name}\n" for name in all_names), encoding="utf-8")
    backup = Path(tempfile.mkdtemp(prefix=f"published-v{version}-", dir=local))
    backup.rmdir()  # Our empty temporary directory only.
    folder.rename(backup)
    try:
        prepared.rename(folder)
    except OSError:
        backup.rename(folder)
        raise
    print(f"Local dual aliases prepared. Original published set preserved: {backup}")
    print("Embedded product ID is unchanged. New normalized source must be rebuilt/signed before publication.")
    return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--confirm-alias-only", action="store_true", required=True)
    args = parser.parse_args()
    prepare(args.version)
