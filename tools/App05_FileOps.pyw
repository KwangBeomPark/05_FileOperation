from __future__ import annotations

import json
import hashlib
import ctypes
import locale
import os
import re
import ssl
import subprocess
import tempfile
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import tkinter as tk
from tkinter import messagebox, ttk

try:
    import winreg
except ImportError:
    winreg = None


APP_TITLE = "FileOps Hub"
APP_EXE = "IntegratedDataTool.exe"
INSTALL_DIR = "IntegratedDataTool"
REPO_OWNER = "KwangBeomPark"
REPO_NAME = "FileOps-Hub"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
TRUSTED_HOSTS = {
    "github.com",
    "api.github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
INSTALLER_NAME_PATTERN = re.compile(r"^IntegratedDataTool_Setup_v(\d+(?:\.\d+)*)\.exe$", re.IGNORECASE)
SHA256_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$", re.IGNORECASE)
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024

TRANSLATIONS = {
    "ko": {
        "invalid_release_tag": "최신 릴리스 태그 형식이 올바르지 않습니다: {tag_name}",
        "installer_missing": "GitHub 최신 릴리스에서 정식 설치 파일을 찾지 못했습니다: {expected_name}",
        "installer_name_invalid": "설치 파일 이름 검증에 실패했습니다.",
        "untrusted_redirect": "신뢰할 수 없는 다운로드 리다이렉트입니다.\n{url}",
        "untrusted_url": "신뢰할 수 없는 다운로드 주소입니다.\n{url}",
        "missing_digest": "GitHub 릴리스에 SHA-256 digest가 없습니다. 자동 설치를 중단합니다.",
        "download_title": "{app_title} 설치 파일 다운로드",
        "download_initial": "최신 설치 파일을 다운로드하는 중입니다.",
        "download_progress": "최신 설치 파일을 다운로드하는 중입니다. {percent}%",
        "invalid_digest": "설치 파일 SHA-256 digest 형식이 올바르지 않습니다.",
        "untrusted_final_url": "신뢰할 수 없는 최종 다운로드 주소입니다.\n{url}",
        "installer_too_large": "설치 파일이 허용 크기를 초과했습니다: {size} bytes",
        "download_incomplete": "다운로드가 완전하지 않습니다. {downloaded}/{total_size} bytes",
        "digest_failed": "다운로드 파일의 SHA-256 검증에 실패했습니다.",
        "download_failed": "설치 파일을 자동으로 다운로드하지 못했습니다.\n\n상세: {detail}\n\nGitHub 릴리스 페이지를 열까요?",
        "not_installed": "FileOps 프로그램이 설치되어 있지 않습니다.\n\nGitHub에서 최신 설치 파일을 다운로드하고 설치할까요?",
    },
    "en": {
        "invalid_release_tag": "The latest release tag is invalid: {tag_name}",
        "installer_missing": "The official installer was not found in the latest GitHub release: {expected_name}",
        "installer_name_invalid": "Installer filename validation failed.",
        "untrusted_redirect": "An untrusted download redirect was blocked.\n{url}",
        "untrusted_url": "An untrusted download URL was blocked.\n{url}",
        "missing_digest": "The GitHub release does not include a SHA-256 digest. Automatic installation was stopped.",
        "download_title": "Download {app_title} installer",
        "download_initial": "Downloading the latest installer.",
        "download_progress": "Downloading the latest installer. {percent}%",
        "invalid_digest": "The installer SHA-256 digest format is invalid.",
        "untrusted_final_url": "An untrusted final download URL was blocked.\n{url}",
        "installer_too_large": "The installer exceeds the allowed size: {size} bytes",
        "download_incomplete": "The download is incomplete. {downloaded}/{total_size} bytes",
        "digest_failed": "SHA-256 verification of the downloaded installer failed.",
        "download_failed": "The installer could not be downloaded automatically.\n\nDetails: {detail}\n\nOpen the GitHub Releases page?",
        "not_installed": "FileOps Hub is not installed.\n\nDownload and install the latest version from GitHub?",
    },
    "pl": {
        "invalid_release_tag": "Format najnowszego tagu wydania jest nieprawidłowy: {tag_name}",
        "installer_missing": "Nie znaleziono oficjalnego instalatora w najnowszym wydaniu GitHub: {expected_name}",
        "installer_name_invalid": "Weryfikacja nazwy pliku instalatora nie powiodła się.",
        "untrusted_redirect": "Zablokowano niezaufane przekierowanie pobierania.\n{url}",
        "untrusted_url": "Zablokowano niezaufany adres pobierania.\n{url}",
        "missing_digest": "Wydanie GitHub nie zawiera sumy SHA-256. Automatyczna instalacja została zatrzymana.",
        "download_title": "Pobieranie instalatora {app_title}",
        "download_initial": "Pobieranie najnowszego instalatora.",
        "download_progress": "Pobieranie najnowszego instalatora. {percent}%",
        "invalid_digest": "Format sumy SHA-256 instalatora jest nieprawidłowy.",
        "untrusted_final_url": "Zablokowano niezaufany końcowy adres pobierania.\n{url}",
        "installer_too_large": "Instalator przekracza dozwolony rozmiar: {size} bytes",
        "download_incomplete": "Pobieranie jest niekompletne. {downloaded}/{total_size} bytes",
        "digest_failed": "Weryfikacja SHA-256 pobranego instalatora nie powiodła się.",
        "download_failed": "Nie można było automatycznie pobrać instalatora.\n\nSzczegóły: {detail}\n\nOtworzyć stronę wydań GitHub?",
        "not_installed": "FileOps Hub nie jest zainstalowany.\n\nPobrać i zainstalować najnowszą wersję z GitHub?",
    },
}


def normalize_language(value: str | None) -> str | None:
    """Map Windows and locale language tags to the launcher translation keys."""
    if not value:
        return None
    normalized = value.replace("_", "-").lower()
    for language in TRANSLATIONS:
        if normalized == language or normalized.startswith(f"{language}-"):
            return language
    return None


def detect_language(
    override: str | None = None,
    ui_language_id: int | None = None,
    locale_name: str | None = None,
) -> str:
    """Prefer an explicit override, then Windows UI language, then English."""
    selected = normalize_language(override or os.environ.get("APP05_LANGUAGE"))
    if selected:
        return selected

    if ui_language_id is None and os.name == "nt":
        try:
            ui_language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        except Exception:
            ui_language_id = None

    primary_language = (ui_language_id or 0) & 0x03FF
    windows_languages = {0x12: "ko", 0x09: "en", 0x15: "pl"}
    if primary_language in windows_languages:
        return windows_languages[primary_language]

    if locale_name is None:
        try:
            locale_name = locale.getlocale()[0]
        except Exception:
            locale_name = None
    return normalize_language(locale_name) or "en"


LAUNCHER_LANGUAGE = detect_language()


def translate(key: str, **values: object) -> str:
    """Return a localized message, using English as the complete fallback catalog."""
    template = TRANSLATIONS.get(LAUNCHER_LANGUAGE, TRANSLATIONS["en"]).get(key, TRANSLATIONS["en"][key])
    return template.format(**values)


class LauncherError(Exception):
    pass


@dataclass(frozen=True)
class ReleaseAsset:
    tag_name: str
    name: str
    url: str
    sha256: str


class RedirectWithoutAuth(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_url(newurl):
            raise LauncherError(translate("untrusted_redirect", url=newurl))
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req and req.host != new_req.host and "Authorization" in new_req.headers:
            new_req.remove_header("Authorization")
        return new_req


def trusted_url(url: str) -> bool:
    parsed = urlparse(url)
    try:
        has_port = parsed.port is not None
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or has_port:
        return False
    host = (parsed.hostname or "").lower()
    return host in TRUSTED_HOSTS


def registry_candidates() -> list[Path]:
    if winreg is None:
        return []

    candidates: list[Path] = []
    roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
    views = [0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY]
    uninstall_base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

    for root in roots:
        for view in views:
            try:
                with winreg.OpenKey(root, uninstall_base, 0, winreg.KEY_READ | view) as base_key:
                    index = 0
                    while True:
                        try:
                            subkey = winreg.EnumKey(base_key, index)
                            index += 1
                        except OSError:
                            break

                        try:
                            with winreg.OpenKey(base_key, subkey, 0, winreg.KEY_READ | view) as app_key:
                                values = read_registry_values(app_key)
                        except OSError:
                            continue

                        display_name = values.get("DisplayName", "").strip()
                        if display_name not in {"IntegratedDataTool", "FileOps Hub", "FileOps-Hub"}:
                            if subkey not in {"IntegratedDataTool_is1", "FileOps Hub_is1", "FileOps-Hub_is1"}:
                                continue

                        install_path = values.get("InstallLocation") or values.get("Inno Setup: App Path")
                        if install_path:
                            candidates.append(Path(install_path) / APP_EXE)

                        icon_path = values.get("DisplayIcon", "").strip().strip('"')
                        if icon_path:
                            if icon_path.lower().endswith(",0"):
                                icon_path = icon_path[:-2]
                            candidates.append(Path(icon_path))
            except OSError:
                continue
    return candidates


def read_registry_values(key) -> dict[str, str]:
    values: dict[str, str] = {}
    index = 0
    while True:
        try:
            name, value, _ = winreg.EnumValue(key, index)
            index += 1
        except OSError:
            break
        if isinstance(value, str):
            values[name] = value
    return values


def default_candidates() -> list[Path]:
    candidates: list[Path] = []
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / INSTALL_DIR / APP_EXE)
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(env_name):
            candidates.append(Path(os.environ[env_name]) / INSTALL_DIR / APP_EXE)
            candidates.append(Path(os.environ[env_name]) / APP_TITLE / APP_EXE)
    return candidates


def find_installed_exe() -> Path | None:
    seen: set[str] = set()
    for candidate in registry_candidates() + default_candidates():
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file() and candidate.name.lower() == APP_EXE.lower():
            return candidate
    return None


def request_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "App05-FileOps-Installer",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def expected_installer_name(tag_name: str) -> str:
    raw_tag = tag_name.strip()
    version = raw_tag[1:] if raw_tag[:1].lower() == "v" else raw_tag
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        raise LauncherError(translate("invalid_release_tag", tag_name=tag_name))
    return f"IntegratedDataTool_Setup_v{version}.exe"


def latest_setup_asset() -> ReleaseAsset:
    req = urllib.request.Request(LATEST_RELEASE_API, headers=request_headers())
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=20) as response:
        release = json.loads(response.read().decode("utf-8"))

    tag_name = str(release.get("tag_name") or "")
    expected_name = expected_installer_name(tag_name)
    assets = release.get("assets") or []
    matches = [asset for asset in assets if asset.get("name") == expected_name]
    if len(matches) != 1:
        raise LauncherError(translate("installer_missing", expected_name=expected_name))
    selected = matches[0]

    name = str(selected.get("name") or "")
    url = str(selected.get("browser_download_url") or "")
    digest_match = SHA256_PATTERN.fullmatch(str(selected.get("digest") or ""))
    if not INSTALLER_NAME_PATTERN.fullmatch(name) or Path(name).name != name:
        raise LauncherError(translate("installer_name_invalid"))
    if not trusted_url(url):
        raise LauncherError(translate("untrusted_url", url=url))
    if not digest_match:
        raise LauncherError(translate("missing_digest"))
    return ReleaseAsset(tag_name, name, url, digest_match.group(1).lower())


