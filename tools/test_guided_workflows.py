import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTableWidgetItem

from src.ui.bypass_tab import BypassTab
from src.ui.eml_tab import EMLTab
from src.ui.ocr_tab import OCRTab
from src.ui.pdf_tab import PDFTab
from src.ui.sync_tab import SyncTab


class FakeConfig:
    def __init__(self, values=None):
        self.values = {"ui_language": "ko", **(values or {})}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def update(self, values):
        self.values.update(values)


class GuidedWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pdf_and_ocr_start_only_after_input_selection(self):
        pdf = PDFTab(FakeConfig({"output_folder": "output"}))
        self.assertFalse(pdf.start_btn.isEnabled())
        pdf.selected_pdf_paths.append("sample.pdf")
        pdf._refresh_action_state()
        self.assertTrue(pdf.start_btn.isEnabled())

        ocr = OCRTab(FakeConfig())
        self.assertFalse(ocr.start_btn.isEnabled())
        ocr.add_image_to_list("sample.png")
        self.assertTrue(ocr.start_btn.isEnabled())

        pdf.close()
        ocr.close()

    def test_eml_requires_a_task_and_row_actions_require_selection(self):
        eml = EMLTab(FakeConfig())
        self.assertFalse(eml.start_btn.isEnabled())
        self.assertFalse(eml.edit_btn.isEnabled())
        eml.tasks = [{"name": "mail", "source_folder": "source", "target_folder": "output"}]
        eml.update_table_view()
        self.assertTrue(eml.start_btn.isEnabled())
        self.assertFalse(eml.edit_btn.isEnabled())
        eml.table_widget.selectRow(0)
        self.assertTrue(eml.edit_btn.isEnabled())
        eml.close()

    def test_sync_requires_two_folders_and_a_current_nonempty_preview(self):
        sync = SyncTab(FakeConfig())
        self.assertFalse(sync.analyze_btn.isEnabled())
        self.assertFalse(sync.sync_btn.isEnabled())
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            sync.sync_groups = [{"name": "daily", "folders": [first, second]}]
            sync._refresh_action_state()
            self.assertTrue(sync.analyze_btn.isEnabled())
            self.assertFalse(sync.sync_btn.isEnabled())
            sync._analysis_is_current = True
            sync._analysis_has_actions = True
            sync._refresh_action_state()
            self.assertTrue(sync.sync_btn.isEnabled())
            sync._invalidate_analysis(folders_changed=True)
            self.assertFalse(sync.sync_btn.isEnabled())
        sync.close()

    def test_sync_bridge_weekdays_schedule_multilingual(self):
        config = FakeConfig({
            "task_enabled_items": {"sync:grp1": True},
            "task_schedule_enabled": True,
            "task_schedule_mode": "daily",
            "task_schedule_time": "09:30",
            "task_schedule_weekdays": [0, 1, 2, 3, 4],
            "ui_language": "en",
        })
        sync = SyncTab(config)
        sync.sync_groups = [{"id": "grp1", "name": "work", "folders": ["/a", "/b"]}]
        sync.current_group_idx = 0

        # EN (points to real tab name 'Run Tasks')
        sync.refresh_task_bridge()
        self.assertIn("Run Tasks: Included", sync.task_bridge_label.text())
        self.assertIn("Mon-Fri 09:30", sync.task_bridge_label.text())
        self.assertNotIn("daily", sync.task_bridge_label.text())
        self.assertEqual(sync.task_bridge_btn.text(), "Open Run Tasks")
        self.assertEqual(sync.archive_input.placeholderText(), "to be deleted")

        # KO (points to real tab name '작업 실행')
        config.values["ui_language"] = "ko"
        sync.refresh_language()
        self.assertIn("작업 실행: 포함됨", sync.task_bridge_label.text())
        self.assertIn("월~금 09:30", sync.task_bridge_label.text())
        self.assertNotIn("매일", sync.task_bridge_label.text())
        self.assertEqual(sync.task_bridge_btn.text(), "작업 실행 열기")

        # PL (points to real tab name 'Uruchom zadania' and tone 'Uwzględnione')
        config.values["ui_language"] = "pl"
        sync.refresh_language()
        self.assertIn("Uruchom zadania: Uwzględnione", sync.task_bridge_label.text())
        self.assertIn("Pn-Pt 09:30", sync.task_bridge_label.text())
        self.assertNotIn("codziennie", sync.task_bridge_label.text())
        self.assertEqual(sync.task_bridge_btn.text(), "Otwórz Uruchom zadania")
        sync.close()

    def test_convert_files_updates_targets_in_memory_when_target_format_changes(self):
        with tempfile.TemporaryDirectory() as source:
            bypass = BypassTab(FakeConfig())
            bypass.set_source_folder_path(source)
            file_path = os.path.join(source, "book.xlsx")
            bypass.scanned_files = [file_path]
            bypass.file_table.setRowCount(1)
            item = QTableWidgetItem("book.xlsx")
            item.setData(Qt.ItemDataRole.UserRole, file_path)
            bypass.file_table.setItem(0, 0, item)
            bypass.file_table.setItem(0, 2, QTableWidgetItem(".xlsb"))
            bypass._refresh_action_state()
            self.assertTrue(bypass.start_btn.isEnabled())

            bypass.excel_combo.setCurrentText(".xlsm")
            self.assertEqual(bypass.scanned_files, [file_path])
            self.assertEqual(bypass.file_table.item(0, 2).text(), ".xlsm")
            self.assertTrue(bypass.start_btn.isEnabled())
            bypass.close()

    def test_convert_files_makes_source_replacement_visible_and_separates_backup_option(self):
        bypass = BypassTab(FakeConfig({"bypass_output_mode": "inplace"}))
        self.assertTrue(bypass.radio_inplace.isChecked())
        self.assertFalse(bypass.check_backup_orig.isEnabled())
        self.assertIn("휴지통으로 이동", bypass.source_action_hint.text())
        self.assertIn("영구 삭제", bypass.source_action_hint.text())
        self.assertEqual(bypass.start_btn.text(), "변환 후 원본 교체")

        bypass.radio_custom.setChecked(True)

        self.assertTrue(bypass.check_backup_orig.isEnabled())
        self.assertIn("그대로 보존", bypass.source_action_hint.text())
        self.assertEqual(bypass.start_btn.text(), "파일 변환 시작")
        bypass.close()

    def test_inplace_scan_skips_files_already_in_target_format(self):
        with tempfile.TemporaryDirectory() as source:
            workbook = os.path.join(source, "book.xlsm")
            with open(workbook, "wb") as file:
                file.write(b"workbook")
            bypass = BypassTab(FakeConfig({
                "bypass_output_mode": "inplace",
                "bypass_excel_target": ".xlsm",
            }))
            bypass.set_source_folder_path(source)

            bypass.scan_source_folder()

            self.assertEqual(bypass.scanned_files, [])
            self.assertIn("이미 같은 파일 1개", bypass.log_area.toPlainText())
            self.assertFalse(bypass.start_btn.isEnabled())
            bypass.close()


if __name__ == "__main__":
    unittest.main()
