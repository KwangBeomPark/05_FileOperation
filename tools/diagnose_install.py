from __future__ import annotations

import argparse
import importlib
import os
import platform
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.preflight import (
    check_ocr_engines as preflight_check_ocr_engines,
    check_github_updater_settings as preflight_check_github_updater_settings,
    check_office_apps as preflight_check_office_apps,
    check_playwright_driver as preflight_check_playwright_driver,
)
from src.utils.config_manager import ConfigManager
from src.version import APP_VERSION

RELEASE_DIR = ROOT / "release"


def status(ok: bool, label: str, detail: str = "") -> bool:
    prefix = "OK " if ok else "ERR"
    suffix = f" - {detail}" if detail else ""
    print(f"[{prefix}] {label}{suffix}")
    return ok


def warn(label: str, detail: str = "") -> bool:
    suffix = f" - {detail}" if detail else ""
    print(f"[WARN] {label}{suffix}")
    return True


def check_import(module_name: str, label: str | None = None) -> bool:
    label = label or module_name
    try:
        importlib.import_module(module_name)
        return status(True, label)
    except Exception as exc:
        return status(False, label, str(exc))


def check_python_environment() -> bool:
    ok = True
    ok &= status(platform.system() == "Windows", "Windows host", platform.platform())
    ok &= status(sys.version_info >= (3, 11), "Python version", sys.version.split()[0])
    ok &= status((ROOT / "src" / "main.py").exists(), "source tree", str(ROOT))
    return ok


def check_python_packages() -> bool:
    checks = [
        ("PyQt6.QtWidgets", "PyQt6"),
        ("fitz", "PyMuPDF"),
        ("pytesseract", "pytesseract"),
        ("PIL.Image", "Pillow"),
        ("playwright.sync_api", "playwright"),
        ("qtawesome", "qtawesome"),
        ("win32com.client", "pywin32 win32com"),
        ("pythoncom", "pywin32 pythoncom"),
    ]
    ok = True
    for module_name, label in checks:
        ok &= check_import(module_name, label)
    return ok


def check_build_artifacts() -> bool:
    dist = ROOT / "dist"
    app_exe = dist / "IntegratedDataTool.exe"
    setup_exe = setup_exe_path()
    launcher_exe = launcher_exe_path()
    ok = True
    ok &= status(app_exe.exists(), "app exe", str(app_exe))
    ok &= status(setup_exe.exists(), "installer exe", str(setup_exe))
    ok &= status(launcher_exe.exists(), "release launcher", str(launcher_exe))
    iscc = find_iscc()
    if iscc:
        ok &= status(True, "Inno Setup compiler", iscc)
    else:
        ok &= warn("Inno Setup compiler", "missing; required only when building setup exe")
    return ok


def setup_exe_path() -> Path:
    return RELEASE_DIR / f"IntegratedDataTool_Setup_v{APP_VERSION}.exe"


def launcher_exe_path() -> Path:
    return RELEASE_DIR / f"App05_FileOps_v{APP_VERSION}.exe"


def find_iscc() -> str | None:
    found = shutil.which("iscc")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def check_tesseract() -> bool:
    config_manager = type("Config", (), {"get": lambda _self, _key, default="": default})()
    ok, detail, using_fallback = preflight_check_ocr_engines(config_manager)
    if ok and not using_fallback:
        return status(True, "OCR engine", detail)
    if ok:
        return warn("OCR engine", detail)
    return status(False, "OCR engine", detail)


def check_playwright_runtime(check_browser: bool) -> bool:
    ok, detail = preflight_check_playwright_driver(check_browser=check_browser)
    return status(ok, "Playwright driver/runtime", detail)


def check_office() -> bool:
    ok, errors = preflight_check_office_apps(["Excel.Application", "Word.Application", "PowerPoint.Application"])
    if ok:
        return status(True, "Office COM apps")
    for error in errors:
        status(False, "Office COM app", error)
    return False


def check_github_updater() -> bool:
    ok, detail = preflight_check_github_updater_settings(ConfigManager())
    if ok:
        return status(True, "GitHub updater settings", detail)
    return warn("GitHub updater settings", detail)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose FileOps Hub install/build prerequisites.")
    parser.add_argument("--check-browser", action="store_true", help="Try to launch Playwright Chromium.")
    parser.add_argument("--check-office", action="store_true", help="Try to instantiate Office COM apps.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok = True
    ok &= check_python_environment()
    ok &= check_python_packages()
    ok &= check_build_artifacts()
    ok &= check_tesseract()
    ok &= check_playwright_runtime(check_browser=args.check_browser)
    ok &= check_github_updater()

    if args.check_office:
        ok &= check_office()
    else:
        print("[SKIP] Office COM launch check - pass --check-office to run it.")

    if ok:
        print("\nDiagnosis completed without blocking issues.")
        return 0

    print("\nDiagnosis found blocking or environment-specific issues.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
