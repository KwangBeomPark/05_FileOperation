import os
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QMessageBox

from src.core.task_contracts import BypassFileConfig, BypassRunConfig, EmlRunConfig, PdfRunConfig, SourceDisposition, SyncRunConfig, TaskValidationError
from src.ui.bypass_tab import BypassTab
from src.ui.eml_tab import EMLTab
from src.ui.pdf_tab import PDFTab
from src.ui.sync_tab import SyncTab


class TextValue:
    def __init__(self, value):
        self.value = value

    def text(self):
        return self.value


class CheckedValue:
    def __init__(self, value):
        self.value = value

    def isChecked(self):
        return self.value


class TableItem:
    def __init__(self, value):
        self.value = value

    def text(self):
        return self.value


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def rowCount(self):
        return len(self.rows)

    def item(self, row, column):
        return TableItem(self.rows[row][column])


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class TabContractTests(unittest.TestCase):
    def test_pdf_tab_builds_typed_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, "sample.pdf")
            output_dir = os.path.join(temp_dir, "out")
            with open(pdf_path, "wb") as file:
                file.write(b"%PDF-1.4\n")

            fake_tab = type("FakePDFTab", (), {})()
            fake_tab.selected_pdf_paths = [pdf_path]
            fake_tab.output_path_input = TextValue(output_dir)

            run_config = PDFTab.build_run_config(fake_tab)
            self.assertIsInstance(run_config, PdfRunConfig)
            self.assertEqual(run_config.pdf_paths, [pdf_path])
            self.assertEqual(run_config.output_folder, output_dir)

    def test_bypass_tab_requires_explicit_scan_before_integrated_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_tab = self.make_bypass_fake(temp_dir, scanned_files=[], table_rows=[])

            with self.assertRaises(TaskValidationError):
                BypassTab.build_run_config(fake_tab)

    def test_bypass_tab_builds_config_from_current_scan_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "book.xlsx")
            with open(source_path, "wb") as file:
                file.write(b"x")

            fake_tab = self.make_bypass_fake(
                temp_dir,
                scanned_files=[source_path],
                table_rows=[["book.xlsx", "1.0 KB", ".xlsb", "대기 중"]],
            )

            run_config = BypassTab.build_run_config(fake_tab)
            self.assertIsInstance(run_config, BypassRunConfig)
            self.assertEqual(run_config.tasks[0].src, source_path)
            self.assertTrue(run_config.tasks[0].tgt.endswith(".xlsb"))
            self.assertEqual(run_config.source_disposition, SourceDisposition.REPLACE)
            self.assertEqual(run_config.tasks[0].source_disposition, SourceDisposition.REPLACE)

    def test_bypass_tab_never_uses_the_source_as_same_extension_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "document.pdf")
            with open(source_path, "wb") as file:
                file.write(b"pdf")

            fake_tab = self.make_bypass_fake(
                temp_dir,
                scanned_files=[source_path],
                table_rows=[["document.pdf", "0.1 KB", ".pdf", "대기 중"]],
            )
            run_config = BypassTab.build_run_config(fake_tab)

            self.assertNotEqual(os.path.normcase(run_config.tasks[0].src), os.path.normcase(run_config.tasks[0].tgt))
            self.assertTrue(run_config.tasks[0].tgt.endswith("document_converted.pdf"))

    def test_bypass_tab_reserves_duplicate_output_names_within_one_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sources = [os.path.join(temp_dir, "book.xlsx"), os.path.join(temp_dir, "book.xls")]
            for source_path in sources:
                with open(source_path, "wb") as file:
                    file.write(b"office")

            fake_tab = self.make_bypass_fake(
                temp_dir,
                scanned_files=sources,
                table_rows=[
                    ["book.xlsx", "0.1 KB", ".xlsb", "대기 중"],
                    ["book.xls", "0.1 KB", ".xlsb", "대기 중"],
                ],
            )
            run_config = BypassTab.build_run_config(fake_tab)

            self.assertEqual(len({task.tgt for task in run_config.tasks}), 2)

    def test_bypass_backup_confirmation_summarizes_scope_and_defaults_to_no(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "document.pdf")
            target_dir = os.path.join(temp_dir, "output")
            os.makedirs(target_dir)
            with open(source, "wb") as file:
                file.write(b"1234")
            config = BypassRunConfig(
                [BypassFileConfig(source, os.path.join(target_dir, "document.zip"), ".zip", True, SourceDisposition.BACKUP)],
                SourceDisposition.BACKUP,
            )
            fake_tab = type("FakeBypassConfirmation", (), {})()
            fake_tab._t = lambda english, _korean, _polish=None: english
            fake_tab._format_size = BypassTab._format_size
            summary = BypassTab._backup_confirmation_text(fake_tab, config)
            fake_tab._backup_confirmation_text = lambda _config: summary

            with patch("src.ui.bypass_tab.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as question:
                confirmed = BypassTab._confirm_backup_move(fake_tab, config)

            self.assertFalse(confirmed)
            self.assertIn("Files: 1", summary)
            self.assertIn("Total size: 4.0 B", summary)
            self.assertIn(source.rsplit(os.sep, 1)[0], summary)
            self.assertIn(target_dir, summary)
            self.assertIn("Original Backup", summary)
            self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.No)

    def test_bypass_replace_confirmation_is_explicit_and_defaults_to_no(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            target = os.path.join(temp_dir, "book.xlsm")
            with open(source, "wb") as file:
                file.write(b"1234")
            config = BypassRunConfig(
                [BypassFileConfig(source, target, ".xlsm", True, SourceDisposition.REPLACE)],
                SourceDisposition.REPLACE,
            )
            fake_tab = type("FakeBypassConfirmation", (), {})()
            fake_tab._t = lambda english, _korean, _polish=None: english
            fake_tab._format_size = BypassTab._format_size
            summary = BypassTab._replacement_confirmation_text(fake_tab, config)
            fake_tab._replacement_confirmation_text = lambda _config: summary
            fake_tab._confirm_backup_move = lambda _config: True

            with patch("src.ui.bypass_tab.QMessageBox.warning", return_value=QMessageBox.StandardButton.No) as warning:
                confirmed = BypassTab._confirm_source_action(fake_tab, config)

            self.assertFalse(confirmed)
            self.assertIn("Windows Recycle Bin", summary)
            self.assertIn("permanent deletion is used", summary)
            self.assertIn("Original Backup is not used", summary)
            self.assertIn(f"{source}  →  {target}", summary)
            self.assertEqual(warning.call_args.args[-1], QMessageBox.StandardButton.No)

    def test_bypass_custom_output_keeps_or_backs_up_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(output_dir)
            source_path = os.path.join(temp_dir, "book.xlsx")
            with open(source_path, "wb") as file:
                file.write(b"x")
            fake_tab = self.make_bypass_fake(
                temp_dir,
                scanned_files=[source_path],
                table_rows=[["book.xlsx", "1.0 KB", ".xlsm", "대기 중"]],
            )
            fake_tab.radio_inplace = CheckedValue(False)
            fake_tab.tgt_entry = TextValue(output_dir)

            run_config = BypassTab.build_run_config(fake_tab)

            self.assertEqual(run_config.source_disposition, SourceDisposition.BACKUP)
            self.assertTrue(run_config.tasks[0].tgt.startswith(output_dir))

    def test_sync_tab_rejects_missing_or_duplicate_folders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_tab = type("FakeSyncTab", (), {})()
            fake_tab.config_manager = FakeConfig()
            fake_tab.sync_groups = [{"name": "daily", "folders": [temp_dir, temp_dir]}]

            with self.assertRaises(TaskValidationError):
                SyncTab.build_run_config(fake_tab)

            fake_tab.sync_groups = [{"name": "daily", "folders": [temp_dir, os.path.join(temp_dir, "missing")]}]
            with self.assertRaises(TaskValidationError):
                SyncTab.build_run_config(fake_tab)

    def test_sync_and_eml_tabs_build_typed_configs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(output_dir)
            sync_tab = type("FakeSyncTab", (), {})()
            sync_tab.config_manager = FakeConfig({"sync_move_to_deleted": True})
            sync_tab.sync_groups = [{"name": "daily", "folders": [temp_dir, output_dir]}]

            sync_config = SyncTab.build_run_config(sync_tab)
            self.assertIsInstance(sync_config, SyncRunConfig)
            self.assertEqual(sync_config.sync_groups[0].name, "daily")

            eml_tab = type("FakeEMLTab", (), {})()
            eml_tab.config_manager = FakeConfig({"eml_output_width": 1200})
            eml_tab.tasks = [{"name": "mail", "source_folder": temp_dir, "target_folder": output_dir}]

            eml_config = EMLTab.build_run_config(eml_tab)
            self.assertIsInstance(eml_config, EmlRunConfig)
            self.assertEqual(eml_config.width, 1200)

    def make_bypass_fake(self, source_dir, scanned_files, table_rows):
        fake_tab = type("FakeBypassTab", (), {})()
        fake_tab.src_entry = TextValue(source_dir)
        fake_tab.tgt_entry = TextValue("저장할 우회 폴더를 선택하세요.")
        fake_tab.scanned_files = scanned_files
        fake_tab.radio_inplace = CheckedValue(True)
        fake_tab.file_table = FakeTable(table_rows)
        fake_tab.check_preserve_meta = CheckedValue(True)
        fake_tab.check_backup_orig = CheckedValue(True)
        return fake_tab


if __name__ == "__main__":
    unittest.main()
