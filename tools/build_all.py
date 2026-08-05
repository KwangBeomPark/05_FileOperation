from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SPEC_FILE = ROOT / "tools" / "IntegratedDataTool.spec"
SETUP_SCRIPT = ROOT / "tools" / "setup.iss"
DIST_DIR = ROOT / "dist"
RELEASE_DIR = ROOT / "release"
LOCAL_BUILD_DIR = ROOT / "tools" / "_local"
APP_EXE = DIST_DIR / "IntegratedDataTool.exe"
LAUNCHER_SOURCE = ROOT / "tools" / "App05_FileOps.pyw"
LAUNCHER_BASENAME = "App05_FileOps"
VERSION_FILE = SRC / "version.py"
VERSION_PATTERN = re.compile(r'^APP_VERSION\s*=\s*["\'](\d+(?:\.\d+)*)["\']\s*$', re.MULTILINE)


def format_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if sys.platform == "win32" else " ".join(command)


def run(command: list[str], *, required: bool = True, env: dict[str, str] | None = None) -> int:
    print(f"\n$ {format_command(command)}")
    completed = subprocess.run(command, cwd=ROOT, env=env)
    if required and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed.returncode


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def require_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Required file is missing: {path}")


def read_app_version() -> str:
    require_file(VERSION_FILE)
    match = VERSION_PATTERN.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"APP_VERSION is missing or invalid in {VERSION_FILE}")
    return match.group(1)


def setup_exe_path(app_version: str) -> Path:
    return RELEASE_DIR / f"IntegratedDataTool_Setup_v{app_version}.exe"


def launcher_exe_path(app_version: str) -> Path:
    return RELEASE_DIR / f"{LAUNCHER_BASENAME}_v{app_version}.exe"


def version_tuple(app_version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in app_version.split(".")]
    if len(parts) > 4:
        raise SystemExit("App version may contain at most four numeric components.")
    return tuple((parts + [0, 0, 0, 0])[:4])


def write_version_resource(
    app_version: str,
    *,
    resource_name: str,
    file_description: str,
    internal_name: str,
    original_filename: str,
) -> Path:
    LOCAL_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    resource = LOCAL_BUILD_DIR / resource_name
    file_version = version_tuple(app_version)
    resource.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={file_version},
    prodvers={file_version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'FileOps Hub'),
        StringStruct('FileDescription', '{file_description}'),
        StringStruct('FileVersion', '{app_version}'),
        StringStruct('InternalName', '{internal_name}'),
        StringStruct('OriginalFilename', '{original_filename}'),
        StringStruct('ProductName', 'FileOps Hub'),
        StringStruct('ProductVersion', '{app_version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return resource


def ensure_app_not_running() -> None:
    if sys.platform != "win32":
        return
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq IntegratedDataTool.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0 and "IntegratedDataTool.exe" in completed.stdout:
        raise SystemExit("IntegratedDataTool.exe is running. Close the app before building release artifacts.")


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def find_iscc() -> str | None:
    found = shutil.which("iscc")
    if found:
        return found
    candidates = [
        Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    return next((str(candidate) for candidate in candidates if candidate.exists()), None)


def find_signtool() -> str | None:
    configured = os.environ.get("FILEOPS_SIGNTOOL_PATH", "")
    if configured and Path(configured).exists():
        return configured
    return shutil.which("signtool")


def require_signing_configuration() -> None:
    """Fail before a release build when public Authenticode signing is mandatory."""
    thumbprint = os.environ.get("FILEOPS_SIGN_CERT_SHA1", "").replace(" ", "")
    if not thumbprint or not find_signtool():
        raise SystemExit("Code signing was requested but FILEOPS_SIGN_CERT_SHA1 or signtool is unavailable.")


def verify_source_tree() -> None:
    for path in (SRC / "main.py", VERSION_FILE, SPEC_FILE, SETUP_SCRIPT, LAUNCHER_SOURCE, ROOT / "requirements.txt"):
        require_file(path)


def run_static_checks(skip_ruff: bool, skip_tests: bool) -> None:
    run([sys.executable, "-m", "compileall", "-q", "src", "tools", str(LAUNCHER_SOURCE)])
    run([sys.executable, "-m", "pip", "check"])
    if not skip_tests:
        run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py", "-v"])

    if skip_ruff:
        print("\nSkipping ruff check by request.")
    elif module_available("ruff"):
        run([sys.executable, "-m", "ruff", "check", "src", "tools", "--select", "E9,F,B"])
    else:
        print("\nRuff is not installed; skipping optional ruff check.")


def build_app(skip_pyinstaller: bool, app_version: str) -> None:
    if skip_pyinstaller:
        print("\nSkipping PyInstaller build by request.")
        require_file(APP_EXE)
        return
    if not module_available("PyInstaller"):
        raise SystemExit("PyInstaller is not installed. Run: python -m pip install -r requirements.txt")

    environment = os.environ.copy()
    environment["FILEOPS_VERSION_FILE"] = str(
        write_version_resource(
            app_version,
            resource_name="IntegratedDataTool.version",
            file_description="Integrated Data and File Utility",
            internal_name="IntegratedDataTool",
            original_filename="IntegratedDataTool.exe",
        )
    )
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_FILE)], env=environment)
    require_file(APP_EXE)
    print(f"\nBuilt app: {APP_EXE}")
    print(f"Size: {APP_EXE.stat().st_size:,} bytes")
    print(f"SHA-256: {sha256(APP_EXE)}")


