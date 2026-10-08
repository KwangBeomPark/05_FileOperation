"""Windows Startup shortcut manager for FileOps Hub.

Provides runtime management of the user's Start Menu Startup folder shortcut,
enabling or disabling background tray auto-start on Windows logon.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

from src.app_identity import DISPLAY_NAME, asset_path
from src.utils.logger import get_logger

logger = get_logger()

STARTUP_SHORTCUT_NAME = f"{DISPLAY_NAME}.lnk"
LEGACY_SHORTCUT_NAMES = (
    "FileOps.lnk",
    "App05_FileOperation.lnk",
    "App005_FileOps.lnk",
    "App05_FileOps.lnk",
    "IntegratedDataTool.lnk",
)


def get_startup_folder() -> Path:
    """Return the Windows user startup directory."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return Path.home() / r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"


def get_startup_shortcut_path() -> Path:
    """Return the canonical path to the FileOps Hub startup shortcut."""
    return get_startup_folder() / STARTUP_SHORTCUT_NAME


def clean_legacy_startup_shortcuts() -> None:
    """Remove known legacy startup shortcut filenames to prevent duplicates."""
    folder = get_startup_folder()
    if not folder.is_dir():
        return
    for legacy_name in LEGACY_SHORTCUT_NAMES:
        if legacy_name.lower() == STARTUP_SHORTCUT_NAME.lower():
            continue
        legacy_path = folder / legacy_name
        if legacy_path.is_file():
            try:
                legacy_path.unlink()
                logger.info("Removed legacy startup shortcut: %s", legacy_path)
            except Exception as exc:
                logger.warning("Failed to remove legacy startup shortcut %s: %s", legacy_path, exc)


def is_startup_enabled() -> bool:
    """Check if the canonical FileOps Hub startup shortcut currently exists."""
    shortcut_path = get_startup_shortcut_path()
    return shortcut_path.is_file()


def resolve_startup_target_and_arguments() -> tuple[str, str, str]:
    """Resolve target executable, execution arguments, and working directory."""
    if getattr(sys, "frozen", False):
        target = str(Path(sys.executable).resolve())
        arguments = "--tray"
        working_dir = str(Path(sys.executable).resolve().parent)
    else:
        python_dir = Path(sys.executable).resolve().parent
        pythonw = python_dir / "pythonw.exe"
        target = str(pythonw if pythonw.is_file() else Path(sys.executable).resolve())
        project_root = Path(__file__).resolve().parents[2]
        main_py = project_root / "src" / "main.py"
        arguments = f'"{main_py}" --tray'
        working_dir = str(project_root)
    return target, arguments, working_dir


def _create_shortcut_wscript(
    shortcut_path: Path,
    target: str,
    arguments: str,
    working_dir: str,
    icon_location: str,
) -> None:
    """Create Windows shortcut using Windows COM WScript.Shell, with PowerShell fallback."""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_path))
        shortcut.TargetPath = target
        shortcut.Arguments = arguments
        shortcut.WorkingDirectory = working_dir
        if icon_location and os.path.exists(icon_location):
            shortcut.IconLocation = icon_location
        shortcut.Description = f"{DISPLAY_NAME} (Background Tray)"
        shortcut.Save()
        return
    except Exception as exc:
        logger.warning("win32com CreateShortcut failed (%s); falling back to PowerShell.", exc)

    def _ps_quote(val: str) -> str:
        return "'" + str(val).replace("'", "''") + "'"

    icon_str = _ps_quote(icon_location) if (icon_location and os.path.exists(icon_location)) else "''"
    ps_script = f"""
$taskShell = New-Object -ComObject WScript.Shell
$taskShortcut = $taskShell.CreateShortcut({_ps_quote(shortcut_path)})
$taskShortcut.TargetPath = {_ps_quote(target)}
$taskShortcut.Arguments = {_ps_quote(arguments)}
$taskShortcut.WorkingDirectory = {_ps_quote(working_dir)}
if ({icon_str}) {{ $taskShortcut.IconLocation = {icon_str} }}
$taskShortcut.Description = '{DISPLAY_NAME} (Background Tray)'
$taskShortcut.Save()
"""
    encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "PowerShell shortcut creation failed.")


def set_startup_enabled(enabled: bool) -> bool:
    """Create or remove the Windows Startup shortcut for FileOps Hub."""
    clean_legacy_startup_shortcuts()
    shortcut_path = get_startup_shortcut_path()
    try:
        if enabled:
            shortcut_path.parent.mkdir(parents=True, exist_ok=True)
            target, arguments, working_dir = resolve_startup_target_and_arguments()
            icon_location = str(asset_path("icon.ico"))
            _create_shortcut_wscript(
                shortcut_path=shortcut_path,
                target=target,
                arguments=arguments,
                working_dir=working_dir,
                icon_location=icon_location,
            )
            logger.info("Startup shortcut created: %s -> %s %s", shortcut_path, target, arguments)
            return True
        else:
            if shortcut_path.is_file():
                shortcut_path.unlink()
                logger.info("Startup shortcut removed: %s", shortcut_path)
            return True
    except Exception as exc:
        logger.error("Failed to set startup enabled (%s): %s", enabled, exc)
        return False


def toggle_startup() -> bool:
    """Toggle the startup shortcut state and return the new state."""
    current = is_startup_enabled()
    new_state = not current
    success = set_startup_enabled(new_state)
    return is_startup_enabled() if success else current
