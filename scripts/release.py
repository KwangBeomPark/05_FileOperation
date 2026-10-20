#!/usr/bin/env python3
"""
FileOps Hub One-Click Release & Digital Signing Automation Script
Inspired by Enterprise PL Suite Release Pipeline (Project 04 Data Refinery).

Usage:
    python scripts/release.py [--skip-tests] [--overwrite] [--publish] [--verify-only] [--cert-thumbprint SHA1]

Features:
    1. Automatic UAC Elevation: Prompts for Administrator privileges if not already elevated,
       waits with responsive cancellation, and propagates the real exit code.
    2. Environment Verification: Checks Smart Card service (SCardSvr), SignTool, and Code Signing Certificate.
    3. Pre-flight Quality Gate: Runs full regression test suite (unittest discover) before building.
    4. Authenticode Signing & Packaging: Executes build_all.py with digital signature requirement.
    5. Clean Worktree & Branch Check: Enforces clean Git status and main branch only when --publish is passed.
    6. Post-Release Verification: Validates complete signed set, SHA-256 checksums, and build manifests.
    7. Elevation Safety: Auto-passes parent environment certificate and keeps terminal open only on UAC prompt.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRIPTS_DIR = ROOT / "scripts"
RELEASE_DIR = ROOT / "release"
VERSION_FILE = ROOT / "src" / "version.py"
SIGN_PS1 = SCRIPTS_DIR / "sign.ps1"
PUBLISH_PY = SCRIPTS_DIR / "publish_release.py"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_admin() -> bool:
    """Check if the current process is running with Administrator privileges."""
    if not is_windows():
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def run_as_admin(argv: list[str]) -> int:
    """Re-launch the script in an elevated Administrator prompt (UAC) and wait for exit code."""
    script_path = str(Path(__file__).resolve())
    
    # Propagate parent environment certificate if not already in argv
    forward_argv = list(argv)
    has_cert_arg = any(a == "--cert-thumbprint" or a.startswith("--cert-thumbprint=") for a in forward_argv)
    if not has_cert_arg:
        env_cert = os.environ.get("FILEOPS_SIGN_CERT_SHA1")
        if env_cert:
            forward_argv.extend(["--cert-thumbprint", env_cert])

    # Mark the child process as elevated so it knows to pause before closing
    if "--_elevated" not in forward_argv:
        forward_argv.append("--_elevated")

    cmd_args = subprocess.list2cmdline([script_path, *forward_argv])

    print("=" * 70)
    print(" [UAC ELEVATION] Administrator privileges required for Digital Signing.")
    print(" Requesting elevation via Windows User Account Control...")
    print("=" * 70)

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = sys.executable
    sei.lpParameters = cmd_args
    sei.lpDirectory = str(ROOT)
    sei.nShow = 1  # SW_SHOWNORMAL

    success = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
    if not success or not sei.hProcess:
        err = ctypes.GetLastError()
        print(f"!! Elevation was declined or failed (Error Code: {err}).")
        return 1

    h_process = sei.hProcess
    try:
        # Responsive wait loop (250ms chunks) to permit clean Ctrl+C interruption
        WAIT_OBJECT_0 = 0x00000000
        WAIT_TIMEOUT = 0x00000102
        while True:
            wait_res = ctypes.windll.kernel32.WaitForSingleObject(h_process, wintypes.DWORD(250))
            if wait_res == WAIT_OBJECT_0:
                break
            elif wait_res == WAIT_TIMEOUT:
                continue
            else:
                err = ctypes.GetLastError()
                print(f"!! Waiting for elevated process failed (Wait Result: {wait_res}, Error: {err}).")
                return 1

        exit_code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(h_process, ctypes.byref(exit_code)):
            err = ctypes.GetLastError()
            print(f"!! Failed to get elevated process exit code (Error: {err}).")
            return 1

        return int(exit_code.value)
    except KeyboardInterrupt:
        print("\n\nWait cancelled by user.")
        return 130
    finally:
        ctypes.windll.kernel32.CloseHandle(h_process)


def read_app_version() -> str:
    """Read the single source of truth version from src/version.py."""
    if not VERSION_FILE.exists():
        raise SystemExit(f"Error: Version file missing at {VERSION_FILE}")
    content = VERSION_FILE.read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\'](\d+(?:\.\d+)*)["\']', content, re.MULTILINE)
    if not match:
        raise SystemExit(f"Error: APP_VERSION not found in {VERSION_FILE}")
    return match.group(1)


def ensure_smart_card_service() -> bool:
    """Ensure the Windows Smart Card service (SCardSvr) is running."""
    if not is_windows():
        return True
    try:
        query_out = subprocess.check_output(
            ["sc", "query", "SCardSvr"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if "RUNNING" not in query_out:
            print(">> Starting Windows Smart Card service (SCardSvr)...")
            start_res = subprocess.run(
                ["net", "start", "SCardSvr"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            # Re-verify via sc query instead of relying on language-specific net start text
            query_after = subprocess.check_output(
                ["sc", "query", "SCardSvr"],
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if "RUNNING" in query_after:
                print(">> Smart Card service is now RUNNING.")
                return True
            else:
                print(f"!! Warning: SCardSvr is not in RUNNING state: {start_res.stderr.strip()}")
                return False
        return True
    except (OSError, subprocess.SubprocessError) as e:
        print(f"!! Warning: Error checking SCardSvr: {e}")
        return False


def find_code_signing_cert() -> str | None:
    """Detect available code-signing certificate thumbprint in Cert:\\CurrentUser\\My.

    Returns the thumbprint ONLY if exactly one valid certificate is found.
    If multiple certificates exist, returns None to avoid arbitrary selection.
    """
    ps_cmd = (
        "$now = Get-Date; "
        "$certs = @(Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert | "
        "Where-Object { $_.HasPrivateKey -and $_.NotBefore -le $now -and $_.NotAfter -gt $now -and $_.Subject -ne $_.Issuer }); "
        "if ($certs.Count -eq 1) { $certs[0].Thumbprint } else { '' }"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            cwd=str(ROOT),
        )
        thumbprint = (proc.stdout or "").strip()
        return thumbprint if thumbprint else None
    except (OSError, subprocess.SubprocessError) as e:
        print(f"!! Error inspecting certificate store: {e}")
        return None


def run_unit_tests() -> bool:
    """Run full test suite before packaging."""
    print("\n" + "=" * 70)
    print(" [PRE-FLIGHT] Executing full regression test suite...")
    print("=" * 70)
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py"]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8:replace"}
    res = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if res.returncode != 0:
        print(f"\n!! Test suite failed with exit code {res.returncode}.")
        return False
    print(">> All unit regression tests passed successfully!")
    return True


def check_git_publish_readiness() -> bool:
    """Ensure Git worktree is clean and branch is automatically merged/switched to main for publication."""
    print(">> Checking Git status for official publication...")
    try:
        # 1. Check for uncommitted changes first
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            cwd=str(ROOT),
        )
        dirty = [line for line in status_proc.stdout.splitlines() if not line.startswith("?? release/")]
        if dirty:
            print("!! [ERROR] Official publication requires a clean working tree.")
            print("   Uncommitted changes detected:")
            for line in dirty[:5]:
                print(f"     {line}")
            return False

        # 2. Check current branch and auto-merge/switch to main if needed
        branch_proc = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            cwd=str(ROOT),
        )
        current_branch = branch_proc.stdout.strip()
        if current_branch != "main":
            print(f">> [AUTO-SYNC] Current branch is '{current_branch}'.")
            print(">> [AUTO-SYNC] Automatically switching to 'main' and merging changes for release...")

            checkout_res = subprocess.run(["git", "checkout", "main"], cwd=str(ROOT), check=False)
            if checkout_res.returncode != 0:
                print("!! [ERROR] Failed to switch to 'main' branch.")
                return False

            merge_res = subprocess.run(["git", "merge", current_branch], cwd=str(ROOT), check=False)
            if merge_res.returncode != 0:
                print(f"!! [ERROR] Failed to merge '{current_branch}' into 'main'. Rolling back...")
                subprocess.run(["git", "merge", "--abort"], cwd=str(ROOT), check=False)
                subprocess.run(["git", "checkout", current_branch], cwd=str(ROOT), check=False)
                return False

            print(f">> [AUTO-SYNC] Successfully merged '{current_branch}' into 'main'!")

        print(">> Git repository is clean and on 'main' branch.")
        return True
    except (OSError, subprocess.SubprocessError) as e:
        print(f"!! [ERROR] Failed to verify Git repository readiness: {e}")
        return False


def run_verify_only() -> int:
    """Run explicit verification of existing release artifacts via publish_release.py."""
    print("\n" + "=" * 70)
    print(" [VERIFY-ONLY] Verifying published release artifacts...")
    print("=" * 70)
    cmd = [sys.executable, str(PUBLISH_PY), "--verify-only"]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8:replace"}
    res = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if res.returncode != 0:
        print(f"\n!! Verification failed with exit code {res.returncode}.")
        return res.returncode
    print(">> [SUCCESS] Release verification succeeded!")
    return 0


def verify_release_artifacts(version: str) -> bool:
    """Validate completeness, Authenticode signatures, and SHA-256 digests of artifacts."""
    installer_name = f"App05_FileOps_Setup_v{version}.exe"
    installer_path = RELEASE_DIR / installer_name
    sums_file = RELEASE_DIR / "SHA256SUMS.txt"
    manifest_file = RELEASE_DIR / "build-manifest.json"

    print("\n" + "=" * 70)
    print(" [RELEASE ARTIFACTS VERIFICATION]")
    print("=" * 70)

    if not installer_path.exists():
        print(f" !! [FAIL] Expected installer artifact not found: {installer_path}")
        return False

    if not sums_file.exists():
        print(f" !! [FAIL] Expected checksums file not found: {sums_file}")
        return False

    if not manifest_file.exists():
        print(f" !! [FAIL] Expected manifest file not found: {manifest_file}")
        return False

    # Reuse canonical validate_release_payload from build_all
    try:
        from scripts.build_all import validate_release_payload
        manifest, paths = validate_release_payload(RELEASE_DIR, version)
        print(f" [OK] Validated release payload ({len(paths)} artifacts verified).")
        print(f" [OK] Authenticode Signature: {manifest.get('authenticode_verified')}")
        print(f" [OK] Build Manifest: {manifest_file.name} (v{manifest.get('version')})")
        print(f" [OK] Checksums File:  {sums_file.name}")
    except Exception as e:  # noqa: BLE001
        print(f" !! [FAIL] Release payload validation failed: {e}")
        return False

    size_mb = installer_path.stat().st_size / (1024 * 1024)
    print(f" [OK] Installer: {installer_name} ({size_mb:.2f} MB)")
    return True


def run_release_pipeline(
    skip_tests: bool = False,
    overwrite: bool = False,
    publish: bool = False,
    cert_thumbprint: str | None = None,
) -> int:
    """Execute the complete build, sign, and publication pipeline."""
    version = read_app_version()
    print("=" * 70)
    print(f" FileOps Hub One-Click Release Pipeline - v{version}")
    print(f" Working Directory: {ROOT}")
    print(f" Python Executable: {sys.executable}")
    print(f" Target Mode:      {'BUILD, SIGN & PUBLISH' if publish else 'BUILD & SIGN (Local Release)'}")
    print("=" * 70)

    # 1. Release notes check
    rel_notes = ROOT / "docs" / f"RELEASE_NOTES_v{version}.md"
    if not rel_notes.exists():
        print(f"!! Warning: Release notes file not found: {rel_notes}")
        choice = input(">> Continue without dedicated release notes? (y/N): ").strip().lower()
        if choice != "y":
            print("Aborted.")
            return 1
    else:
        print(f">> Found release notes: {rel_notes.name}")

    # 2. Git Pre-flight Check (Fail-fast when publish is requested)
    if publish and not check_git_publish_readiness():
        return 1

    # 3. Quality Gate: Unit Tests
    if not skip_tests:
        if not run_unit_tests():
            print("!! Release cancelled due to test failures.")
            return 1
    else:
        print(">> Unit tests skipped as requested.")

    # 4. Environment & Service Check
    ensure_smart_card_service()

    # 5. Code Signing Certificate Detection
    if not cert_thumbprint:
        cert_thumbprint = os.environ.get("FILEOPS_SIGN_CERT_SHA1") or find_code_signing_cert()

    if cert_thumbprint:
        print(f">> Using Code Signing Certificate: {cert_thumbprint}")
    else:
        print("!! WARNING: No single code-signing certificate could be uniquely detected in Cert:\\CurrentUser\\My.")
        print("   If multiple certificates exist, pass --cert-thumbprint <SHA1> explicitly.")
        print("   If using a hardware token/dongle (SimplySign, SafeNet), ensure it is plugged in.")
        choice = input(">> Proceed anyway? (Build may fail if signing is mandatory) (y/N): ").strip().lower()
        if choice != "y":
            print("Aborted.")
            return 1

    # 6. Execute Signing & Packaging via sign.ps1
    print("\n" + "=" * 70)
    print(" [BUILD & SIGN] Invoking PowerShell Sign & Packaging Engine...")
    print("=" * 70)

    ps_args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SIGN_PS1),
        "-Python",
        sys.executable,
    ]
    if publish:
        ps_args.append("-Publish")
    if overwrite:
        ps_args.append("-Overwrite")
    if cert_thumbprint:
        ps_args.extend(["-CertificateThumbprint", cert_thumbprint])

    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8:replace"}
    build_res = subprocess.run(ps_args, cwd=str(ROOT), env=env, check=False)
    if build_res.returncode != 0:
        print(f"\n!! Release pipeline failed with exit code {build_res.returncode}.")
        return build_res.returncode

    # 7. Post-release Artifact Verification
    if not verify_release_artifacts(version):
        return 1

    print("\n" + "=" * 70)
    action_text = "built, signed, and published to GitHub" if publish else "built and digitally signed locally"
    print(f" [SUCCESS] FileOps Hub v{version} successfully {action_text}!")
    print(f" Location: {RELEASE_DIR}")
    print("=" * 70)

    # 8. Open Release Directory
    if is_windows():
        try:
            os.startfile(str(RELEASE_DIR))
        except OSError:
            pass

    return 0


def main() -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        description="FileOps Hub One-Click Release Automation Tool",
        allow_abbrev=False,
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip running regression unit tests")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting existing versioned release artifacts")
    parser.add_argument("--publish", action="store_true", help="Publish release to GitHub and create Git tag (requires clean main branch)")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing release publication without rebuilding")
    parser.add_argument("--cert-thumbprint", type=str, default=None, help="Explicit SHA1 thumbprint of code signing certificate")
    parser.add_argument("--_elevated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    # Step 0: Verification-only does not require elevation or user prompts
    if args.verify_only:
        return run_verify_only()

    # Step 1: Pre-flight Git check before UAC elevation (Fail-fast before prompting)
    if args.publish and not check_git_publish_readiness():
        return 1

    # Step 2: Ensure Administrator Privileges (Auto-Elevation with child process exit code propagation)
    if not is_admin():
        passed_argv = [a for a in sys.argv[1:] if a != "--_elevated"]
        return run_as_admin(passed_argv)

    # Elevated Execution
    is_elevated_window = args._elevated
    try:
        ret = run_release_pipeline(
            skip_tests=args.skip_tests,
            overwrite=args.overwrite,
            publish=args.publish,
            cert_thumbprint=args.cert_thumbprint,
        )
        if is_elevated_window:
            print("\nPress Enter to close this window...")
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                pass
        return ret
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        return 130
    except (Exception, SystemExit) as ex:  # noqa: BLE001
        if isinstance(ex, SystemExit):
            code = 0 if ex.code is None else (ex.code if isinstance(ex.code, int) else 1)
            if code != 0:
                print(f"\n!! Release exited: {ex}")
            if is_elevated_window:
                print("\nPress Enter to close this window...")
                try:
                    input()
                except (KeyboardInterrupt, EOFError):
                    pass
            return code

        print(f"\n!! Unexpected release failure: {ex}")
        import traceback
        traceback.print_exc()
        if is_elevated_window:
            print("\nPress Enter to close this window...")
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
