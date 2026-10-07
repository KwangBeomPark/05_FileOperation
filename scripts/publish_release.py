"""Explicit signed-only publication; existing public versions are never overwritten."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_all as build
from src.core.release_config import DEFAULT_GITHUB_OWNER, DEFAULT_GITHUB_REPOSITORY

REPO = f"{DEFAULT_GITHUB_OWNER}/{DEFAULT_GITHUB_REPOSITORY}"


def command(args: list[str]) -> str:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {args[0]}")
    return result.stdout.strip()


def validate_release(folder: Path, version: str, commit: str) -> tuple[dict, list[Path]]:
    """Reject stale/unsigned/dirty manifests, unexpected files, and incomplete hashes."""
    return build.validate_release_payload(folder, version, commit=commit, require_clean=True)


def validate_remote_assets(payload: dict, paths: list[Path], tag: str, *, draft: bool) -> None:
    if payload.get("tagName") != tag or payload.get("isDraft") is not draft or payload.get("isPrerelease"):
        raise ValueError("Unexpected GitHub release state.")
    assets = payload.get("assets", [])
    if len(assets) != len(paths):
        raise ValueError("Unexpected GitHub asset count.")
    for path in paths:
        matches = [asset for asset in assets if asset["name"] == path.name]
        if len(matches) != 1:
            raise ValueError(f"Missing/duplicate uploaded file: {path.name}")
        asset = matches[0]
        if (asset.get("state") != "uploaded" or asset.get("size") != path.stat().st_size or
                asset.get("digest") != "sha256:" + build.sha256(path).lower()):
            raise ValueError(f"GitHub upload digest mismatch: {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    commit = command(["git", "rev-parse", "HEAD"])
    if command(["git", "status", "--porcelain"]):
        raise ValueError("Commit intended changes before signing/publishing.")
    version = build.read_app_version()
    manifest, paths = validate_release(ROOT / "release", version, commit)
    build.verify_signed_payload(manifest, paths)
    if args.verify_only:
        print("Signed release verified; nothing published.")
        return 0
    selected_signer = os.environ.get("FILEOPS_SIGN_CERT_SHA1", "").replace(" ", "")
    if not selected_signer or selected_signer.upper() != manifest["signing_certificate_sha1"].upper():
        raise ValueError("Publishing requires an explicitly selected public signer matching the manifest.")
    tag = f"v{version}"
    releases = json.loads(command(["gh", "api", "--paginate", "--slurp", f"repos/{REPO}/releases?per_page=100"]))
    if any(release.get("tag_name") == tag for page in releases for release in page):
        raise ValueError(f"Release {tag} exists. Use a new version; no clobber is allowed.")
    if command(["git", "branch", "--show-current"]) != "main":
        raise ValueError("Publishing requires the approved main branch.")
    remote = command(["git", "remote", "get-url", "origin"])
    if remote not in (f"https://github.com/{REPO}.git", f"git@github.com:{REPO}.git"):
        raise ValueError("Unexpected origin repository.")
    if command(["git", "tag", "--list", tag]):
        if command(["git", "rev-parse", f"{tag}^{{commit}}"] ) != commit:
            raise ValueError("Existing tag points at a different commit; it will not be replaced.")
    else:
        command(["git", "tag", "-a", tag, "-m", f"FileOps Hub {tag} signed release"])
    command(["git", "push", "--atomic", "origin", "HEAD:refs/heads/main", f"refs/tags/{tag}"])
    notes = ROOT / "docs" / f"RELEASE_NOTES_{tag}.md"
    note_args = ["--notes-file", str(notes)] if notes.is_file() else ["--notes", "Signed FileOps Hub release. See README for UserSetting and upgrade guidance."]
    command(["gh", "release", "create", tag, "--repo", REPO, "--verify-tag", "--draft", "--title", f"FileOps Hub {tag}", *note_args, *(str(path) for path in paths)])
    query = ["gh", "release", "view", tag, "--repo", REPO, "--json", "tagName,isDraft,isPrerelease,assets,url"]
    validate_remote_assets(json.loads(command(query)), paths, tag, draft=True)
    command(["gh", "release", "edit", tag, "--repo", REPO, "--draft=false", "--latest"])
    validate_remote_assets(json.loads(command(query)), paths, tag, draft=False)
    latest = json.loads(command(["gh", "api", f"repos/{REPO}/releases/latest"]))
    if latest.get("tag_name") != tag or latest.get("draft") or latest.get("prerelease"):
        raise ValueError("Latest release state could not be confirmed.")
    print(f"Published and verified: https://github.com/{REPO}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc
