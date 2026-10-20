import os
import subprocess
import sys
import unittest
from ctypes import wintypes
from unittest.mock import MagicMock, patch

from scripts.release import (
    ROOT,
    check_git_publish_readiness,
    find_code_signing_cert,
    is_admin,
    main,
    read_app_version,
    run_as_admin,
    run_release_pipeline,
    run_verify_only,
    verify_release_artifacts,
)


class ReleaseScriptTests(unittest.TestCase):
    def test_read_app_version_matches_pattern_and_version_file(self):
        version = read_app_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        version_content = (ROOT / "src" / "version.py").read_text(encoding="utf-8")
        self.assertIn(f'APP_VERSION = "{version}"', version_content)

    def test_is_admin_callable(self):
        admin = is_admin()
        self.assertIsInstance(admin, bool)

    def test_root_directory_validity(self):
        self.assertTrue((ROOT / "src").is_dir())
        self.assertTrue((ROOT / "scripts").is_dir())
        self.assertTrue((ROOT / "scripts" / "release.py").is_file())
        self.assertTrue((ROOT / "scripts" / "sign.ps1").is_file())

    def test_script_standalone_cli_execution_with_help(self):
        # Must execute cleanly as a standalone subprocess without sys.path import errors
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "release.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("FileOps Hub One-Click Release Automation Tool", proc.stdout)

    def test_verify_only_invokes_publish_release_with_verify_only_flag(self):
        with patch("scripts.release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ret = run_verify_only()
            self.assertEqual(ret, 0)
            mock_run.assert_called_once()
            called_args = mock_run.call_args[0][0]
            self.assertIn("--verify-only", called_args)

    def test_find_code_signing_cert_returns_none_on_multiple_or_empty(self):
        with patch("scripts.release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="   \n")
            cert = find_code_signing_cert()
            self.assertIsNone(cert)

    def test_find_code_signing_cert_handles_none_stdout(self):
        with patch("scripts.release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=None)
            cert = find_code_signing_cert()
            self.assertIsNone(cert)

    def _setup_mock_shellexec(self, mock_shell):
        def _set_hprocess(sei_ref):
            sei_ref._obj.hProcess = wintypes.HANDLE(0x1234)
            return 1
        mock_shell.side_effect = _set_hprocess

    def test_run_as_admin_handles_declined_elevation(self):
        with patch("ctypes.windll.shell32.ShellExecuteExW", return_value=0):
            ret = run_as_admin(["--skip-tests"])
            self.assertEqual(ret, 1)

    def test_run_as_admin_handles_wait_failure(self):
        with patch("ctypes.windll.shell32.ShellExecuteExW") as mock_shell, \
             patch("ctypes.windll.kernel32.WaitForSingleObject", return_value=0xFFFFFFFF) as mock_wait, \
             patch("ctypes.windll.kernel32.CloseHandle") as mock_close:
            self._setup_mock_shellexec(mock_shell)
            ret = run_as_admin(["--skip-tests"])
            self.assertEqual(ret, 1)
            mock_wait.assert_called_once()
            mock_close.assert_called_once_with(0x1234)

    def test_run_as_admin_handles_get_exit_code_failure(self):
        with patch("ctypes.windll.shell32.ShellExecuteExW") as mock_shell, \
             patch("ctypes.windll.kernel32.WaitForSingleObject", return_value=0) as mock_wait, \
             patch("ctypes.windll.kernel32.GetExitCodeProcess", return_value=0) as mock_get_code, \
             patch("ctypes.windll.kernel32.CloseHandle") as mock_close:
            self._setup_mock_shellexec(mock_shell)
            ret = run_as_admin(["--skip-tests"])
            self.assertEqual(ret, 1)
            mock_wait.assert_called_once()
            mock_get_code.assert_called_once()
            mock_close.assert_called_once_with(0x1234)

    def test_run_as_admin_propagates_child_exit_code(self):
        def mock_get_exit_code(h_proc, code_ref):
            code_ref._obj.value = 42
            return 1

        with patch("ctypes.windll.shell32.ShellExecuteExW") as mock_shell, \
             patch("ctypes.windll.kernel32.WaitForSingleObject", return_value=0), \
             patch("ctypes.windll.kernel32.GetExitCodeProcess", side_effect=mock_get_exit_code), \
             patch("ctypes.windll.kernel32.CloseHandle") as mock_close:
            self._setup_mock_shellexec(mock_shell)
            ret = run_as_admin(["--skip-tests"])
            self.assertEqual(ret, 42)
            mock_close.assert_called_once_with(0x1234)

    def test_run_as_admin_propagates_env_cert_and_elevated_flag(self):
        captured_params = []

        def mock_shellexec(sei_ref):
            captured_params.append(sei_ref._obj.lpParameters)
            sei_ref._obj.hProcess = wintypes.HANDLE(0x1234)
            return 1

        with patch("ctypes.windll.shell32.ShellExecuteExW", side_effect=mock_shellexec), \
             patch("ctypes.windll.kernel32.WaitForSingleObject", return_value=0), \
             patch("ctypes.windll.kernel32.GetExitCodeProcess", return_value=1), \
             patch("ctypes.windll.kernel32.CloseHandle"), \
             patch.dict(os.environ, {"FILEOPS_SIGN_CERT_SHA1": "MOCK_SHA1_THUMB"}):
            run_as_admin(["--skip-tests"])
            self.assertTrue(len(captured_params) > 0)
            self.assertIn("MOCK_SHA1_THUMB", captured_params[0])
            self.assertIn("--_elevated", captured_params[0])

    def test_run_as_admin_does_not_override_explicit_cert_equals_syntax(self):
        captured_params = []

        def mock_shellexec(sei_ref):
            captured_params.append(sei_ref._obj.lpParameters)
            sei_ref._obj.hProcess = wintypes.HANDLE(0x1234)
            return 1

        with patch("ctypes.windll.shell32.ShellExecuteExW", side_effect=mock_shellexec), \
             patch("ctypes.windll.kernel32.WaitForSingleObject", return_value=0), \
             patch("ctypes.windll.kernel32.GetExitCodeProcess", return_value=1), \
             patch("ctypes.windll.kernel32.CloseHandle"), \
             patch.dict(os.environ, {"FILEOPS_SIGN_CERT_SHA1": "ENV_THUMB"}):
            run_as_admin(["--cert-thumbprint=EXPLICIT_THUMB"])
            self.assertTrue(len(captured_params) > 0)
            self.assertIn("--cert-thumbprint=EXPLICIT_THUMB", captured_params[0])
            self.assertNotIn("ENV_THUMB", captured_params[0])

    def test_main_verify_only_bypasses_uac_and_prompts(self):
        with patch("sys.argv", ["release.py", "--verify-only"]), \
             patch("scripts.release.run_verify_only", return_value=0) as mock_verify, \
             patch("scripts.release.is_admin") as mock_admin:
            ret = main()
            self.assertEqual(ret, 0)
            mock_verify.assert_called_once()
            mock_admin.assert_not_called()

    def test_check_git_publish_readiness_rejects_dirty_tree(self):
        with patch("scripts.release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=" M src/version.py\n")
            ready = check_git_publish_readiness()
            self.assertFalse(ready)

    def test_check_git_publish_readiness_auto_merges_non_main_branch(self):
        def mock_git(cmd, **kwargs):
            if cmd == ["git", "status", "--porcelain"]:
                return MagicMock(stdout="")
            if cmd == ["git", "branch", "--show-current"]:
                return MagicMock(stdout="release/v1.5.0\n")
            if cmd == ["git", "checkout", "main"]:
                return MagicMock(returncode=0)
            if cmd == ["git", "merge", "release/v1.5.0"]:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0, stdout="")

        with patch("scripts.release.subprocess.run", side_effect=mock_git):
            ready = check_git_publish_readiness()
            self.assertTrue(ready)

    def test_run_release_pipeline_publish_flag_handling(self):
        with patch("scripts.release.read_app_version", return_value="1.5.0"), \
             patch("scripts.release.run_unit_tests", return_value=True), \
             patch("scripts.release.ensure_smart_card_service", return_value=True), \
             patch("scripts.release.find_code_signing_cert", return_value="THUMB123"), \
             patch("scripts.release.check_git_publish_readiness", return_value=True), \
             patch("scripts.release.verify_release_artifacts", return_value=True), \
             patch("scripts.release.subprocess.run") as mock_run, \
             patch("scripts.release.os.startfile", create=True):
            mock_run.return_value = MagicMock(returncode=0)

            # Test 1: Without --publish, sign.ps1 should NOT receive -Publish
            run_release_pipeline(skip_tests=True, publish=False, cert_thumbprint="THUMB123")
            args_without = mock_run.call_args[0][0]
            self.assertNotIn("-Publish", args_without)

            # Test 2: With --publish, sign.ps1 SHOULD receive -Publish
            run_release_pipeline(skip_tests=True, publish=True, cert_thumbprint="THUMB123")
            args_with = mock_run.call_args[0][0]
            self.assertIn("-Publish", args_with)

    def test_main_publish_rejects_dirty_or_non_main_before_uac(self):
        with patch("sys.argv", ["release.py", "--publish"]), \
             patch("scripts.release.check_git_publish_readiness", return_value=False) as mock_ready, \
             patch("scripts.release.is_admin") as mock_admin:
            ret = main()
            self.assertEqual(ret, 1)
            mock_ready.assert_called_once()
            mock_admin.assert_not_called()

    def test_verify_release_artifacts_success(self):
        with patch("scripts.release.RELEASE_DIR") as mock_dir, \
             patch("scripts.build_all.validate_release_payload", return_value=({"version": "1.5.0", "authenticode_verified": True}, ["path1", "path2"])):
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            mock_file.stat.return_value.st_size = 10 * 1024 * 1024
            mock_dir.__truediv__.return_value = mock_file
            ok = verify_release_artifacts("1.5.0")
            self.assertTrue(ok)

    def test_verify_release_artifacts_handles_missing_files(self):
        with patch("scripts.release.RELEASE_DIR") as mock_dir:
            mock_dir.__truediv__.return_value.exists.return_value = False
            ok = verify_release_artifacts("1.5.0")
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
