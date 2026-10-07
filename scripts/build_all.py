from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app_identity import (
    APP_EXE as APP_EXE_NAME, APP_EXE_NAMES, DISPLAY_NAME, INSTALL_DIR, INSTALLER_APP_ID,
    INSTALLER_BASENAME, LAUNCHER_BASENAME, PRODUCT_ID, WINDOWS_APP_ID,
    LEGACY_SHORTCUT_NAMES, LEGACY_EXE_NAMES, installer_filenames,
)

SRC = ROOT / "src"
SPEC_FILE = ROOT / "scripts" / f"{PRODUCT_ID}.spec"
SETUP_SCRIPT = ROOT / "installer" / "setup.iss"
DIST_DIR = ROOT / "dist"
RELEASE_DIR = ROOT / "release"
LOCAL_BUILD_DIR = ROOT / "tools" / "_local"
APP_EXE = DIST_DIR / APP_EXE_NAME
LAUNCHER_SOURCE = ROOT / "scripts" / f"{LAUNCHER_BASENAME}.pyw"
APP_ICON = ROOT / "assets" / "icon.ico"
VERSION_FILE = SRC / "version.py"
VERSION_PATTERN = re.compile(r'^APP_VERSION\s*=\s*["\'](\d+(?:\.\d+)*)["\']\s*$', re.MULTILINE)


def format_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if sys.platform == "win32" else " ".join(command)


def run(command: list[str], *, required: bool = True, env: dict[str, str] | None = None) -> int:
    print(f"\n$ {format_command(command)}")
    if Path(command[0]).name.lower() == "powershell.exe":
        env = (os.environ if env is None else env).copy()
        env.pop("PSModulePath", None)  # Do not load PowerShell 7 modules into Windows PowerShell.
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
    return RELEASE_DIR / f"{INSTALLER_BASENAME}_v{app_version}.exe"


def public_setup_exe_path(app_version: str) -> Path:
    return RELEASE_DIR / installer_filenames(app_version)[1]


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
    for exe_name in APP_EXE_NAMES:
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0 and exe_name in completed.stdout:
            raise SystemExit(f"{exe_name} is running. Close the app before building release artifacts.")


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
    if configured:
        if not Path(configured).is_file():
            raise SystemExit("Configured FILEOPS_SIGNTOOL_PATH does not exist; no fallback is allowed.")
        return configured
    found = shutil.which("signtool")
    if found:
        return found
    sdk_bin = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    if sdk_bin.is_dir():
        for sdk_version in sorted(sdk_bin.iterdir(), reverse=True):
            candidate = sdk_version / "x64" / "signtool.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def require_signing_configuration() -> None:
    """Fail before a release build when public Authenticode signing is mandatory."""
    thumbprint = os.environ.get("FILEOPS_SIGN_CERT_SHA1", "").replace(" ", "")
    signtool = find_signtool()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", thumbprint) or not signtool:
        raise SystemExit("Code signing was requested but FILEOPS_SIGN_CERT_SHA1 or signtool is unavailable.")
    verify_signtool(signtool)


def verify_signtool(signtool: str) -> None:
    """Do not execute a PATH/configured tool before checking Microsoft's signature."""
    literal_path = str(signtool).replace("'", "''")
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "Import-Module ([IO.Path]::Combine($PSHOME, 'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1')) -ErrorAction Stop; "
        f"$tool = Get-AuthenticodeSignature -LiteralPath '{literal_path}'; "
        "if ($tool.Status -ne 'Valid' -or "
        "$tool.SignerCertificate.Subject -notlike 'CN=Microsoft Corporation,*') { "
        "throw 'SignTool must have a valid Microsoft signature.' }"
    )
    run([windows_powershell_path(), "-NoProfile", "-NonInteractive", "-Command", script])


