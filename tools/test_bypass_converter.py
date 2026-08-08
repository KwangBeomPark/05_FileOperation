import os
import tempfile
import unittest
from unittest.mock import patch

from src.core.bypass_converter import BypassConverter
from src.core.task_contracts import SourceDisposition


class BypassConverterSafetyTests(unittest.TestCase):
    @staticmethod
    def _successful_pdf_conversion(_src, target, _extension):
        with open(target, "wb") as output:
            output.write(b"converted")
        return True, "ok"

    def test_default_keeps_source_after_verified_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.pdf")
            target = os.path.join(temp_dir, "source.zip")
            with open(source, "wb") as file:
                file.write(b"source")
            converter = BypassConverter()
            converter._convert_pdf = self._successful_pdf_conversion

            success, message = converter.convert_file(source, target, ".zip")

            self.assertTrue(success)
            self.assertEqual(message, "SOURCE_KEPT")
            self.assertTrue(os.path.exists(source))
            self.assertTrue(os.path.exists(target))

    def test_backup_moves_source_and_preserves_existing_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.pdf")
            target = os.path.join(temp_dir, "source.zip")
            backup_dir = os.path.join(temp_dir, "Original Backup")
            os.makedirs(backup_dir)
            with open(source, "wb") as file:
                file.write(b"new source")
            with open(os.path.join(backup_dir, "source.pdf"), "wb") as file:
                file.write(b"old source")
            converter = BypassConverter()
            converter._convert_pdf = self._successful_pdf_conversion

            success, message = converter.convert_file(
                source,
                target,
                ".zip",
                source_disposition=SourceDisposition.BACKUP,
            )

            self.assertTrue(success)
            self.assertFalse(os.path.exists(source))
            self.assertEqual(message, f"SOURCE_BACKED_UP|{os.path.join(backup_dir, 'source_1.pdf')}")
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "source.pdf")))
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "source_1.pdf")))

    def test_missing_output_never_moves_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.pdf")
            target = os.path.join(temp_dir, "missing.zip")
            with open(source, "wb") as file:
                file.write(b"source")
            converter = BypassConverter()
            converter._convert_pdf = lambda *_args: (True, "ok")

            success, message = converter.convert_file(
                source,
                target,
                ".zip",
                source_disposition=SourceDisposition.BACKUP,
            )

            self.assertFalse(success)
            self.assertTrue(message.startswith("OUTPUT_NOT_CREATED|"))
            self.assertTrue(os.path.exists(source))

    def test_backup_failure_is_reported_as_failure_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.pdf")
            target = os.path.join(temp_dir, "source.zip")
            with open(source, "wb") as file:
                file.write(b"source")
            converter = BypassConverter()
            converter._convert_pdf = self._successful_pdf_conversion

            with patch("src.core.bypass_converter.shutil.move", side_effect=OSError("blocked")):
                success, message = converter.convert_file(
                    source,
                    target,
                    ".zip",
                    source_disposition=SourceDisposition.BACKUP,
                )

            self.assertFalse(success)
            self.assertEqual(message, "SOURCE_BACKUP_FAILED|blocked")
            self.assertTrue(os.path.exists(source))

    def test_legacy_delete_flag_is_migrated_to_recoverable_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.pdf")
            target = os.path.join(temp_dir, "source.zip")
            with open(source, "wb") as file:
                file.write(b"source")
            converter = BypassConverter()
            converter._convert_pdf = self._successful_pdf_conversion

            success, message = converter.convert_file(source, target, ".zip", delete_original=True)

            self.assertTrue(success)
            self.assertTrue(message.startswith("SOURCE_BACKED_UP|"))
            self.assertFalse(os.path.exists(source))
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "Original Backup", "source.pdf")))

    def test_existing_target_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.pdf")
            target = os.path.join(temp_dir, "source.zip")
            with open(source, "wb") as file:
                file.write(b"source")
            with open(target, "wb") as file:
                file.write(b"existing")

            success, message = BypassConverter().convert_file(source, target, ".zip")

            self.assertFalse(success)
            self.assertEqual(message, f"TARGET_ALREADY_EXISTS|{target}")
            with open(target, "rb") as file:
                self.assertEqual(file.read(), b"existing")

    def test_same_source_and_target_is_rejected_before_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.pdf")
            with open(source, "wb") as file:
                file.write(b"source")

            success, message = BypassConverter().convert_file(source, source, ".pdf")

            self.assertFalse(success)
            self.assertTrue(message.startswith("SOURCE_TARGET_SAME|"))
            self.assertTrue(os.path.exists(source))


if __name__ == "__main__":
    unittest.main()
