import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from src.core.bypass_converter import BypassConverter
from src.core.task_contracts import SourceDisposition


class BypassConverterSafetyTests(unittest.TestCase):
    @staticmethod
    def _successful_pdf_conversion(_src, target, _extension):
        with open(target, "wb") as output:
            output.write(b"converted")
        return True, "ok"

    @staticmethod
    def _successful_xlsm_conversion(_src, target, _extension):
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types />")
            archive.writestr("xl/workbook.xml", "<workbook />")
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

    def test_manifest_failure_does_not_turn_completed_backup_into_source_loss(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "source.pdf")
            target = os.path.join(temp_dir, "source.zip")
            with open(source, "wb") as file:
                file.write(b"source")
            converter = BypassConverter()
            converter._convert_pdf = self._successful_pdf_conversion

            with patch(
                "src.core.bypass_converter.record_backup_move",
                return_value=(False, "manifest blocked"),
            ):
                success, message = converter.convert_file(
                    source,
                    target,
                    ".zip",
                    source_disposition=SourceDisposition.BACKUP,
                )

            self.assertTrue(success)
            self.assertTrue(message.startswith("SOURCE_BACKED_UP_MANIFEST_WARNING|"))
            self.assertFalse(os.path.exists(source))
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "Original Backup", "source.pdf")))

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

    def test_replace_removes_xlsx_only_after_valid_xlsm_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsm")
            with open(source, "wb") as file:
                file.write(b"source workbook")
            converter = BypassConverter()
            converter._convert_excel = self._successful_xlsm_conversion

            with patch("src.core.bypass_converter.send2trash", side_effect=os.remove):
                success, message = converter.convert_file(
                    source,
                    target,
                    ".xlsm",
                    source_disposition=SourceDisposition.REPLACE,
                )

            self.assertTrue(success)
            self.assertEqual(message, f"SOURCE_RECYCLED|{target}")
            self.assertFalse(os.path.exists(source))
            self.assertTrue(os.path.exists(target))

    def test_replace_keeps_source_when_output_format_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsm")
            with open(source, "wb") as file:
                file.write(b"source workbook")
            converter = BypassConverter()
            converter._convert_excel = self._successful_pdf_conversion

            success, message = converter.convert_file(
                source,
                target,
                ".xlsm",
                source_disposition=SourceDisposition.REPLACE,
            )

            self.assertFalse(success)
            self.assertTrue(message.startswith("OUTPUT_FORMAT_INVALID|"))
            self.assertTrue(os.path.exists(source))
            self.assertTrue(os.path.exists(target))

    def test_replace_keeps_source_when_source_changes_during_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsm")
            with open(source, "wb") as file:
                file.write(b"source workbook")

            def convert_and_change_source(src_path, target_path, extension):
                self._successful_xlsm_conversion(src_path, target_path, extension)
                with open(src_path, "ab") as source_file:
                    source_file.write(b" changed")
                return True, "ok"

            converter = BypassConverter()
            converter._convert_excel = convert_and_change_source
            success, message = converter.convert_file(
                source,
                target,
                ".xlsm",
                source_disposition=SourceDisposition.REPLACE,
            )

            self.assertFalse(success)
            self.assertTrue(message.startswith("SOURCE_CHANGED_DURING_CONVERSION|"))
            self.assertTrue(os.path.exists(source))
            self.assertTrue(os.path.exists(target))

    def test_replace_delete_failure_keeps_both_files_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsm")
            with open(source, "wb") as file:
                file.write(b"source workbook")
            converter = BypassConverter()
            converter._convert_excel = self._successful_xlsm_conversion

            with (
                patch("src.core.bypass_converter.send2trash", side_effect=OSError("no recycle bin")),
                patch("src.core.bypass_converter.os.remove", side_effect=PermissionError("blocked")),
            ):
                success, message = converter.convert_file(
                    source,
                    target,
                    ".xlsm",
                    source_disposition=SourceDisposition.REPLACE,
                )

            self.assertFalse(success)
            self.assertTrue(message.startswith("SOURCE_REPLACE_FAILED|"))
            self.assertTrue(os.path.exists(source))
            self.assertTrue(os.path.exists(target))

    def test_replace_permanently_deletes_when_recycle_bin_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsm")
            with open(source, "wb") as file:
                file.write(b"source workbook")
            converter = BypassConverter()
            converter._convert_excel = self._successful_xlsm_conversion

            with patch("src.core.bypass_converter.send2trash", side_effect=OSError("no recycle bin")):
                success, message = converter.convert_file(
                    source,
                    target,
                    ".xlsm",
                    source_disposition=SourceDisposition.REPLACE,
                )

            self.assertTrue(success)
            self.assertEqual(message, f"SOURCE_DELETED_FALLBACK|{target}|no recycle bin")
            self.assertFalse(os.path.exists(source))
            self.assertTrue(os.path.exists(target))

    def test_target_extension_mismatch_is_rejected_before_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsb")
            with open(source, "wb") as file:
                file.write(b"source workbook")

            success, message = BypassConverter().convert_file(source, target, ".xlsm")

            self.assertFalse(success)
            self.assertTrue(message.startswith("TARGET_EXTENSION_MISMATCH|"))
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(target))

    def test_invalid_target_extension_is_rejected_without_touching_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsm")
            with open(source, "wb") as file:
                file.write(b"source workbook")

            success, message = BypassConverter().convert_file(source, target, None)

            self.assertFalse(success)
            self.assertTrue(message.startswith("INVALID_TARGET_EXTENSION|"))
            self.assertTrue(os.path.exists(source))

    def test_recycle_warning_after_source_moved_is_reported_without_delete_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsm")
            with open(source, "wb") as file:
                file.write(b"source workbook")
            converter = BypassConverter()
            converter._convert_excel = self._successful_xlsm_conversion

            def recycle_then_warn(path):
                os.remove(path)
                raise OSError("late shell warning")

            with (
                patch("src.core.bypass_converter.send2trash", side_effect=recycle_then_warn),
                patch("src.core.bypass_converter.os.remove", wraps=os.remove) as remove,
            ):
                success, message = converter.convert_file(
                    source,
                    target,
                    ".xlsm",
                    source_disposition=SourceDisposition.REPLACE,
                )

            self.assertTrue(success)
            self.assertTrue(message.startswith("SOURCE_RECYCLED_WARNING|"))
            self.assertEqual(remove.call_count, 1)
            self.assertFalse(os.path.exists(source))


if __name__ == "__main__":
    unittest.main()