def windows_powershell_path() -> str:
    """Never resolve a trust-verification shell through the current directory/PATH."""
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) /
               "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def ensure_version_not_reused(app_version: str) -> None:
    """Reject a tagged version from a different source commit before signing."""
    tag = f"v{app_version}"
    result = subprocess.run(["git", "tag", "--list", tag], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit("Cannot inspect version tags; signed build stopped.")
    if result.stdout.strip():
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        tagged = subprocess.run(["git", "rev-parse", f"{tag}^{{commit}}"], cwd=ROOT, capture_output=True, text=True)
        if head.returncode or tagged.returncode or head.stdout.strip() != tagged.stdout.strip():
            raise SystemExit(f"{tag} belongs to an earlier source commit. Choose a new APP_VERSION before signing.")


def verify_source_tree() -> None:
    for path in (SRC / "main.py", VERSION_FILE, SPEC_FILE, SETUP_SCRIPT, LAUNCHER_SOURCE, APP_ICON,
                 ROOT / "requirements.txt", ROOT / "tools" / "verify_packaged_sources.py"):
        require_file(path)


def run_static_checks(skip_ruff: bool, skip_tests: bool) -> None:
    run([sys.executable, "-m", "compileall", "-q", "src", "scripts", "tools"])
    run([sys.executable, "-m", "pip", "check"])
    if not skip_tests:
        # Isolate test settings, but preserve the real signing-session environment.
        with tempfile.TemporaryDirectory(prefix="app05-release-tests-") as test_dir:
            test_environment = os.environ.copy()
            test_environment["LOCALAPPDATA"] = test_dir
            test_environment["QT_QPA_PLATFORM"] = "offscreen"
            run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py", "-v"],
                env=test_environment,
            )

    if skip_ruff:
        print("\nSkipping ruff check by request.")
    elif module_available("ruff"):
        run([sys.executable, "-m", "ruff", "check", "src", "scripts", "tools", "--select", "E9,F,B"])
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
            resource_name=f"{PRODUCT_ID}.version",
            file_description=DISPLAY_NAME,
            internal_name=PRODUCT_ID,
            original_filename=APP_EXE_NAME,
        )
    )
    run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--workpath", str(LOCAL_BUILD_DIR / "main_build"),
        "--distpath", str(APP_EXE.parent), str(SPEC_FILE),
    ], env=environment)
    require_file(APP_EXE)
    print(f"\nBuilt app: {APP_EXE}")
    print(f"Size: {APP_EXE.stat().st_size:,} bytes")
    print(f"SHA-256: {sha256(APP_EXE)}")


def build_launcher(skip_pyinstaller: bool, app_version: str) -> Path:
    """Build the standalone launcher that accompanies the signed release installer."""
    launcher_exe = launcher_exe_path(app_version)
    if skip_pyinstaller:
        print("\nSkipping optional launcher build by request.")
        require_file(launcher_exe)
        return launcher_exe
    if not module_available("PyInstaller"):
        raise SystemExit("PyInstaller is not installed. Run: python -m pip install -r requirements.txt")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    version_resource = write_version_resource(
        app_version,
        resource_name=f"{LAUNCHER_BASENAME}.version",
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
            "--paths",
            str(ROOT),
            "--windowed",
            "--name",
            launcher_exe.stem,
            "--distpath",
            str(RELEASE_DIR),
            "--workpath",
            str(LOCAL_BUILD_DIR / "launcher_build"),
            "--specpath",
            str(LOCAL_BUILD_DIR),
            "--version-file",
            str(version_resource),
            "--icon",
            str(APP_ICON),
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


def installer_command(iscc: str, app_version: str) -> list[str]:
    """Inject version, product identity, and source path from the Python contract."""
    return [
        iscc,
        f"/O{RELEASE_DIR}",
        f"/DAppVersion={app_version}",
        f"/DAppProductId={PRODUCT_ID}",
        f"/DAppInstallDir={INSTALL_DIR}",
        f"/DAppExeSource={APP_EXE}",
        f"/DAppInstallerId={{{INSTALLER_APP_ID}",
        f"/DAppWindowsId={WINDOWS_APP_ID}",
        f"/DAppCloseApplications={','.join(APP_EXE_NAMES)}",
        f"/DLegacyShortcutsFile={LOCAL_BUILD_DIR / 'legacy_shortcuts.iss'}",
        str(SETUP_SCRIPT),
    ]


def legacy_shortcut_entries() -> str:
    entries = []
    for name in LEGACY_SHORTCUT_NAMES:
        entries.extend((
            f'Type: files; Name: "{{userdesktop}}\\{name}.lnk"',
            f'Type: files; Name: "{{userprograms}}\\{name}\\{name}.lnk"',
            f'Type: files; Name: "{{userstartup}}\\{name}.lnk"',
        ))
    # Leaf-only obsolete executables in this installation; never old folders or data.
    entries.extend(f'Type: files; Name: "{{app}}\\{name}"' for name in LEGACY_EXE_NAMES)
    return "\n".join(entries)


def build_installer(skip_installer: bool, app_version: str, allow_overwrite: bool) -> Path | None:
    if skip_installer:
        print("\nSkipping Inno Setup installer build by request.")
        return None
    iscc = find_iscc()
    if not iscc:
        raise SystemExit("Inno Setup compiler (iscc) was not found.")

    setup_exe = setup_exe_path(app_version)
    ensure_output_available(setup_exe, allow_overwrite)
    LOCAL_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (LOCAL_BUILD_DIR / "legacy_shortcuts.iss").write_text(legacy_shortcut_entries() + "\n", encoding="utf-8")
    run(installer_command(iscc, app_version))
    require_file(setup_exe)
    print(f"\nBuilt installer: {setup_exe}")
    print(f"Size: {setup_exe.stat().st_size:,} bytes")
    print(f"SHA-256: {sha256(setup_exe)}")
    return setup_exe


def authenticode_verification_command(path: Path, thumbprint: str) -> list[str]:
    """Require Windows trust, the selected signer, and a timestamp on the actual file."""
    literal_path = str(path).replace("'", "''")
    literal_thumbprint = thumbprint.replace("'", "''")
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "Import-Module ([IO.Path]::Combine($PSHOME, 'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1')) -ErrorAction Stop; "
        f"$signature = Get-AuthenticodeSignature -LiteralPath '{literal_path}'; "
        "if ($signature.Status -ne 'Valid' -or $null -eq $signature.TimeStamperCertificate "
        f"-or $signature.SignerCertificate.Thumbprint -ne '{literal_thumbprint}') {{ "
        "[Console]::WriteLine([string]$signature.StatusMessage); exit 1 }; "
        "[Console]::WriteLine('Status: ' + $signature.Status); "
        "[Console]::WriteLine('Signer: ' + $signature.SignerCertificate.Subject); "
        "[Console]::WriteLine('Timestamp: ' + $signature.TimeStamperCertificate.Subject)"
    )
    return [windows_powershell_path(), "-NoProfile", "-NonInteractive", "-Command", script]


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
    verify_signtool(signtool)
    run([signtool, "sign", "/sha1", thumbprint, "/fd", "SHA256", "/tr", timestamp_url, "/td", "SHA256", str(path)])
    run([signtool, "verify", "/pa", "/all", "/v", str(path)])
    run(authenticode_verification_command(path, thumbprint))


