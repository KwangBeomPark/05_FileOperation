import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox

from src.core.backup_recovery import backup_directory, list_backup_entries, restore_backup_files
from src.ui.backup_recovery_dialog import BackupRecoveryDialog


class FakeConfig:
    def get(self, _key, default=None):
        return default


class BackupRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _write(path: str, content: bytes) -> None:
        with open(path, "wb") as file:
            file.write(content)

    def test_listing_previews_regular_files_without_following_links(self):
        with tempfile.TemporaryDirectory() as source_folder:
            backup_folder = backup_directory(source_folder)
            os.makedirs(backup_folder)
            older = os.path.join(backup_folder, "older.pdf")
            newer = os.path.join(backup_folder, "newer.pdf")
            self._write(older, b"old")
            self._write(newer, b"newer")
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))

            entries = list_backup_entries(source_folder)

            self.assertEqual([entry.file_name for entry in entries], ["newer.pdf", "older.pdf"])
            self.assertEqual(entries[0].size, 5)
            self.assertEqual(entries[0].restore_target, os.path.join(source_folder, "newer.pdf"))

    def test_restore_never_overwrites_existing_source(self):
        with tempfile.TemporaryDirectory() as source_folder:
            backup_folder = backup_directory(source_folder)
            os.makedirs(backup_folder)
            backup_file = os.path.join(backup_folder, "document.pdf")
            existing_file = os.path.join(source_folder, "document.pdf")
            self._write(backup_file, b"backup")
            self._write(existing_file, b"existing")

            result = restore_backup_files(source_folder, [backup_file])[0]

            self.assertTrue(result.success)
            self.assertEqual(result.restored_path, os.path.join(source_folder, "document_restored_1.pdf"))
            self.assertFalse(os.path.exists(backup_file))
            with open(existing_file, "rb") as file:
                self.assertEqual(file.read(), b"existing")
            with open(result.restored_path, "rb") as file:
                self.assertEqual(file.read(), b"backup")

    def test_restore_rejects_files_outside_expected_backup_folder(self):
        with tempfile.TemporaryDirectory() as source_folder:
            outside_file = os.path.join(source_folder, "outside.pdf")
            self._write(outside_file, b"keep")

            result = restore_backup_files(source_folder, [outside_file])[0]

            self.assertFalse(result.success)
            self.assertIn("outside", result.error)
            self.assertTrue(os.path.exists(outside_file))

    def test_failed_move_leaves_backup_file_in_place(self):
        with tempfile.TemporaryDirectory() as source_folder:
            backup_folder = backup_directory(source_folder)
            os.makedirs(backup_folder)
            backup_file = os.path.join(backup_folder, "locked.pdf")
            self._write(backup_file, b"locked")

            with patch("src.core.backup_recovery.shutil.move", side_effect=OSError("blocked")):
                result = restore_backup_files(source_folder, [backup_file])[0]

            self.assertFalse(result.success)
            self.assertEqual(result.error, "blocked")
            self.assertTrue(os.path.exists(backup_file))

    def test_multiple_restore_results_keep_processing_after_failure(self):
        with tempfile.TemporaryDirectory() as source_folder:
            backup_folder = backup_directory(source_folder)
            os.makedirs(backup_folder)
            missing = os.path.join(backup_folder, "missing.pdf")
            valid = os.path.join(backup_folder, "valid.pdf")
            self._write(valid, b"valid")

            results = restore_backup_files(source_folder, [missing, valid])

            self.assertFalse(results[0].success)
            self.assertTrue(results[1].success)
            self.assertTrue(os.path.exists(os.path.join(source_folder, "valid.pdf")))

    def test_dialog_previews_backup_and_restore_confirmation_defaults_to_no(self):
        with tempfile.TemporaryDirectory() as source_folder:
            backup_folder = backup_directory(source_folder)
            os.makedirs(backup_folder)
            backup_file = os.path.join(backup_folder, "preview.pdf")
            self._write(backup_file, b"preview")
            dialog = BackupRecoveryDialog(FakeConfig(), source_folder)
            dialog.table.selectRow(0)

            with patch(
                "src.ui.backup_recovery_dialog.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ) as question:
                dialog.restore_selected()

            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertTrue(dialog.restore_button.isEnabled())
            self.assertTrue(os.path.exists(backup_file))
            self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.No)
            dialog.close()


if __name__ == "__main__":
    unittest.main()
