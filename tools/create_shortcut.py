"""Create a development desktop shortcut without assuming a checkout location."""
import base64
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app_identity import APP_EXE_NAMES, DISPLAY_NAME, asset_path


def ps_literal(value):
    """Quote a literal PowerShell string, including apostrophes in folder names."""
    return "'" + str(value).replace("'", "''") + "'"


def create_desktop_shortcut():
    """Prefer the canonical compiled app; otherwise launch the repository source."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    target = pythonw if pythonw.is_file() else Path(sys.executable)
    arguments = '"' + str(ROOT / "src" / "main.py") + '"'
    for exe_name in APP_EXE_NAMES:
        candidate = ROOT / "dist" / exe_name
        if candidate.is_file():
            target, arguments = candidate, ""
            break
    script = f"""
$taskShell = New-Object -ComObject WScript.Shell
$taskDesktop = $taskShell.SpecialFolders.Item('Desktop')
$taskShortcut = $taskShell.CreateShortcut((Join-Path $taskDesktop {ps_literal(DISPLAY_NAME + '.lnk')}))
$taskShortcut.TargetPath = {ps_literal(target)}
$taskShortcut.Arguments = {ps_literal(arguments)}
$taskShortcut.WorkingDirectory = {ps_literal(ROOT)}
$taskShortcut.IconLocation = {ps_literal(asset_path('icon.ico'))}
$taskShortcut.Description = 'FileOps Hub - File Operations'
$taskShortcut.Save()
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Desktop shortcut creation failed.")
    print(f"Desktop shortcut created: {DISPLAY_NAME}.lnk")


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Desktop shortcuts require Windows.")
    create_desktop_shortcut()