def write_checksum_manifest(app_version: str, setup_exe: Path | None, launcher_exe: Path | None = None) -> None:
    if not setup_exe:
        return
    artifacts = [setup_exe]
    public_setup = public_setup_exe_path(app_version)
    if public_setup.is_file():
        artifacts.append(public_setup)
    if APP_EXE.parent == RELEASE_DIR and APP_EXE.is_file():
        artifacts.append(APP_EXE)  # Development app lives in this isolated staging set.
    if launcher_exe and launcher_exe.exists():
        artifacts.append(launcher_exe)
    build_manifest = RELEASE_DIR / "build-manifest.json"
    if build_manifest.is_file():
        artifacts.append(build_manifest)
    content = "".join(f"{sha256(path)}  {path.name}\n" for path in artifacts)
    (RELEASE_DIR / "SHA256SUMS.txt").write_text(content, encoding="utf-8")
    print(f"Checksum manifest: {RELEASE_DIR / 'SHA256SUMS.txt'}")


def write_build_manifest(app_version: str, setup_exe: Path | None, launcher_exe: Path | None, *, signed: bool) -> None:
    """Record the commit, version, and artifacts without personal absolute paths."""
    git_result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    git_status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    artifacts = []
    public_setup = public_setup_exe_path(app_version) if setup_exe else None
    for path in (APP_EXE, setup_exe, public_setup, launcher_exe):
        if path is not None and path.is_file():
            artifacts.append({
                "path": (path.relative_to(ROOT).as_posix() if path == APP_EXE else f"release/{path.name}"),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            })
    payload = {
        "product_id": PRODUCT_ID,
        "display_name": DISPLAY_NAME,
        "version": app_version,
        "git_commit": git_result.stdout.strip() if git_result.returncode == 0 else None,
        "worktree_dirty": bool(git_status.stdout.strip()) if git_status.returncode == 0 else None,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "authenticode_verified": signed,
        "timestamp_type": "RFC3161" if signed else None,
        "signing_certificate_sha1": os.environ.get("FILEOPS_SIGN_CERT_SHA1", "") if signed else None,
        "timestamp_server": os.environ.get("FILEOPS_TIMESTAMP_URL", "http://timestamp.digicert.com") if signed else None,
        "artifacts": artifacts,
    }
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "build-manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and build FileOps Hub release artifacts.")
    parser.add_argument("--skip-ruff", action="store_true", help="Skip optional ruff check.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip unit tests.")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="Do not rebuild the app exe.")
    parser.add_argument("--skip-installer", action="store_true", help="Do not build the Inno Setup installer.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing versioned installer artifact.")
    parser.add_argument("--sign", action="store_true", help="Sign artifacts when FILEOPS_SIGN_CERT_SHA1 is configured.")
    parser.add_argument("--require-signature", action="store_true", help="Fail the build unless every release executable is Authenticode signed.")
    parser.add_argument("--build-launcher", action="store_true", help="Build optional launcher executable.")
    return parser.parse_args()


