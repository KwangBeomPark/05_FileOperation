import os
import unittest
from unittest.mock import Mock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMainWindow

from src.core.task_contracts import TaskStep
from src.ui.task_tab import TaskTab


class FakeConfig:
    def __init__(self, values=None):
        self.values = {"ui_language": "en", **(values or {})}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return True


class TaskSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_selection_is_sync_only_and_stale_bypass_is_not_validated(self):
        config = FakeConfig()
        window = QMainWindow()
        task_tab = TaskTab(config)
        window.setCentralWidget(task_tab)

        window.sync_tab = Mock()
        window.sync_tab.build_run_config.return_value = None
        window.eml_tab = Mock()
        window.pdf_tab = Mock()
        window.ocr_tab = Mock()
        window.bypass_tab = Mock()

        with patch("src.ui.task_tab.QMessageBox.warning"):
            self.assertFalse(task_tab.start_all_tasks())

        self.assertEqual(task_tab.selected_steps(), [TaskStep.SYNC])
        window.sync_tab.build_run_config.assert_called_once_with()
        window.bypass_tab.build_run_config.assert_not_called()
        self.assertEqual(task_tab.status_table.item(0, 1).text(), "Sync Folders")

        task_tab.schedule_timer.stop()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