def build_launcher(skip_pyinstaller: bool, app_version: str) -> Path:
    """Build the standalone launcher that accompanies the signed release installer."""
    launcher_exe = launcher_exe_path(app_version)
    if skip_pyinstaller:
        print("\nSkipping App05 launcher build by request.")
        require_file(launcher_exe)
        return launcher_exe
    if not module_available("PyInstaller"):
        raise SystemExit("PyInstaller is not installed. Run: python -m pip install -r requirements.txt")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    version_resource = write_version_resource(
        app_version,
        resource_name="App05_FileOps.version",
        file_description="FileOps Hub Launcher",
        internal_name=LAUNCHER_BASENAME,
        original_filename=launcher_exe.name,
    )
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            launcher_exe.stem,
            "--distpath",
            str(RELEASE_DIR),
            "--workpath",
            str(LOCAL_BUILD_DIR / "app05_build"),
            "--specpath",
            str(LOCAL_BUILD_DIR),
            "--version-file",
            str(version_resource),
            str(LAUNCHER_SOURCE),
        ]
    )
    require_file(launcher_exe)
    print(f"\nBuilt launcher: {launcher_exe}")
    print(f"Size: {launcher_exe.stat().st_size:,} bytes")
    print(f"SHA-256: {sha256(launcher_exe)}")
    return launcher_exe


def ensure_output_available(path: Path, allow_overwrite: bool) -> None:
    if path.exists() and not allow_overwrite:
        raise SystemExit(f"Refusing to overwrite existing release artifact: {path}. Bump APP_VERSION or pass --overwrite.")


def build_installer(skip_installer: bool, app_version: str, allow_overwrite: bool) -> Path | None:
    if skip_installer:
        print("\nSkipping Inno Setup installer build by request.")
        return None
    iscc = find_iscc()
    if not iscc:
        raise SystemExit("Inno Setup compiler (iscc) was not found.")

    setup_exe = setup_exe_path(app_version)
    ensure_output_available(setup_exe, allow_overwrite)
    run([iscc, f"/DAppVersion={app_version}", str(SETUP_SCRIPT)])
    require_file(setup_exe)
    print(f"\nBuilt installer: {setup_exe}")
    print(f"Size: {setup_exe.stat().st_size:,} bytes")
    print(f"SHA-256: {sha256(setup_exe)}")
    return setup_exe


def sign_artifact(path: Path, required: bool) -> None:
    thumbprint = os.environ.get("FILEOPS_SIGN_CERT_SHA1", "").replace(" ", "")
    signtool = find_signtool()
    if not thumbprint or not signtool:
        message = "Code signing was requested but FILEOPS_SIGN_CERT_SHA1 or signtool is unavailable."
        if required:
            raise SystemExit(message)
        print(f"\nWARNING: {message}")
        return
    timestamp_url = os.environ.get("FILEOPS_TIMESTAMP_URL", "http://timestamp.digicert.com")
    run([signtool, "sign", "/sha1", thumbprint, "/fd", "SHA256", "/tr", timestamp_url, "/td", "SHA256", str(path)])
    run([signtool, "verify", "/pa", "/v", str(path)])


def write_checksum_manifest(app_version: str, setup_exe: Path | None, launcher_exe: Path) -> None:
    if not setup_exe:
        return
    manifest = RELEASE_DIR / f"IntegratedDataTool_Setup_v{app_version}.sha256"
    manifest.write_text(
        f"{sha256(setup_exe)}  {setup_exe.name}\n{sha256(launcher_exe)}  {launcher_exe.name}\n",
        encoding="ascii",
    )
    print(f"Checksum manifest: {manifest}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and build FileOps Hub release artifacts.")
    parser.add_argument("--skip-ruff", action="store_true", help="Skip optional ruff check.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip unit tests.")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="Do not rebuild the app exe.")
    parser.add_argument("--skip-installer", action="store_true", help="Do not build the Inno Setup installer.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing versioned installer artifact.")
    parser.add_argument("--sign", action="store_true", help="Sign artifacts when FILEOPS_SIGN_CERT_SHA1 is configured.")
    parser.add_argument("--require-signature", action="store_true", help="Fail the build unless every release executable is Authenticode signed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    verify_source_tree()
    if args.require_signature:
        require_signing_configuration()
    if not args.skip_pyinstaller or not args.skip_installer:
        ensure_app_not_running()
    app_version = read_app_version()
    run_static_checks(skip_ruff=args.skip_ruff, skip_tests=args.skip_tests)
    build_app(skip_pyinstaller=args.skip_pyinstaller, app_version=app_version)
    launcher_exe = build_launcher(skip_pyinstaller=args.skip_pyinstaller, app_version=app_version)

    signing_requested = args.sign or args.require_signature
    if signing_requested:
        sign_artifact(APP_EXE, required=args.require_signature)
        sign_artifact(launcher_exe, required=args.require_signature)
    else:
        print("\nWARNING: Build artifacts are unsigned. Use --require-signature for a public release.")

    setup_exe = build_installer(args.skip_installer, app_version, args.overwrite)
    if setup_exe and signing_requested:
        sign_artifact(setup_exe, required=args.require_signature)
    write_checksum_manifest(app_version, setup_exe, launcher_exe)
    print("\nBuild checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