class ProgressWindow:
    def __init__(self, root: tk.Tk):
        self.window = tk.Toplevel(root)
        self.window.title(translate("download_title", app_title=APP_TITLE))
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        self.label = ttk.Label(self.window, text=translate("download_initial"))
        self.label.grid(row=0, column=0, padx=18, pady=(16, 8), sticky="w")
        self.progress = ttk.Progressbar(self.window, length=360, mode="indeterminate")
        self.progress.grid(row=1, column=0, padx=18, pady=(0, 16), sticky="ew")
        self.progress.start(12)
        self.window.update_idletasks()
        self.center()

    def center(self) -> None:
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = int((self.window.winfo_screenwidth() - width) / 2)
        y = int((self.window.winfo_screenheight() - height) / 2)
        self.window.geometry(f"+{x}+{y}")

    def update(self, downloaded: int, total_size: int) -> None:
        if total_size > 0 and self.progress["mode"] != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=total_size)
        if total_size > 0:
            self.progress["value"] = downloaded
            percent = min(100, int(downloaded * 100 / total_size))
            self.label.configure(text=translate("download_progress", percent=percent))
        self.window.update_idletasks()

    def close(self) -> None:
        self.progress.stop()
        self.window.destroy()


def download_file(url: str, destination: Path, progress: ProgressWindow, expected_sha256: str) -> None:
    if not trusted_url(url):
        raise LauncherError(translate("untrusted_url", url=url))
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256, re.IGNORECASE):
        raise LauncherError(translate("invalid_digest"))

    partial = destination.with_suffix(destination.suffix + ".download")
    destination.parent.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(
        RedirectWithoutAuth(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    req = urllib.request.Request(url, headers=request_headers())

    try:
        with opener.open(req, timeout=30) as response:
            if not trusted_url(response.geturl()):
                raise LauncherError(translate("untrusted_final_url", url=response.geturl()))

            total_size = int(response.info().get("Content-Length", 0))
            if total_size > MAX_INSTALLER_BYTES:
                raise LauncherError(translate("installer_too_large", size=total_size))
            downloaded = 0
            digest = hashlib.sha256()
            with partial.open("wb") as file:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    file.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if downloaded > MAX_INSTALLER_BYTES:
                        raise LauncherError(translate("installer_too_large", size=downloaded))
                    progress.update(downloaded, total_size)

            if total_size > 0 and downloaded != total_size:
                raise LauncherError(translate("download_incomplete", downloaded=downloaded, total_size=total_size))
            if digest.hexdigest().lower() != expected_sha256.lower():
                raise LauncherError(translate("digest_failed"))
            partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def download_and_run_installer(root: tk.Tk) -> None:
    progress: ProgressWindow | None = None
    try:
        asset = latest_setup_asset()
        destination = Path(tempfile.gettempdir()) / asset.name
        progress = ProgressWindow(root)
        download_file(asset.url, destination, progress, asset.sha256)
    except Exception as exc:
        if progress:
            progress.close()
        release_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest"
        if messagebox.askyesno(APP_TITLE, translate("download_failed", detail=exc)):
            webbrowser.open(release_url)
        return

    if progress:
        progress.close()
    if os.name == "nt":
        os.startfile(str(destination))
    else:
        subprocess.Popen([str(destination)], close_fds=True)


def main() -> int:
    if os.environ.get("APP05_FILEOPS_SELFTEST") == "1":
        latest_setup_asset()
        find_installed_exe()
        return 0

    root = tk.Tk()
    root.withdraw()

    installed_exe = find_installed_exe()
    if installed_exe:
        if os.name == "nt":
            os.chdir(str(installed_exe.parent))
            os.startfile(str(installed_exe))
        else:
            subprocess.Popen([str(installed_exe)], cwd=str(installed_exe.parent), close_fds=True)
        return 0

    should_install = messagebox.askyesno(
        APP_TITLE,
        translate("not_installed"),
    )
    if should_install:
        download_and_run_installer(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
