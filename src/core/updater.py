from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import re
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.version import APP_VERSION_TAG

logger = get_logger()

TRUSTED_DOWNLOAD_HOSTS = frozenset({
    "github.com",
    "api.github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "release-assets.githubusercontent.com",
})
SHA256_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$", re.IGNORECASE)
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class ReleaseAsset:
    """A release installer that passed metadata validation before download."""

    name: str
    url: str
    sha256: str


class RedirectWithoutAuth(urllib.request.HTTPRedirectHandler):
    """Reject untrusted redirects and drop GitHub authorization across hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_trusted_download_url(newurl):
            raise ValueError(f"Untrusted download redirect: {newurl}")
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req and req.host != new_req.host and "Authorization" in new_req.headers:
            new_req.remove_header("Authorization")
        return new_req


def is_trusted_download_url(url: str) -> bool:
    """Allow only HTTPS GitHub release hosts, including its final asset redirect host."""
    parsed = urlparse(url)
    try:
        has_port = parsed.port is not None
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or has_port:
        return False
    host = (parsed.hostname or "").lower()
    return host in TRUSTED_DOWNLOAD_HOSTS


def installer_name_for_tag(tag_name: str) -> str | None:
    """Return the only installer filename accepted for an application version."""
    raw_tag = tag_name.strip()
    version = raw_tag[1:] if raw_tag[:1].lower() == "v" else raw_tag
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        return None
    return f"IntegratedDataTool_Setup_v{version}.exe"


class AutoUpdater:
    def __init__(self, current_version=APP_VERSION_TAG, repo_owner="KwangBeomPark", repo_name="05_FileOperation"):
        self.current_version = current_version
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.last_error = ""
        self.latest_asset: ReleaseAsset | None = None
        self.config_manager = ConfigManager()
        configured_repo = self.config_manager.get("github_repo", "").strip()
        if "/" in configured_repo:
            owner, name = configured_repo.split("/", 1)
            if owner.strip() and name.strip():
                self.repo_owner = owner.strip()
                self.repo_name = name.strip()

    def check_for_updates(self):
        """Return update metadata without ever falling back to an arbitrary release asset."""
        self.last_error = ""
        self.latest_asset = None
        url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/releases/latest"
        token = self.config_manager.get("github_token", "").strip()
        headers = {"User-Agent": "IntegratedDataTool-AutoUpdater"}
        if token:
            headers["Authorization"] = f"token {token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=5) as response:
                data = json.loads(response.read().decode())
                latest_tag = str(data.get("tag_name", "v0.0.0"))

                if self.is_newer_version(self.current_version, latest_tag):
                    self.latest_asset = self._select_verified_installer(latest_tag, data.get("assets", []))
                    body = data.get("body", "No release notes available.")
                    return True, latest_tag, self.latest_asset.url if self.latest_asset else None, body
                return False, latest_tag, None, ""
        except Exception as exc:
            self.last_error = str(exc)
            logger.error("Failed to check updates from GitHub: %s", exc)
            return False, self.current_version, None, ""

    def _select_verified_installer(self, latest_tag: str, assets: list[dict]) -> ReleaseAsset | None:
        expected_name = installer_name_for_tag(latest_tag)
        if not expected_name:
            logger.warning("Ignoring update with unsupported release tag: %s", latest_tag)
            return None

        matches = [asset for asset in assets if asset.get("name") == expected_name]
        if len(matches) != 1:
            logger.warning("Release %s does not contain the expected installer: %s", latest_tag, expected_name)
            return None
        selected = matches[0]

        url = str(selected.get("browser_download_url") or "")
        digest_match = SHA256_PATTERN.fullmatch(str(selected.get("digest") or ""))
        if not is_trusted_download_url(url) or not digest_match:
            logger.warning("Release %s installer metadata failed validation.", latest_tag)
            return None
        return ReleaseAsset(expected_name, url, digest_match.group(1).lower())

    def download_file(self, url, dest_path, expected_sha256, progress_callback=None):
        """Download a verified installer to a temporary file, then atomically publish it."""
        if not is_trusted_download_url(url):
            raise ValueError(f"신뢰할 수 없는 다운로드 주소입니다: {url}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256), re.IGNORECASE):
            raise ValueError("업데이트 파일 SHA-256 digest 형식이 올바르지 않습니다.")

        token = self.config_manager.get("github_token", "").strip()
        headers = {"User-Agent": "IntegratedDataTool-AutoUpdater"}
        if token:
            headers["Authorization"] = f"token {token}"

        destination = Path(dest_path)
        partial = destination.with_suffix(destination.suffix + ".download")
        destination.parent.mkdir(parents=True, exist_ok=True)
        opener = urllib.request.build_opener(
            RedirectWithoutAuth(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        req = urllib.request.Request(url, headers=headers)

        try:
            with opener.open(req, timeout=15) as response:
                if not is_trusted_download_url(response.geturl()):
                    raise ValueError(f"신뢰할 수 없는 최종 다운로드 주소입니다: {response.geturl()}")
                total_size = int(response.info().get("Content-Length", 0))
                if total_size > MAX_INSTALLER_BYTES:
                    raise IOError(f"업데이트 파일이 허용 크기를 초과했습니다: {total_size} bytes")
                downloaded = 0
                digest = hashlib.sha256()
                with partial.open("wb") as file:
                    while True:
                        chunk = response.read(16 * 1024)
                        if not chunk:
                            break
                        file.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if downloaded > MAX_INSTALLER_BYTES:
                            raise IOError(f"업데이트 파일이 허용 크기를 초과했습니다: {downloaded} bytes")
                        if progress_callback:
                            progress_callback(downloaded, total_size)

                if total_size > 0 and downloaded != total_size:
                    raise IOError(f"불완전한 다운로드 감지: {downloaded}/{total_size} bytes 수신됨.")
                if digest.hexdigest().lower() != str(expected_sha256).lower():
                    raise IOError("업데이트 파일 SHA-256 검증에 실패했습니다.")
                os.replace(partial, destination)
            return True
        except Exception as exc:
            logger.error("Failed to download file from %s to %s: %s", url, dest_path, exc)
            partial.unlink(missing_ok=True)
            raise

    def is_newer_version(self, current, latest):
        """Compare numeric release tags such as v1.2.3 without accepting arbitrary text."""
        def parse_version(value):
            raw_value = str(value).strip()
            clean = raw_value[1:] if raw_value[:1].lower() == "v" else raw_value
            if clean.isdigit():
                return (int(clean),)
            try:
                return tuple(int(part) for part in clean.split("."))
            except ValueError:
                return (0,)

        return parse_version(latest) > parse_version(current)
