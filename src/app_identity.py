"""Dependency-free product identity shared by runtime, launcher, and packaging.

Windows identities and existing UserSetting remain stable across name changes.
"""

import os
import re
import sys
from pathlib import Path

PRODUCT_ID = "App05_FileOps"
DISPLAY_NAME = "FileOps Hub"
APP_EXE = f"{PRODUCT_ID}.exe"
INSTALL_DIR = "FileOps"
LEGACY_EXE_NAMES = ("App005_FileOps.exe", "IntegratedDataTool.exe", "FileOps.exe")
APP_EXE_NAMES = (APP_EXE, *LEGACY_EXE_NAMES)
LEGACY_INSTALL_DIRS = ("App005_FileOps", "App05_FileOps", "IntegratedDataTool", "FileOps Hub")
USER_SETTING_DIR = "UserSetting"
CONFIG_FILENAME = "settings.json"
INSTALLER_APP_ID = "{2A0D58B7-8D1D-44B1-9C3A-2B33F4F3DF11}"
WINDOWS_APP_ID = "fileops.hub.desktop.v1"
INSTALLER_BASENAME = f"{PRODUCT_ID}_Setup"
PUBLIC_INSTALLER_BASENAME = "FileOps-Setup"
LAUNCHER_BASENAME = f"{PRODUCT_ID}_Launcher"
LEGACY_INSTALLER_BASENAMES = ("App005_FileOps_Setup", "App05_FileOps_Setup", "IntegratedDataTool_Setup")
LEGACY_SHORTCUT_NAMES = ("App005_FileOps", "App05_FileOps", "IntegratedDataTool")
LANGUAGE_ENV_NAMES = ("APP05_LANGUAGE", "APP005_LANGUAGE")
SELFTEST_ENV_NAMES = ("APP05_FILEOPS_SELFTEST", "APP005_FILEOPS_SELFTEST")
SECURITY_DESCRIPTION = f"{PRODUCT_ID} Security"


def installer_filenames(version: str) -> tuple[str, ...]:
    """Generate only the canonical installer; historical names are read-only compatibility."""
    if version_from_tag(version) != version:
        raise ValueError("Invalid artifact version")
    return (f"{INSTALLER_BASENAME}_v{version}.exe",)


def version_from_tag(tag_name: str) -> str | None:
    """Accept numeric release versions without accepting paths or suffixes."""
    raw_tag = tag_name.strip()
    version = raw_tag[1:] if raw_tag[:1].lower() == "v" else raw_tag
    return version if re.fullmatch(r"\d+(?:\.\d+)*", version) else None


def installer_names_for_tag(tag_name: str) -> list[str]:
    """Prefer the canonical installer and accept known historical installers.

    The ambiguous historical product_v* file was a launcher before v1.4.1.
    """
    version = version_from_tag(tag_name)
    if not version:
        return []
    names = list(installer_filenames(version))
    names.extend((f"{PRODUCT_ID}-Setup_v{version}.exe", f"{PUBLIC_INSTALLER_BASENAME}.v{version}.exe"))
    names.extend(f"{basename}_v{version}.exe" for basename in LEGACY_INSTALLER_BASENAMES)
    parts = tuple(int(part) for part in version.split("."))
    if parts >= (1, 4, 1):
        names.append(f"{PRODUCT_ID}_v{version}.exe")
    return list(dict.fromkeys(names))


def asset_path(filename: str) -> Path:
    """Resolve the same assets/ layout in source and PyInstaller builds."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / filename


def user_data_dir() -> Path:
    """Store settings/logs/history in the installed application's UserSetting.

    Source runs use the approved default rather than the Python runtime folder.
    Frozen custom installations keep using their existing UserSetting directory.
    Legacy external data stores are not automatically imported.
    """
    if getattr(sys, "frozen", False) and Path(sys.executable).name.lower() in {name.lower() for name in APP_EXE_NAMES}:
        return Path(sys.executable).parent / USER_SETTING_DIR
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    elif os.environ.get("USERPROFILE"):
        base = Path(os.environ["USERPROFILE"]) / "AppData" / "Local"
    else:
        base = Path.cwd()
    return base / "Programs" / INSTALL_DIR / USER_SETTING_DIR
