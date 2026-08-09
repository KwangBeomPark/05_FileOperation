import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

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

    def test_convert_files_invalidates_scan_when_target_format_changes(self):
        with tempfile.TemporaryDirectory() as source:
            bypass = BypassTab(FakeConfig())
            bypass.set_source_folder_path(source)
            bypass.scanned_files = [os.path.join(source, "book.xlsx")]
            bypass._refresh_action_state()
            self.assertTrue(bypass.start_btn.isEnabled())
            bypass.excel_combo.setCurrentText(".xlsx")
            self.assertEqual(bypass.scanned_files, [])
            self.assertFalse(bypass.start_btn.isEnabled())
            bypass.close()


if __name__ == "__main__":
    unittest.main()
