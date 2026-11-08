"""Isolated UI tests: all file operations are injected fakes."""
import logging
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

_temporary = tempfile.TemporaryDirectory()
os.environ["TEMP"] = _temporary.name
os.environ["TMP"] = _temporary.name
os.environ["LOCALAPPDATA"] = _temporary.name
os.environ["APPDATA"] = _temporary.name
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.ui.main_window import MainWindow
from src.ui.sync_tab import SyncTab
from src.ui.task_tab import TaskTab
from src.ui.version_cleanup_dialog import VersionCleanupDialog

app = QApplication.instance() or QApplication([])


def wait(worker):
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    if worker.isRunning():
        loop.exec()
    app.processEvents()
    assert not worker.isRunning()


class CleanupUI(unittest.TestCase):
    def test_manual_selection_and_confirmation(self):
        calls = []
        candidate = {"path": "X:/example/old.txt", "folder": "X:/example", "filename": "old.txt", "date": "20240101", "latest_date": "20250101", "family_snapshot": {"test": 1}}
        def scan(**kwargs):
            calls.append(("scan", kwargs))
            kwargs["progress_callback"]("X:/example")
            return [candidate]
        def execute(**kwargs):
            calls.append(("execute", kwargs))
            kwargs["progress_callback"](1, 1, "old.txt")
            return {"success": 1, "fail": 0, "cancelled": False, "not_processed": 0, "errors": []}
        dialog = VersionCleanupDialog(["X:/example"], "ko", scan=scan, execute=execute, archive_folder_name="archive")
        self.assertEqual(dialog.method.currentData(), "trash")
        dialog.start_scan()
        wait(dialog.worker)
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(dialog.table.item(0, 3).text(), "20240101")
        self.assertEqual(dialog.table.item(0, 4).text(), "20250101")
        self.assertFalse(dialog.execute_button.isEnabled())
        self.assertEqual(calls[0][1]["archive_folder_name"], "archive")
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(dialog.execute_button.isEnabled())
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(dialog.execute_button.isEnabled())
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog.start_execution()
        self.assertEqual(len(calls), 1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.start_execution()
        wait(dialog.worker)
        self.assertEqual(calls[1][1]["candidates"], [candidate])
        self.assertEqual(calls[1][1]["method"], "trash")
        self.assertEqual(dialog.table.rowCount(), 0)
        dialog.close()

    def test_subfolder_change_invalidates_candidates(self):
        dialog = VersionCleanupDialog(["X:/example"], "en", scan=lambda **kw: [], execute=lambda **kw: {})
        dialog.candidates = [{"path": "x"}]
        dialog.subfolders.setChecked(True)
        self.assertFalse(dialog.candidates)
        self.assertFalse(dialog.execute_button.isEnabled())
        dialog.close()

    def test_default_executor_routes_selected_files_and_disables_while_running(self):
        entered, release = threading.Event(), threading.Event()
        candidate = {"path": "X:/example/a_v0.1.txt"}
        def execute(**kwargs):
            entered.set()
            release.wait(2)
            return {"success": 1}
        with patch("src.core.version_cleanup.execute_version_cleanup", side_effect=execute) as operation:
            dialog = VersionCleanupDialog(["X:/example"], "en", scan=lambda **kw: [candidate])
            dialog.start_scan()
            wait(dialog.worker)
            self.assertFalse(dialog.execute_button.isEnabled())
            dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            dialog.method.setCurrentIndex(1)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                dialog.start_execution()
            self.assertTrue(entered.wait(2))
            self.assertFalse(dialog.execute_button.isEnabled())
            self.assertFalse(dialog.table.isEnabled())
            release.set()
            wait(dialog.worker)
            self.assertEqual(operation.call_args.kwargs["method"], "folder")
            self.assertEqual(operation.call_args.kwargs["candidates"], [candidate])
            dialog.close()

    def test_real_engine_folder_route_on_temporary_files(self):
        with tempfile.TemporaryDirectory(dir=_temporary.name) as folder:
            old = Path(folder) / "report_v0.1.txt"
            latest = Path(folder) / "report_v1.2.txt"
            old.write_text("old", encoding="utf-8")
            latest.write_text("latest", encoding="utf-8")
            dialog = VersionCleanupDialog([folder], "en")
            dialog.start_scan()
            wait(dialog.worker)
            self.assertEqual(dialog.table.rowCount(), 1)
            dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            dialog.method.setCurrentIndex(1)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                dialog.start_execution()
            wait(dialog.worker)
            self.assertIn("Completed: 1", dialog.status.text())
            self.assertFalse(old.exists())
            self.assertEqual((Path(folder) / "to be deleted" / old.name).read_text(), "old")
            self.assertEqual(latest.read_text(), "latest")
            dialog.close()

    def test_execution_exception_and_cancel_close(self):
        entered = threading.Event()
        def execute(**kwargs):
            entered.set()
            while not kwargs["cancel_callback"]():
                time.sleep(0.001)
            raise RuntimeError("test failure")
        dialog = VersionCleanupDialog(["X:/example"], "en", scan=lambda **kw: [{"path": "x"}], execute=execute)
        dialog.start_scan()
        wait(dialog.worker)
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.start_execution()
        self.assertTrue(entered.wait(2))
        worker = dialog.worker
        dialog.close()
        self.assertFalse(worker.isRunning())
        app.processEvents()
        self.assertIn("test failure", dialog.status.text())

    def test_legacy_trash_setting_is_preserved_until_explicit_selection(self):
        class Config:
            def __init__(self):
                self.data = {"sync_groups": [{"name": "legacy", "folders": [], "date_archive_mode": "trash"}]}
            def get(self, key, default=None):
                return self.data.get(key, default)
            def set(self, key, value):
                self.data[key] = value
                return True
        config = Config()
        tab = SyncTab(config)
        tab.subfolders_check.setChecked(True)
        self.assertEqual(tab.sync_groups[0]["date_archive_mode"], "trash")
        self.assertEqual(config.data["sync_groups"][0]["date_archive_mode"], "trash")
        tab.date_archive_combo.setCurrentIndex(1)
        self.assertEqual(tab.sync_groups[0]["date_archive_mode"], "folder")
        tab.close()

    def test_shutdown_cancels_and_waits_for_scan(self):
        entered = threading.Event()
        def scan(**kwargs):
            entered.set()
            while not kwargs["cancel_callback"]():
                time.sleep(0.001)
            return []
        dialog = VersionCleanupDialog(["X:/example"], "en", scan=scan)
        dialog.start_scan()
        self.assertTrue(entered.wait(2))
        original = dialog.worker
        dialog.launch(scan, {}, dialog.scan_finished)
        self.assertIs(dialog.worker, original)
        tab = SimpleNamespace(cleanup_dialog=dialog)
        self.assertTrue(SyncTab.cleanup_running(tab))
        SyncTab.stop_all(SimpleNamespace(worker=None, cleanup_dialog=dialog))
        self.assertFalse(original.isRunning())
        app.processEvents()
        dialog.close()

    def test_main_window_reports_cleanup_worker(self):
        idle = SimpleNamespace(is_running=False, is_converting=False)
        sync = SimpleNamespace(is_running=False, cleanup_running=lambda: True)
        window = SimpleNamespace(language="en", task_tab=idle, pdf_tab=idle, ocr_tab=idle,
                                 eml_tab=idle, sync_tab=sync, collect_sync_tab=idle, bypass_tab=idle)
        self.assertIn("Old-version cleanup", MainWindow.active_tasks_running(window))

    def test_clean_close_stops_sync_workers(self):
        sync = SimpleNamespace(stop_all=Mock())
        collect = SimpleNamespace(_confirmation_active=False, stop_all=Mock())
        window = SimpleNamespace(_run_confirmation_active=False, collect_sync_tab=collect,
                                 tray_icon=None, active_tasks_running=list, sync_tab=sync,
                                 save_window_state=Mock())
        event = SimpleNamespace(accept=Mock(), ignore=Mock())
        MainWindow.closeEvent(window, event)
        sync.stop_all.assert_called_once_with()
        event.accept.assert_called_once_with()

    def test_open_dialog_blocks_scheduled_and_manual_task_start(self):
        task = SimpleNamespace(_version_cleanup_open=lambda: True, _update_config=Mock(),
                               _text=lambda en, ko, pl: en, _start_rejected=Mock(return_value=False))
        self.assertFalse(TaskTab.check_scheduled_run(task))
        task._update_config.assert_not_called()
        self.assertFalse(TaskTab.start_all_tasks(task))
        task._start_rejected.assert_called_once()

    def test_open_cleanup_blocks_active_task_and_preflight(self):
        for state in ("is_running", "is_preflighting"):
            task = SimpleNamespace(is_running=False, is_preflighting=False)
            setattr(task, state, True)
            tab = SimpleNamespace(is_running=False, current_group_idx=0,
                                  window=lambda task=task: SimpleNamespace(task_tab=task),
                                  _msg=lambda key: key, _t=lambda en, ko, pl: en)
            with patch("src.ui.sync_tab.QMessageBox.warning") as warning:
                SyncTab.open_version_cleanup(tab)
            warning.assert_called_once()

    def test_localized_scan_errors_keep_details(self):
        expected = {"en": "Check the filenames", "ko": "파일명을 확인", "pl": "Sprawdź nazwy plików"}
        for language, phrase in expected.items():
            dialog = VersionCleanupDialog(["X:/example"], language, scan=lambda **kw: [])
            for error in ("Invalid or mixed version formats: X:/example", "Equivalent version names require review: X:/example"):
                message = dialog.scan_error_message(error)
                self.assertIn(phrase, message)
                self.assertIn(error, message)
            dialog.close()

    def test_localized_execution_details_keep_path_and_reason(self):
        expected = {"en": ("During processing", "uncertain"), "ko": ("처리 중", "불확실"), "pl": ("Podczas przetwarzania", "niepewny")}
        for language, phrases in expected.items():
            dialog = VersionCleanupDialog(["X:/example"], language, scan=lambda **kw: [])
            dialog.worker = SimpleNamespace(wait=lambda: None)
            dialog.execution_finished({"success": 0, "fail": 1, "cancelled": False,
                                       "error_details": [{"phase": "execution", "path": "X:/example/a", "reason": "raw reason", "uncertain": True}]}, None)
            for phrase in (*phrases, "X:/example/a", "raw reason"):
                self.assertIn(phrase, dialog.status.text())
            self.assertNotIn("True", dialog.status.text())
            dialog.worker = None
            dialog.close()


if __name__ == "__main__":
    try:
        result = unittest.main(exit=False).result
    finally:
        logging.shutdown()
        _temporary.cleanup()
    sys.exit(0 if result.wasSuccessful() else 1)
