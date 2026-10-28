"""Offscreen collection UI, real worker, scheduling and lifecycle regressions."""

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer, Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from src.core.collect_sync import ACTION_COPY, ACTION_ERROR, CollectAction, CollectReport
from src.core.collect_sync_config import new_collect_group
from src.ui.collect_sync_tab import CollectSyncTab, CollectWorker
from src.ui.i18n import tr
from src.ui.main_window import MainWindow
from src.ui.task_tab import TaskTab
from tools.test_collect_sync_config import wall_time


class MemoryConfig:
    """No actual application settings, updates or registry changes in fixtures."""

    def __init__(self, groups=(), language="en"):
        self.values = {
            "collect_sync_groups": copy.deepcopy(list(groups)),
            "ui_language": language,
            "auto_check_update": "manual",
            "task_schedule_enabled": False,
            "task_folder_watch_enabled": False,
        }
        self.fail = False
        self.app_dir = None

    def get(self, key, default=None):
        return copy.deepcopy(self.values.get(key, default))

    def set(self, key, value):
        if self.fail:
            return False
        self.values[key] = copy.deepcopy(value)
        return True

    def update(self, values):
        if self.fail:
            return False
        self.values.update(copy.deepcopy(values))
        return True


def wait_until(predicate, timeout_ms=5000):
    """Pump the Qt event loop (never sleep the GUI) until completion or test timeout."""
    if predicate():
        return
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    poll.start()
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    if not predicate():
        raise AssertionError("Qt operation did not finish before timeout")


class CollectUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.source.mkdir()
        self.target.mkdir()
        self.group = new_collect_group("Daily")
        self.group.update(
            sources=[str(self.source)], keywords=["report"], target=str(self.target)
        )
        self.config = MemoryConfig([self.group])
        self.tab = CollectSyncTab(self.config)
        self.tab.state_path = self.root / "data" / "collect_sync_state.json"

    def tearDown(self):
        self.assertTrue(self.tab.stop_all())
        self.tab.deleteLater()
        QCoreApplication.sendPostedEvents()
        self.app.processEvents()
        self.temporary.cleanup()

    def finish(self):
        wait_until(lambda: not self.tab.is_running)

    def test_group_add_rename_remove_and_reload_preserve_independent_settings(self):
        with patch(
            "src.ui.collect_sync_tab.QInputDialog.getText",
            return_value=("Second", True),
        ):
            self.tab.add_group()
        self.assertEqual(len(self.tab.groups), 2)
        self.tab.keywords_input.setText("invoice, memo")
        self.tab.target_input.setText(str(self.target))
        self.tab.add_source_paths([str(self.source), str(self.source)])
        self.tab.subfolders_check.setChecked(True)
        with patch(
            "src.ui.collect_sync_tab.QInputDialog.getText",
            return_value=("Renamed", True),
        ):
            self.tab.rename_group()
        restored = CollectSyncTab(self.config)
        try:
            self.assertEqual(restored.groups[1]["name"], "Renamed")
            self.assertEqual(restored.groups[1]["sources"], [str(self.source)])
            self.assertEqual(restored.groups[1]["keywords"], ["invoice", "memo"])
            self.assertFalse(restored.groups[1]["schedule_enabled"])
            self.assertEqual(restored.groups[0]["keywords"], ["report"])
        finally:
            restored.stop_all()
            restored.deleteLater()
        with patch(
            "src.ui.collect_sync_tab.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.tab.delete_group()
        self.assertEqual(len(self.tab.groups), 1)

    def test_real_preview_is_read_only_then_run_and_repeat_are_stable(self):
        (self.source / "report.txt").write_text("data", encoding="utf-8")
        self.assertTrue(self.tab.start_dry_run())
        self.assertFalse(self.tab.editor.isEnabled())
        self.assertFalse(self.tab.run_button.isEnabled())
        self.finish()
        self.assertFalse(self.tab.state_path.exists())
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual(self.tab.table.rowCount(), 1)
        self.assertIn("no files", self.tab.status_label.text())
        self.assertTrue(self.tab.result_pager.isHidden())
        self.assertNotIn("page buttons", self.tab.summary_label.text())
        with patch(
            "src.ui.collect_sync_tab.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.assertTrue(self.tab.start_execution())
        self.finish()
        self.assertTrue((self.target / "report.txt").exists())
        self.assertEqual(self.tab._last_report.count(ACTION_COPY), 1)
        report_file = (
            self.tab.state_path.parent
            / "collect_sync_reports"
            / f"{self.group['id']}.json"
        )
        self.assertEqual(
            json.loads(report_file.read_text(encoding="utf-8"))["actions"][0]["kind"],
            ACTION_COPY,
        )
        self.assertTrue(self.tab._start())
        self.finish()
        self.assertEqual(self.tab.table.item(0, 0).text(), "Unchanged")

    def test_manual_cancel_does_not_create_worker(self):
        with patch(
            "src.ui.collect_sync_tab.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            self.assertFalse(self.tab.start_execution())
        self.assertIsNone(self.tab.worker)

    def test_all_2001_preview_results_are_accessible_without_report_write(self):
        for number in range(2001):
            (self.source / f"report{number:04d}.txt").write_text(
                "fixture", encoding="utf-8"
            )
        self.assertTrue(self.tab.start_dry_run())
        self.finish()
        self.assertEqual(len(self.tab._last_report.actions), 2001)
        self.assertEqual(self.tab.table.rowCount(), 2000)
        self.assertFalse(self.tab.previous_page_button.isEnabled())
        self.assertTrue(self.tab.next_page_button.isEnabled())
        self.assertIn("no report file was saved", self.tab.summary_label.text())
        self.tab.next_page_button.click()
        self.assertEqual(self.tab.table.rowCount(), 1)
        self.assertEqual(Path(self.tab.table.item(0, 1).text()).name, "report2000.txt")
        self.assertTrue(self.tab.previous_page_button.isEnabled())
        self.assertFalse(self.tab.next_page_button.isEnabled())
        for language in ("ko", "pl", "en"):
            self.config.values["ui_language"] = language
            self.tab.refresh_language()
            self.assertEqual(self.tab._result_page, 1)
            self.assertEqual(
                self.tab.next_page_button.text(), tr("collect_next_page", language)
            )
        self.tab.previous_page_button.click()
        self.assertEqual(self.tab.table.rowCount(), 2000)
        self.assertFalse(self.tab.state_path.exists())
        self.assertFalse((self.tab.state_path.parent / "collect_sync_reports").exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_clearing_results_hides_pager_on_edit_and_new_run(self):
        from src.core.collect_sync import CollectAction, CollectReport

        self.tab._last_report = CollectReport([CollectAction(ACTION_COPY)] * 2001)
        self.tab._render_report()
        self.assertFalse(self.tab.result_pager.isHidden())
        self.tab.keywords_input.editingFinished.emit()
        self.assertTrue(self.tab.result_pager.isHidden())
        self.assertFalse(self.tab.next_page_button.isEnabled())
        self.assertEqual(self.tab.table.rowCount(), 0)
        self.tab._last_report = CollectReport([CollectAction(ACTION_COPY)] * 2001)
        self.tab._render_report()
        self.assertTrue(self.tab.start_dry_run())
        self.assertTrue(self.tab.result_pager.isHidden())
        self.finish()

    def test_manual_and_scheduled_selected_group_check_other_configured_groups(self):
        (self.source / "report.txt").write_text("data", encoding="utf-8")
        reverse = new_collect_group("reverse")
        reverse.update(
            sources=[str(self.target)], keywords=["report"], target=str(self.source)
        )
        self.tab.groups.append(reverse)
        self.assertTrue(self.tab._start())
        self.finish()
        self.assertEqual(self.tab._last_report.actions[0].message_code, "cycle")
        self.tab.groups[0].update(schedule_enabled=True, schedule_time="12:00")
        self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))
        self.assertTrue(self.tab._start())
        self.finish()
        self.assertEqual(self.tab._last_report.actions[0].message_code, "cycle")
        self.assertEqual(list(self.target.iterdir()), [])

    def test_confirmation_defers_schedules_and_reentrant_starts_without_attempts(self):
        self.tab.groups[0]["schedule_enabled"] = True

        def while_confirming(*_args):
            started = self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12))
            self.assertFalse(started)
            self.assertFalse(self.tab.start_dry_run())
            self.assertFalse(self.tab.start_execution())
            self.assertFalse(self.tab.stop_all())
            self.assertNotIn("schedule_attempt_count", self.tab.groups[0])
            return QMessageBox.StandardButton.No

        with patch(
            "src.ui.collect_sync_tab.QMessageBox.question", side_effect=while_confirming
        ):
            self.assertFalse(self.tab.start_execution())
        self.assertFalse(self.tab.is_busy)
        self.assertIsNone(self.tab.worker)

    def test_group_editor_modal_also_defers_schedule(self):
        self.tab.groups[0]["schedule_enabled"] = True

        def while_editing(*_args, **_kwargs):
            self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))
            self.assertTrue(self.tab.is_busy)
            return "Renamed", True

        with patch(
            "src.ui.collect_sync_tab.QInputDialog.getText", side_effect=while_editing
        ):
            self.tab.rename_group()
        self.assertEqual(self.tab.groups[0]["name"], "Renamed")
        self.assertNotIn("schedule_attempt_count", self.tab.groups[0])

    def test_modal_exception_releases_interaction_gate(self):
        with (
            patch(
                "src.ui.collect_sync_tab.QMessageBox.question",
                side_effect=RuntimeError("dialog failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.tab.start_execution()
        self.assertFalse(self.tab.is_busy)
        self.assertTrue(self.tab.editor.isEnabled())

    def test_state_commit_error_retains_completed_results_and_blocks_uncertain_retry(
        self,
    ):
        from src.core import collect_sync

        (self.source / "report.txt").write_text("test", encoding="utf-8")
        real_write = collect_sync.atomic_write_json
        calls = 0

        def fail_commit(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PermissionError("state disconnected")
            return real_write(*args, **kwargs)

        with patch("src.core.collect_sync.atomic_write_json", side_effect=fail_commit):
            self.assertTrue(self.tab._start())
            self.finish()
        self.assertEqual(self.tab._last_report.count(ACTION_COPY), 1)
        self.assertEqual(self.tab._last_report.count(ACTION_ERROR), 1)
        self.assertEqual(self.tab._status_key, "collect_state_error")
        self.assertTrue(self.tab._start())
        self.finish()
        self.assertEqual(self.tab._status_key, "collect_recovery_required")
        self.assertEqual([p.name for p in self.target.iterdir()], ["report.txt"])

    def test_start_failure_preserves_previous_completed_schedule_history(self):
        old = {
            "schedule_last_started_at": "2026-10-26T12:00:00",
            "schedule_last_finished_at": "2026-10-26T12:01:00",
            "schedule_last_result": "success",
            "last_result_counts": {"copy": 7},
            "last_finished_at": "2026-10-26T12:01:00",
        }
        self.tab.groups[0].update(old, schedule_enabled=True)
        with patch.object(
            CollectWorker, "start", side_effect=RuntimeError("thread start failed")
        ):
            self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))
        for key, value in old.items():
            self.assertEqual(self.tab.groups[0][key], value)
        self.assertNotIn("schedule_last_failure_at", self.tab.groups[0])

    def test_direct_native_start_failure_restores_persisted_schedule_history(self):
        previous = {
            "schedule_last_started_at": "2026-10-26T12:00:00",
            "schedule_last_finished_at": "2026-10-26T12:01:00",
            "schedule_last_result": "success",
            "last_result_counts": {"copy": 7},
        }
        self.tab.groups[0].update(previous)
        with patch.object(
            CollectWorker, "start", side_effect=RuntimeError("thread start failed")
        ):
            self.assertFalse(
                self.tab._start(
                    scheduled=True, index=0, now=wall_time(2026, 10, 27, 12)
                )
            )
        saved = self.config.get("collect_sync_groups")[0]
        for key, value in previous.items():
            self.assertEqual(saved[key], value)

    def test_failed_history_rollback_blocks_further_scheduling(self):
        original_set = self.config.set
        calls = 0

        def save(key, value):
            nonlocal calls
            calls += 1
            return original_set(key, value) if calls == 1 else False

        with (
            patch.object(self.config, "set", side_effect=save),
            patch.object(
                CollectWorker, "start", side_effect=RuntimeError("start failed")
            ),
        ):
            self.assertFalse(
                self.tab._start(
                    scheduled=True, index=0, now=wall_time(2026, 10, 27, 12)
                )
            )
        self.assertEqual(self.tab._status_key, "collect_save_error")
        self.assertTrue(self.tab._save_failed)
        self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 13)))

    def test_work_is_on_non_gui_thread_and_cancel_preserves_completed_file(self):
        for index in range(3):
            (self.source / f"report{index}.txt").write_text("data", encoding="utf-8")
        from src.core import collect_sync

        original = collect_sync._copy_new
        threads = []
        committed = threading.Event()
        release = threading.Event()

        def slow_copy(source, target):
            threads.append(threading.get_ident())
            original(source, target)
            committed.set()
            release.wait(3)

        with patch("src.core.collect_sync._copy_new", side_effect=slow_copy):
            try:
                self.assertTrue(self.tab._start())
                wait_until(committed.is_set)
                self.assertFalse(self.tab.start_dry_run())
                self.tab.stop()
                self.assertFalse(self.tab.stop_button.isEnabled())
                release.set()
                self.finish()
            finally:
                release.set()
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertTrue(self.tab._last_report.cancelled)
        self.assertEqual(self.tab._last_report.count(ACTION_COPY), 1)
        self.assertEqual(
            len(json.loads(self.tab.state_path.read_text(encoding="utf-8"))["targets"]),
            1,
        )




    def test_settings_save_failure_blocks_manual_and_schedule(self):
        self.config.fail = True
        self.tab.groups[0]["schedule_enabled"] = True
        self.assertFalse(self.tab._start())
        self.assertIsNone(self.tab.worker)
        self.assertIn("could not be saved", self.tab.status_label.text())
        self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))

    def test_busy_skip_does_not_consume_attempts(self):
        self.tab.groups[0]["schedule_enabled"] = True
        with patch.object(self.tab, "_other_tasks_running", return_value=True):
            self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))
        self.assertNotIn("schedule_attempt_count", self.tab.groups[0])
        self.tab.set_ui_locked(True)
        self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))
        self.tab.set_ui_locked(False)

    def test_other_modal_dialog_defers_schedule_without_attempts(self):
        self.tab.groups[0]["schedule_enabled"] = True
        dialog = QDialog()
        dialog.setModal(True)
        dialog.show()
        self.app.processEvents()
        try:
            self.assertIsNotNone(QApplication.activeModalWidget())
            self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))
            self.assertNotIn("schedule_attempt_count", self.tab.groups[0])
        finally:
            dialog.reject()
            dialog.deleteLater()
            self.app.processEvents()
        self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))
        self.assertTrue(self.tab._start())
        self.finish()


    def test_invalid_saved_settings_are_not_overwritten(self):
        self.config.values["collect_sync_groups"] = "bad"
        self.tab.load_saved_data()
        self.tab.refresh_language()
        self.assertTrue(self.tab._invalid_saved)
        self.assertFalse(self.tab.save_data())
        self.assertEqual(self.config.get("collect_sync_groups"), "bad")

    def test_restart_marks_previous_running_result_interrupted_without_repeating_day(
        self,
    ):
        self.config.values["collect_sync_groups"][0].update(
            schedule_enabled=True,
            schedule_last_result="running",
            schedule_last_started_at="2026-10-27T12:00:00",
            schedule_last_finished_at="",
        )
        restored = CollectSyncTab(self.config)
        try:
            self.assertEqual(restored.groups[0]["schedule_last_result"], "interrupted")
            self.assertEqual(restored.groups[0]["schedule_last_finished_at"], "")
            self.assertFalse(hasattr(restored, "schedule_timer"))
            self.assertFalse(restored.check_scheduled_run(wall_time(2026, 10, 27, 23)))
            self.assertEqual(
                self.config.get("collect_sync_groups")[0]["schedule_last_result"],
                "interrupted",
            )
        finally:
            restored.stop_all()
            restored.deleteLater()

    def test_corrupt_state_stops_worker_with_localized_message(self):
        self.tab.state_path.parent.mkdir()
        report_path = (
            self.tab.state_path.parent
            / "collect_sync_reports"
            / f"{self.group['id']}.json"
        )
        report_path.parent.mkdir()
        report_path.write_text('{"actions": [{"kind": "copy"}]}', encoding="utf-8")
        before = report_path.read_bytes()
        self.tab.groups[0]["last_result_counts"] = {"copy": 9}
        self.tab.state_path.write_text("broken", encoding="utf-8")
        self.assertTrue(self.tab._start())
        self.finish()
        self.assertIn("Mapping could not", self.tab.status_label.text())
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual(report_path.read_bytes(), before)
        self.assertEqual(self.tab.groups[0]["last_result_counts"], {"copy": 9})
        blocked = json.loads(
            report_path.with_name(f"{report_path.stem}.blocked.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(blocked["error_code"], "collect_state_error")

    def test_language_refresh_preserves_fields_and_translates_results(self):
        (self.source / "report.txt").write_text("test", encoding="utf-8")
        self.assertTrue(self.tab.start_dry_run())
        self.finish()
        for language in ("ko", "pl", "en"):
            self.config.values["ui_language"] = language
            self.tab.refresh_language()
            self.assertEqual(
                self.tab.table.item(0, 0).text(), tr("collect_copy", language)
            )
            self.assertEqual(self.tab.keywords_input.text(), "report")
            self.assertEqual(self.tab.target_input.text(), str(self.target))

    def test_shutdown_does_not_destroy_still_blocked_worker(self):
        worker = Mock()
        worker.wait.return_value = False
        self.tab.worker = worker
        self.tab.is_running = True
        try:
            self.assertFalse(self.tab.stop_all())
            worker.stop.assert_called_once()
            worker.wait.assert_called_once_with(1500)
            self.assertIs(self.tab.worker, worker)
        finally:
            self.tab.worker = None
            self.tab.is_running = False

    def test_report_save_failure_is_not_reported_as_success(self):
        with patch(
            "src.ui.collect_sync_tab.atomic_write_json",
            side_effect=PermissionError("report locked"),
        ):
            self.assertTrue(self.tab._start())
            self.finish()
        self.assertEqual(self.tab._status_key, "collect_save_error")

    def test_unexpected_second_file_failure_retains_completed_report_and_pending(self):
        from src.core import collect_sync

        for number in (1, 2):
            (self.source / f"report{number}.txt").write_text("data", encoding="utf-8")
        real_apply = collect_sync._apply_one

        def apply(source, *args, **kwargs):
            if source.name == "report2.txt":
                raise RuntimeError("unexpected second file failure")
            return real_apply(source, *args, **kwargs)

        with patch("src.core.collect_sync._apply_one", side_effect=apply):
            self.assertTrue(self.tab._start())
            self.finish()
        self.assertEqual(self.tab._last_report.count(ACTION_COPY), 1)
        self.assertEqual(self.tab._last_report.count(ACTION_ERROR), 1)
        self.assertEqual(self.tab._status_key, "collect_error_io")
        report = json.loads(
            (
                self.tab.state_path.parent
                / "collect_sync_reports"
                / f"{self.group['id']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(report["actions"][0]["kind"], ACTION_COPY)
        self.assertEqual(Path(report["actions"][1]["source"]).name, "report2.txt")
        self.assertTrue(
            json.loads(self.tab.state_path.read_text(encoding="utf-8"))["pending"]
        )
        report_path = (
            self.tab.state_path.parent
            / "collect_sync_reports"
            / f"{self.group['id']}.json"
        )
        completed_bytes = report_path.read_bytes()
        completed_counts = copy.deepcopy(self.tab.groups[0]["last_result_counts"])
        completed_at = self.tab.groups[0]["last_finished_at"]
        self.assertTrue(self.tab._start())
        self.finish()
        self.assertEqual(self.tab._status_key, "collect_recovery_required")
        self.assertEqual(report_path.read_bytes(), completed_bytes)
        self.assertEqual(self.tab.groups[0]["last_result_counts"], completed_counts)
        self.assertEqual(self.tab.groups[0]["last_finished_at"], completed_at)
        self.assertTrue(
            report_path.with_name(f"{report_path.stem}.blocked.json").exists()
        )
        blocked = json.loads(
            report_path.with_name(f"{report_path.stem}.blocked.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(blocked["error_code"], "collect_recovery_required")
        self.assertEqual(blocked["actions"][0]["message_code"], "pending")
        for language in ("ko", "en", "pl"):
            self.config.values["ui_language"] = language
            self.tab.refresh_language()
            self.assertIn(
                tr("collect_recovery_title", language), self.tab.status_label.text()
            )
        self.tab.groups[0].update(schedule_enabled=True, schedule_time="12:00")
        self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 27, 12)))
        self.assertTrue(self.tab._start())
        self.finish()
        self.assertEqual(report_path.read_bytes(), completed_bytes)
        self.assertEqual(self.tab.groups[0]["last_result_counts"], completed_counts)
        self.assertEqual(self.tab.groups[0]["last_finished_at"], completed_at)

    def test_report_serialization_failure_stays_inside_worker(self):
        with patch(
            "src.ui.collect_sync_tab.atomic_write_json",
            side_effect=ValueError("invalid serialization"),
        ):
            self.assertTrue(self.tab._start())
            self.finish()
        self.assertEqual(self.tab._status_key, "collect_save_error")


class CollectMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = MemoryConfig()
        with (
            patch("src.ui.main_window.ConfigManager", return_value=self.config),
            patch.object(MainWindow, "setup_system_tray"),
            patch.object(MainWindow, "trigger_update_check"),
            patch.object(TaskTab, "refresh_readiness"),
        ):
            self.window = MainWindow()
        self.window.task_tab.schedule_timer.stop()
        self.window.save_window_state = Mock()

    def tearDown(self):
        self.window.collect_sync_tab.is_running = False
        self.window.collect_sync_tab.stop_all()
        self.window.task_tab.stop_all()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def test_top_level_position_manual_language_and_global_lock(self):
        window = self.window
        index = window.tab_widget.indexOf(window.sync_tab)
        self.assertIs(window.tab_widget.widget(index + 1), window.collect_sync_tab)
        window.tab_widget.setCurrentWidget(window.collect_sync_tab)
        self.assertEqual(window._current_manual_topic(), "collect_sync")
        for language in ("ko", "pl", "en"):
            self.config.set("ui_language", language)
            window.refresh_language()
            self.assertEqual(
                window.tab_widget.tabText(index + 1), tr("tab_collect_sync", language)
            )
        window.set_all_tabs_locked(True)
        self.assertFalse(window.collect_sync_tab.editor.isEnabled())
        window.set_all_tabs_locked(False)
        self.assertTrue(window.collect_sync_tab.editor.isEnabled())

    def test_task_scheduler_and_manual_start_cannot_overlap_collect(self):
        self.window.collect_sync_tab.is_running = True
        self.assertFalse(
            self.window.task_tab.check_scheduled_run(wall_time(2026, 10, 27, 12))
        )
        self.assertFalse(self.window.task_tab.start_all_tasks(scheduled=True))
        self.assertIsNone(self.config.get("task_schedule_attempt_count"))

    def test_confirmation_also_blocks_task_start_and_window_exit(self):
        tab = self.window.collect_sync_tab
        with tab._interaction_guard():
            self.assertFalse(
                self.window.task_tab.check_scheduled_run(wall_time(2026, 10, 27, 12))
            )
            with patch.object(
                self.window.task_tab,
                "selected_steps",
                side_effect=AssertionError("Cannot inspect a new run"),
            ):
                self.assertFalse(self.window.task_tab.start_all_tasks(scheduled=True))
            event = QCloseEvent()
            self.window._is_exiting = True
            self.window.closeEvent(event)
            self.assertFalse(event.isAccepted())
        self.assertFalse(tab.is_busy)

    def test_close_refused_while_collect_os_operation_is_blocked(self):
        self.window.collect_sync_tab.is_running = True
        self.window._is_exiting = True
        event = QCloseEvent()
        with (
            patch(
                "src.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(self.window.collect_sync_tab, "stop_all", return_value=False),
        ):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertFalse(self.window._is_exiting)

    def test_failed_installer_launch_restores_previous_timer_state(self):
        timer = self.window.task_tab.schedule_timer
        for active in (True, False):
            timer.start() if active else timer.stop()
            with (
                patch(
                    "src.ui.main_window.launch_installer",
                    side_effect=OSError("launch failed"),
                ),
                self.assertRaises(OSError),
            ):
                self.window._launch_update_installer("fixture-not-executed.exe")
            self.assertEqual(timer.isActive(), active)

    def test_installer_is_refused_while_master_or_sync_is_running(self):
        timer = self.window.task_tab.schedule_timer
        for tab in (self.window.task_tab, self.window.sync_tab):
            for active in (True, False):
                with self.subTest(tab=type(tab).__name__, timer_active=active):
                    timer.start() if active else timer.stop()
                    tab.is_running = True
                    try:
                        with (
                            patch("src.ui.main_window.launch_installer") as launch,
                            patch("src.ui.main_window.QMessageBox.warning") as warning,
                            patch.object(self.window.collect_sync_tab, "stop_all") as stop,
                        ):
                            self.assertFalse(self.window._launch_update_installer("fixture-not-executed.exe"))
                        warning.assert_called_once()
                        launch.assert_not_called()
                        stop.assert_not_called()
                        self.assertEqual(timer.isActive(), active)
                    finally:
                        tab.is_running = False

    def test_refused_installer_launch_keeps_timer_active_and_never_launches(self):
        tab = self.window.collect_sync_tab
        worker = Mock()
        worker.wait.return_value = False
        tab.worker, tab.is_running = worker, True
        self.window.task_tab.schedule_timer.start()
        try:
            with patch("src.ui.main_window.launch_installer") as launch:
                self.assertFalse(
                    self.window._launch_update_installer("fixture-not-executed.exe")
                )
            launch.assert_not_called()
            self.assertTrue(self.window.task_tab.schedule_timer.isActive())
        finally:
            tab.worker, tab.is_running = None, False

    def test_sync_confirmation_modal_prevents_collect_scheduler_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "target"
            source.mkdir()
            target.mkdir()
            group = new_collect_group("g")
            group.update(
                sources=[str(source)],
                keywords=["report"],
                target=str(target),
                schedule_enabled=True,
            )
            collect = self.window.collect_sync_tab
            collect.groups = [group]
            collect.state_path = root / "state.json"
            observed = []

            def ask(*_args):
                dialog = QDialog(self.window)

                def tick():
                    observed.append(
                        collect.check_scheduled_run(wall_time(2026, 10, 27, 12))
                    )
                    dialog.reject()

                QTimer.singleShot(0, tick)
                dialog.exec()
                dialog.deleteLater()
                return False

            self.window.sync_tab._analysis_is_current = True
            self.window.sync_tab._analysis_has_actions = True
            with (
                patch.object(
                    self.window.sync_tab, "_valid_groups", return_value=[group]
                ),
                patch.object(
                    self.window.sync_tab, "build_run_config", return_value=object()
                ),
                patch("src.ui.sync_tab.confirm_run_summary", side_effect=ask),
            ):
                self.window.sync_tab.start_sync_execution()
            collect.stop_all()
            self.assertEqual(observed, [False])
            self.assertNotIn("schedule_attempt_count", group)
            self.assertFalse(self.window.sync_tab.is_running)


class CollectSyncTableSortingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = MemoryConfig()
        self.config.values["collect_sync_groups"] = [
            {"id": "g1", "name": "Group 1", "sources": [], "keywords": ["*"], "target": "dest"}
        ]
        self.tab = CollectSyncTab(self.config)
        self.tab.state_path = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tab.deleteLater()
        self.tmp.cleanup()

    def test_sorting_disabled_on_qtablewidget_directly(self):
        """Qt table-level sorting should stay disabled to prevent incremental insertion races."""
        self.assertFalse(self.tab.table.isSortingEnabled())
        self.assertTrue(self.tab.table.horizontalHeader().sectionsClickable())

    def test_sort_header_case_insensitive_and_toggle(self):
        actions = (
            CollectAction(ACTION_COPY, source="C:/path/b.txt", target_name="b.txt"),
            CollectAction(ACTION_COPY, source="C:/path/A.txt", target_name="A.txt"),
            CollectAction(ACTION_COPY, source="C:/path/c.txt", target_name="c.txt"),
        )
        self.tab._last_report = CollectReport(actions=actions)
        self.tab._render_report()

        header = self.tab.table.horizontalHeader()
        # Sort Column 1 (Source) - Ascending
        header.sortIndicatorChanged.emit(1, Qt.SortOrder.AscendingOrder)
        self.assertEqual(
            [self.tab.table.item(r, 1).text() for r in range(3)],
            ["C:/path/A.txt", "C:/path/b.txt", "C:/path/c.txt"]
        )

        # Sort Column 1 (Source) - Descending
        header.sortIndicatorChanged.emit(1, Qt.SortOrder.DescendingOrder)
        self.assertEqual(
            [self.tab.table.item(r, 1).text() for r in range(3)],
            ["C:/path/c.txt", "C:/path/b.txt", "C:/path/A.txt"]
        )

    def test_sort_stability_on_ties(self):
        actions = (
            CollectAction(ACTION_COPY, source="same.txt", target_name="first.txt"),
            CollectAction(ACTION_COPY, source="same.txt", target_name="second.txt"),
            CollectAction(ACTION_COPY, source="same.txt", target_name="third.txt"),
        )
        self.tab._last_report = CollectReport(actions=actions)
        header = self.tab.table.horizontalHeader()

        # Ascending on Column 1 (all keys identical)
        header.sortIndicatorChanged.emit(1, Qt.SortOrder.AscendingOrder)
        self.assertEqual(
            [self.tab.table.item(r, 2).text() for r in range(3)],
            ["first.txt", "second.txt", "third.txt"]
        )

        # Descending on Column 1 (all keys identical - stable tie-breaking preserves report order)
        header.sortIndicatorChanged.emit(1, Qt.SortOrder.DescendingOrder)
        self.assertEqual(
            [self.tab.table.item(r, 2).text() for r in range(3)],
            ["first.txt", "second.txt", "third.txt"]
        )

    def test_sort_with_paging_and_reset_to_first_page(self):
        actions = tuple(
            CollectAction(ACTION_COPY, source=f"file_{i:04d}.txt", target_name=f"file_{i:04d}.txt")
            for i in range(2001)
        )
        self.tab._last_report = CollectReport(actions=actions)
        self.tab._render_report()
        self.tab._change_result_page(1)
        self.assertEqual(self.tab._result_page, 1)

        # Sort Column 1 Descending -> should reset page to 0
        header = self.tab.table.horizontalHeader()
        header.sortIndicatorChanged.emit(1, Qt.SortOrder.DescendingOrder)
        self.assertEqual(self.tab._result_page, 0)
        self.assertEqual(self.tab.table.item(0, 1).text(), "file_2000.txt")

        # Go to last page -> file_0000.txt should be on page 1
        self.tab._change_result_page(1)
        self.assertEqual(self.tab.table.item(0, 1).text(), "file_0000.txt")

    def test_sort_with_duplicate_identical_action_objects(self):
        actions = [CollectAction(ACTION_COPY, source="test.txt", target_name="test.txt")] * 2001
        self.tab._last_report = CollectReport(actions=tuple(actions))
        header = self.tab.table.horizontalHeader()
        header.sortIndicatorChanged.emit(0, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.tab.table.rowCount(), 2000)

    def test_sort_preference_persists_across_clear_and_empty_safe(self):
        # Empty report safe
        header = self.tab.table.horizontalHeader()
        self.tab._last_report = None
        header.sortIndicatorChanged.emit(1, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.tab.table.rowCount(), 0)

        # Set sort preference
        header.sortIndicatorChanged.emit(1, Qt.SortOrder.DescendingOrder)
        self.tab._clear_results()
        self.assertEqual(self.tab._sort_column, 1)
        self.assertEqual(self.tab._sort_order, Qt.SortOrder.DescendingOrder)

        # New report renders with saved sort preference
        actions = (
            CollectAction(ACTION_COPY, source="A.txt"),
            CollectAction(ACTION_COPY, source="Z.txt"),
        )
        self.tab._last_report = CollectReport(actions=actions)
        self.tab._render_report()
        self.assertEqual(self.tab.table.item(0, 1).text(), "Z.txt")
        self.assertEqual(self.tab.table.item(1, 1).text(), "A.txt")


if __name__ == "__main__":
    unittest.main()
