"""Regression checks for infrastructure failure-reporting boundaries."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core import backup_recovery, preflight, windows_ocr


class InfrastructureBoundaryTests(unittest.TestCase):
    def test_manifest_failure_is_returned_to_caller(self):
        with patch.object(backup_recovery.os, "makedirs", side_effect=RuntimeError("manifest failed")):
            self.assertEqual(backup_recovery._append_manifest_event("unused", {}), (False, "manifest failed"))

    def test_restore_continues_after_unexpected_move_failure(self):
        with tempfile.TemporaryDirectory() as root:
            backup = Path(root) / backup_recovery.BACKUP_FOLDER_NAME
            backup.mkdir()
            first, second = backup / "first.txt", backup / "second.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            real_move = backup_recovery.shutil.move

            def move(source, target):
                if Path(source) == first:
                    raise RuntimeError("move failed")
                return real_move(source, target)

            with patch.object(backup_recovery.shutil, "move", side_effect=move):
                results = backup_recovery.restore_backup_files(root, [str(first), str(second)])
            self.assertFalse(results[0].success)
            self.assertIn("move failed", results[0].error)
            self.assertTrue(first.exists())
            self.assertTrue(results[1].success)
            self.assertEqual((Path(root) / "second.txt").read_text(encoding="utf-8"), "second")

    def test_ocr_backend_failure_is_diagnostic(self):
        with patch.object(windows_ocr.sys, "platform", "win32"), \
             patch.object(windows_ocr, "_write_script", return_value="unused"), \
             patch.object(windows_ocr, "_run_powershell", side_effect=RuntimeError("backend failed")), \
             patch.object(Path, "unlink"):
            self.assertEqual(windows_ocr.windows_ocr_available(), (False, "backend failed"))

    def test_windows_ocr_preflight_reports_backend_failure(self):
        with patch.object(windows_ocr, "windows_ocr_available", side_effect=RuntimeError("backend failed")):
            self.assertEqual(preflight.check_windows_ocr(), (False, "backend failed"))


if __name__ == "__main__":
    unittest.main()
