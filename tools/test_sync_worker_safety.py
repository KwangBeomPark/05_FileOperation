"""Regression coverage for incomplete synchronization previews."""

import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from src.ui.sync_tab import SyncTab, SyncWorker


class _Config:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, "en" if key == "ui_language" else default)

    def set(self, key, value):
        self.values[key] = value
        return True


class SyncWorkerSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _run_with_manager(self, manager):
        worker = SyncWorker([{"name": "g", "folders": ["a", "b"]}], _Config())
        worker._create_manager = lambda *_args: manager(worker)
        completed = []
        failed = []
        worker.dry_run_finished.connect(completed.append)
        worker.finished.connect(lambda *args: failed.append(args))
        worker.run()
        return completed, failed

    def test_cancelled_preview_is_not_reported_complete(self):
        def manager(worker):
            class Manager:
                scan_errors = ()

                def analyze_sync(self):
                    worker.is_cancelled = True
                    return [{"filename": "partial"}]

            return Manager()

        completed, failed = self._run_with_manager(manager)
        self.assertFalse(completed)
        self.assertEqual(len(failed), 1)
        self.assertFalse(failed[0][0])

    def test_partial_scan_is_not_reported_complete(self):
        def manager(_worker):
            class Manager:
                scan_errors = (OSError("unavailable"),)

                def analyze_sync(self):
                    return [{"filename": "partial"}]

            return Manager()

        completed, failed = self._run_with_manager(manager)
        self.assertFalse(completed)
        self.assertEqual(len(failed), 1)
        self.assertIn("unavailable", failed[0][3][0])

    def test_new_and_existing_groups_keep_their_disposition(self):
        config = _Config({"sync_groups": [{"name": "old", "folders": []}]})
        tab = SyncTab(config)
        self.assertEqual(tab.date_archive_combo.currentData(), "folder")
        self.assertNotIn("date_archive_mode", config.values["sync_groups"][0])
        with patch("src.ui.sync_tab.QInputDialog.getText", return_value=("new", True)):
            tab.add_group()
        self.assertEqual(tab.date_archive_combo.currentData(), "folder")
        tab.group_combo.setCurrentIndex(0)
        self.assertEqual(tab.date_archive_combo.currentData(), "folder")
        self.assertNotIn("date_archive_mode", config.values["sync_groups"][0])
        tab.group_combo.setCurrentIndex(1)
        self.assertEqual(tab.date_archive_combo.currentData(), "folder")
        self.assertEqual(config.values["sync_groups"][1]["date_archive_mode"], "folder")
        tab.set_ui_enabled(False)
        self.assertFalse(tab.date_archive_combo.isEnabled())
        self.assertFalse(tab.subfolders_check.isEnabled())
        tab.set_ui_enabled(True)
        self.assertTrue(tab.date_archive_combo.isEnabled())
        tab.close()

    def test_initial_group_defaults_to_folder(self):
        tab = SyncTab(_Config())
        self.assertEqual(tab.date_archive_combo.currentData(), "folder")
        self.assertIn("blocked", tab.date_archive_combo.itemText(0).lower())
        self.assertIn("to be deleted", tab.date_archive_combo.itemText(1))
        tab.close()

    def test_held_only_preview_disables_execution_and_reports_hold(self):
        config = _Config({"ui_language": "ko", "sync_groups": [{"name": "g", "folders": ["source", "target"]}]})
        tab = SyncTab(config)
        self.addCleanup(tab.close)
        action = {"group_name": "g", "filename": "report_v2.txt", "action": "보류",
                  "source_folder": "source", "target_folder": "target",
                  "reason": "Target has a newer version"}
        with patch("src.ui.sync_tab.show_toast"):
            tab.on_dry_run_finished([action])
        self.assertFalse(tab.sync_btn.isEnabled())
        self.assertIn("실행 예정 0건", tab.plan_summary_label.text())
        self.assertIn("보류 1건", tab.plan_summary_label.text())
        self.assertIn("보류 항목만", tab.sync_btn.toolTip())

    def test_explicit_saved_modes_are_preserved_when_switching_groups(self):
        groups = [
            {"name": "folder", "folders": [], "date_archive_mode": "folder"},
            {"name": "trash", "folders": [], "date_archive_mode": "trash"},
        ]
        config = _Config({"sync_groups": groups})
        tab = SyncTab(config)
        for index, expected in enumerate(("folder", None)):
            tab.group_combo.setCurrentIndex(index)
            self.assertEqual(tab.date_archive_combo.currentData(), expected)
        self.assertEqual([group["date_archive_mode"] for group in config.values["sync_groups"]], ["folder", "trash"])
        tab.subfolders_check.setChecked(True)
        self.assertEqual(tab.sync_groups[1]["date_archive_mode"], "trash")
        tab.date_archive_combo.setCurrentIndex(1)
        self.assertEqual(tab.sync_groups[1]["date_archive_mode"], "folder")
        tab.close()
