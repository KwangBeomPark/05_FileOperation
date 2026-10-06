"""Dependency-free product identity shared by runtime, launcher, and packaging.

Windows identities remain stable; the new data folder deliberately starts fresh.
"""

import re
import os
import sys
from pathlib import Path

PRODUCT_ID = "App005_FileOps"
DISPLAY_NAME = "FileOps Hub"
APP_EXE = f"{PRODUCT_ID}.exe"
INSTALL_DIR = "FileOps"
LEGACY_EXE_NAMES = ("App05_FileOps.exe", "IntegratedDataTool.exe")
APP_EXE_NAMES = (APP_EXE, *LEGACY_EXE_NAMES)
LEGACY_INSTALL_DIRS = ("App005_FileOps", "App05_FileOps", "IntegratedDataTool", "FileOps Hub")
USER_SETTING_DIR = "UserSetting"
CONFIG_FILENAME = "settings.json"
INSTALLER_APP_ID = "{2A0D58B7-8D1D-44B1-9C3A-2B33F4F3DF11}"
WINDOWS_APP_ID = "fileops.hub.desktop.v1"
INSTALLER_BASENAME = f"{PRODUCT_ID}_Setup"
LAUNCHER_BASENAME = f"{PRODUCT_ID}_Launcher"


def version_from_tag(tag_name: str) -> str | None:
    """Accept numeric release versions without accepting paths or suffixes."""
    raw_tag = tag_name.strip()
    version = raw_tag[1:] if raw_tag[:1].lower() == "v" else raw_tag
    return version if re.fullmatch(r"\d+(?:\.\d+)*", version) else None


def installer_names_for_tag(tag_name: str) -> list[str]:
    """Prefer the canonical installer and accept known historical installers.

App05_FileOps_v* was a launcher before v1.4.1; it must never be selected as
an installer for those releases.
"""
    version = version_from_tag(tag_name)
    if not version:
        return []
    names = [
        f"{INSTALLER_BASENAME}_v{version}.exe",
        f"App05_FileOps_Setup_v{version}.exe",
        f"IntegratedDataTool_Setup_v{version}.exe",
    ]
    parts = tuple(int(part) for part in version.split("."))
    if parts >= (1, 4, 1):
        names.append(f"App05_FileOps_v{version}.exe")
    return names


def asset_path(filename: str) -> Path:
    """Resolve the same assets/ layout in source and PyInstaller builds."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / filename


def user_data_dir() -> Path:
    """Store settings/logs/history in the installed application's UserSetting.

Source runs use the approved default folder rather than the Python runtime
folder. Frozen custom installations use their real executable directory.
No old IntegratedDataTool/FileOps data is imported.
"""
    if getattr(sys, "frozen", False) and Path(sys.executable).name.lower() == APP_EXE.lower():
        return Path(sys.executable).parent / USER_SETTING_DIR
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    elif os.environ.get("USERPROFILE"):
        base = Path(os.environ["USERPROFILE"]) / "AppData" / "Local"
    else:
        base = Path.cwd()
    return base / "Programs" / INSTALL_DIR / USER_SETTING_DIR
