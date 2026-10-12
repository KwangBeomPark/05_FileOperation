"""Execute the actual Pascal engine on temporary fixtures, never a real installation."""
import ctypes
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt" and shutil.which("ISCC.exe"), "Windows/Inno required")
class InstallerMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="fileops-migration-fixtures-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name) / "한글 시험 폴더"
        cls.root.mkdir()
        result = subprocess.run(
            [shutil.which("ISCC.exe"), "/Q", f"/O{cls.root}", f"/DFixtureRoot={cls.root}",
             f"/DMigrationInclude={ROOT / 'installer' / 'legacy_migration.iss'}",
             str(ROOT / "tools" / "fixtures" / "installer_migration.iss")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        if os.environ.get("FILEOPS_RUN_MIGRATION_FIXTURE") != "1":
            raise unittest.SkipTest("Unsigned fixture execution skipped by default to prevent Windows Security / Application Control popups (set FILEOPS_RUN_MIGRATION_FIXTURE=1 to enable)")
        cls.installer = cls.root / "migration_fixture.exe"
        probe = cls.root / "runtime_probe"
        probe.mkdir()
        try:
            result = subprocess.run(
                [str(cls.installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                 "/Case=runtime_probe", f"/LOG={probe / 'fixture.log'}"],
                capture_output=True, timeout=30,
            )
        except OSError as exc:
            if getattr(exc, "winerror", None) == 4551:
                raise unittest.SkipTest("Application Control (WinError 4551) blocks unsigned fixture execution; native migration remains unverified") from exc
            raise
        if result.returncode:
            raise unittest.SkipTest("Windows Security or Application Control prevented unsigned fixture execution; native migration remains unverified")

    def setUp(self):
        self.case = self.root / self._testMethodName
        self.old = self.case / "IntegratedDataTool"
        self.new = self.case / "Programs" / "FileOps"
        self.old.mkdir(parents=True)
        self.old_program = self.old / "IntegratedDataTool.exe"
        self.old_program.write_bytes(b"old fixture program")

    def settings(self):
        folder = self.old / "UserSetting"
        (folder / "logs").mkdir(parents=True)
        (folder / "settings.json").write_bytes(b'{"language":"ko","github_token":"enc:fixture"}')
        (folder / "logs" / "기록.log").write_bytes("예약 기록".encode())
        return folder

    def run_migration(self, scenario="normal"):
        result = subprocess.run(
            [str(self.installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/Case={self.case.name}", f"/Scenario={scenario}", f"/LOG={self.case / 'fixture.log'}"],
            timeout=30, capture_output=True,
        )
        log = self.case / "fixture.log"
        self.assertEqual(result.returncode, 0, log.read_text(encoding="utf-8", errors="replace") if log.exists() else repr(result))
        return (self.case / "outcome.txt").read_text()

    def test_verified_copy_removes_old_program_and_settings(self):
        original = self.settings()
        snapshot = {str(p.relative_to(original)): p.read_bytes() for p in original.rglob('*') if p.is_file()}
        self.assertEqual(self.run_migration(), "ok")
        for name, content in snapshot.items():
            self.assertEqual((self.new / "UserSetting" / name).read_bytes(), content)
        self.assertFalse(self.old.exists())

    def test_root_legacy_json_is_copied_as_settings_json(self):
        content = b'{"sync_groups":[],"sender_password":"enc:unchanged"}'
        (self.old / "setting_integrated.json").write_bytes(content)
        self.assertEqual(self.run_migration(), "ok")
        self.assertEqual((self.new / "UserSetting" / "settings.json").read_bytes(), content)
        self.assertFalse(self.old.exists())

    def test_existing_new_settings_are_not_overwritten(self):
        original = self.settings()
        current = self.new / "UserSetting" / "settings.json"
        current.parent.mkdir(parents=True)
        current.write_bytes(b"new settings")
        self.assertIn("conflict", self.run_migration())
        self.assertEqual(current.read_bytes(), b"new settings")
        self.assertTrue(self.old_program.exists())
        self.assertTrue((original / "settings.json").exists())

    def test_unknown_old_files_are_retained(self):
        self.settings()
        unknown = self.old / "업무.xlsx"
        unknown.write_bytes(b"unrelated document")
        self.assertIn("retained", self.run_migration())
        self.assertEqual(unknown.read_bytes(), b"unrelated document")
        self.assertFalse(self.old_program.exists())
        self.assertFalse((self.old / "UserSetting").exists())

    def test_payload_failure_does_not_delete_source_or_activate_settings(self):
        self.settings()
        self.assertIn("payload failure", self.run_migration("before_payload_failure"))
        self.assertTrue(self.old_program.exists())
        self.assertTrue((self.old / "UserSetting" / "settings.json").exists())
        self.assertFalse((self.new / "UserSetting" / "settings.json").exists())

    def test_tampered_staging_is_not_activated(self):
        self.settings()
        self.assertIn("changed", self.run_migration("stage_tamper"))
        self.assertTrue(self.old_program.exists())
        self.assertFalse((self.new / "UserSetting").exists())

    def test_settings_created_during_copy_are_not_overwritten(self):
        self.settings()
        self.assertIn("conflict", self.run_migration("target_race"))
        self.assertEqual((self.new / "UserSetting" / "settings.json").read_bytes(), b"new settings appeared")
        self.assertTrue(self.old_program.exists())

    def test_changed_source_is_not_deleted(self):
        self.settings()
        self.assertIn("changed", self.run_migration("source_tamper"))
        self.assertTrue(self.old_program.exists())
        self.assertEqual((self.old / "UserSetting" / "settings.json").read_bytes(), b"changed old settings")

    def test_changed_destination_does_not_delete_original(self):
        self.settings()
        self.assertIn("changed", self.run_migration("target_tamper"))
        self.assertTrue(self.old_program.exists())
        self.assertTrue((self.old / "UserSetting" / "settings.json").exists())

    def test_changed_old_program_blocks_cleanup(self):
        self.settings()
        self.assertIn("changed", self.run_migration("program_tamper"))
        self.assertTrue((self.old / "UserSetting" / "settings.json").exists())
        self.assertEqual(self.old_program.read_bytes(), b"changed old program")

    def test_multiple_legacy_folders_are_not_chosen_arbitrarily(self):
        self.settings()
        other = self.case / "App005_FileOps" / "UserSetting"
        other.mkdir(parents=True)
        (other / "settings.json").write_bytes(b"another config")
        self.assertIn("multiple", self.run_migration())
        self.assertTrue(self.old_program.exists())
        self.assertFalse(self.new.exists())

    def test_uninstaller_removed_only_for_owned_install(self):
        self.settings()
        (self.old / "unins000.exe").write_bytes(b"owned uninstaller")
        (self.old / "unins000.dat").write_bytes(b"owned metadata")
        self.assertEqual(self.run_migration("owned_uninstaller"), "ok")
        self.assertFalse(self.old.exists())

    def test_unowned_uninstaller_is_retained(self):
        self.settings()
        metadata = self.old / "unins000.dat"
        metadata.write_bytes(b"unowned metadata")
        self.assertIn("retained", self.run_migration())
        self.assertTrue(metadata.exists())

    def test_locked_settings_abort_without_deletion(self):
        config = self.settings() / "settings.json"
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(config), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            self.assertNotEqual(self.run_migration(), "ok")
            self.assertTrue(self.old_program.exists())
        finally:
            kernel.CloseHandle(handle)
        self.assertTrue(config.exists())

    def test_junction_settings_are_rejected_and_external_files_untouched(self):
        outside = self.case / "external"
        outside.mkdir()
        document = outside / "settings.json"
        document.write_bytes(b"outside data")
        junction = self.old / "UserSetting"
        result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        try:
            self.assertIn("unsafe", self.run_migration())
            self.assertEqual(document.read_bytes(), b"outside data")
            self.assertTrue(self.old_program.exists())
        finally:
            # rmdir removes only this exact junction, never its external contents.
            os.rmdir(junction)


if __name__ == "__main__":
    unittest.main()