def prepare_public_alias(app_version: str, setup_exe: Path) -> Path:
    public_setup = public_setup_exe_path(app_version)
    shutil.copy2(setup_exe, public_setup)
    if sha256(public_setup) != sha256(setup_exe):
        raise SystemExit("Enterprise/public installer bytes do not match.")
    return public_setup


def validate_release_payload(folder: Path, app_version: str, *, commit: str | None = None,
                             require_clean: bool = False) -> tuple[dict, list[Path]]:
    """Check the complete signed set before promotion or publication; no mutations."""
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Unsafe release directory.")
    names = [*installer_filenames(app_version), "build-manifest.json"]
    launcher_name = f"{LAUNCHER_BASENAME}_v{app_version}.exe"
    if (folder / launcher_name).exists():
        names.append(launcher_name)
    if {path.name for path in folder.iterdir()} != set(names) | {"SHA256SUMS.txt"}:
        raise ValueError("Release must contain only the current complete release set.")
    paths = [folder / name for name in names]
    checksum_file = folder / "SHA256SUMS.txt"
    for path in [*paths, checksum_file, APP_EXE]:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != path.parent.resolve():
            raise ValueError(f"Unsafe release artifact path: {path.name}")
    manifest = json.loads((folder / "build-manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("version") != app_version or manifest.get("product_id") != PRODUCT_ID or
            manifest.get("authenticode_verified") is not True or manifest.get("alias_only") is True or
            (commit is not None and manifest.get("git_commit") != commit) or
            (require_clean and manifest.get("worktree_dirty") is not False)):
        raise ValueError("Release manifest is unsigned, dirty, stale, alias-only, or a different product.")
    sums = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name in sums or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("Duplicate or malformed checksum entry.")
        sums[name] = digest
    if set(sums) != set(names):
        raise ValueError("Checksums must cover every payload including the build manifest.")
    for path in paths:
        if sums[path.name].upper() != sha256(path):
            raise ValueError(f"Release checksum mismatch: {path.name}")
    if sha256(paths[0]) != sha256(paths[1]):
        raise ValueError("Dual installer aliases must be identical.")
    entries = manifest.get("artifacts", [])
    recorded = {Path(item["path"]).name: item for item in entries}
    executables = [APP_EXE, *(path for path in paths if path.suffix == ".exe")]
    if len(entries) != len(recorded) or set(recorded) != {path.name for path in executables}:
        raise ValueError("Build manifest must contain exactly the current executable set.")
    for path in executables:
        item = recorded[path.name]
        if item["size"] != path.stat().st_size or item["sha256"].upper() != sha256(path):
            raise ValueError(f"Build manifest mismatch: {path.name}")
    return manifest, [*paths, checksum_file]


def verify_signed_payload(manifest: dict, paths: list[Path]) -> None:
    """A manifest flag is not proof: recheck actual Windows trust and timestamps."""
    signer = manifest.get("signing_certificate_sha1") or ""
    signtool = find_signtool()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", signer) or not signtool:
        raise ValueError("Signer identity or Microsoft SignTool unavailable.")
    verify_signtool(signtool)
    for path in [APP_EXE, *(path for path in paths if path.suffix == ".exe")]:
        run([signtool, "verify", "/pa", "/all", "/v", str(path)])
        run(authenticode_verification_command(path, signer))


def promote_verified_release(app_version: str, launcher_exe: Path | None, *, overwrite: bool) -> None:
    """Keep release/ signed-only; preserve the previous set outside the active folder."""
    official = ROOT / "release"
    manifest, paths = validate_release_payload(RELEASE_DIR, app_version)
    verify_signed_payload(manifest, paths)
    if official.is_symlink() or official.resolve().parent != ROOT.resolve():
        raise SystemExit("Unexpected official release path.")
    names = [path.name for path in paths]
    for name in names:
        require_file(RELEASE_DIR / name)
        if name.lower().endswith('.exe'):
            ensure_output_available(official / name, overwrite)
    official.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    prepared = Path(tempfile.mkdtemp(prefix="verified-release-", dir=LOCAL_BUILD_DIR))
    for name in names:
        shutil.copy2(RELEASE_DIR / name, prepared / name)
        if sha256(prepared / name) != sha256(RELEASE_DIR / name):
            raise SystemExit(f"Verified release copy mismatch: {name}")
    backup = None
    if official.exists():
        backup = Path(tempfile.mkdtemp(prefix="previous-release-", dir=LOCAL_BUILD_DIR))
        backup.rmdir()  # Empty folder created by this operation only.
        official.rename(backup)
    try:
        prepared.rename(official)
    except OSError:
        if backup:
            backup.rename(official)
        raise
    print(f"Verified release promoted: {official}")
    if backup:
        print(f"Previous set preserved: {backup}")


def main() -> int:
    global RELEASE_DIR, APP_EXE
    args = parse_args()
    verify_source_tree()
    signing_requested = args.sign or args.require_signature
    if signing_requested and (args.skip_pyinstaller or args.skip_tests):
        raise SystemExit("Signed builds must rebuild current sources and run regression tests.")
    app_version = read_app_version()
    if signing_requested:
        ensure_version_not_reused(app_version)
        require_signing_configuration()
    if not args.skip_pyinstaller or not args.skip_installer:
        ensure_app_not_running()
    # Refuse before rebuilding/signing existing official outputs. Unique staging
    # prevents leftovers from another version or optional launcher contaminating a set.
    if signing_requested and not args.skip_installer:
        for name in installer_filenames(app_version):
            ensure_output_available(ROOT / "release" / name, args.overwrite)
    staging_root = DIST_DIR / "packaging"
    staging_root.mkdir(parents=True, exist_ok=True)
    RELEASE_DIR = Path(tempfile.mkdtemp(prefix=f"v{app_version}-", dir=staging_root))
    APP_EXE = (DIST_DIR if signing_requested or args.skip_pyinstaller else RELEASE_DIR) / APP_EXE_NAME
    print(f"Build staging: {RELEASE_DIR}")
    run_static_checks(skip_ruff=args.skip_ruff, skip_tests=args.skip_tests)
    build_app(skip_pyinstaller=args.skip_pyinstaller, app_version=app_version)
    run([sys.executable, str(ROOT / "tools" / "verify_packaged_sources.py"), str(APP_EXE)])
    launcher_exe = build_launcher(skip_pyinstaller=False, app_version=app_version) if getattr(args, "build_launcher", False) else None
    if launcher_exe:
        run([sys.executable, str(ROOT / "tools" / "verify_packaged_sources.py"), str(launcher_exe), "--launcher"])

    if signing_requested:
        sign_artifact(APP_EXE, required=True)
        if launcher_exe:
            sign_artifact(launcher_exe, required=True)
    else:
        print("\nWARNING: Build artifacts are unsigned. Use --require-signature for a public release.")

    setup_exe = build_installer(args.skip_installer, app_version, args.overwrite)
    if setup_exe and signing_requested:
        sign_artifact(setup_exe, required=True)
    if setup_exe:
        public_setup = prepare_public_alias(app_version, setup_exe)
        if signing_requested:
            thumbprint = os.environ["FILEOPS_SIGN_CERT_SHA1"].replace(" ", "")
            run([find_signtool(), "verify", "/pa", "/all", "/v", str(public_setup)])
            run(authenticode_verification_command(public_setup, thumbprint))
    write_build_manifest(app_version, setup_exe, launcher_exe, signed=signing_requested)
    write_checksum_manifest(app_version, setup_exe, launcher_exe)
    if signing_requested and setup_exe:
        promote_verified_release(app_version, launcher_exe, overwrite=args.overwrite)
    print("\nBuild checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
