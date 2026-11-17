"""Preset imports must update both the settings file and open editors."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.ui.main_window import MainWindow


class PresetUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with (
            patch("src.utils.config_manager.user_data_dir", return_value=self.root),
            patch.object(MainWindow, "trigger_update_check"),
            patch.object(MainWindow, "setup_system_tray"),
        ):
            self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.task = self.window.task_tab
        self.task.schedule_timer.stop()
        self.task.run_health_timer.stop()
        self.config = self.window.config_manager

    def import_settings(self, settings, *, answer=QMessageBox.StandardButton.Yes):
        preset = self.root / "preset.json"
        preset.write_text(json.dumps({"settings": settings}), encoding="utf-8")
        with (
            patch("src.ui.task_tab.QFileDialog.getOpenFileName", return_value=(str(preset), "")),
            patch("src.ui.task_tab.QMessageBox.information") as success,
            patch("src.ui.task_tab.QMessageBox.critical") as failure,
            patch("src.ui.task_tab.QMessageBox.question", return_value=answer) as confirm,
        ):
            self.task.import_preset()
        return success, failure, confirm

    def test_sync_editor_never_overwrites_import_with_stale_group_on_edit(self):
        groups = [
            {"id": "preset", "name": "Preset folder group", "folders": []},
            {"id": "other", "name": "Other group", "folders": []},
        ]
        ok, error, confirm = self.import_settings({"sync_groups": groups})

        ok.assert_called_once()
        error.assert_not_called()
        confirm.assert_not_called()
        sync = self.window.sync_tab
        self.assertEqual(sync.group_combo.currentText(), groups[0]["name"])
        self.assertEqual(self.config.get("sync_groups"), groups)
        with patch("src.ui.sync_tab.QInputDialog.getText", return_value=("Renamed preset group", True)):
            sync.rename_group()
        saved = json.loads(Path(self.config.config_path).read_text(encoding="utf-8"))["sync_groups"]
        self.assertEqual([(group["id"], group["name"]) for group in saved], [
            ("preset", "Renamed preset group"), ("other", "Other group"),
        ])

    def test_reload_updates_current_selection_and_editors_without_activating_automation(self):
        self.assertTrue(self.config.set("smtp_server", "existing.example"))
        original_email = self.task.check_auto_email.isChecked()
        ok, error, confirm = self.import_settings({
            "task_enabled_items": {"eml": True},
            "task_schedule_time": "07:45",
            "task_schedule_enabled": True,
            "task_folder_watch_enabled": True,
            "task_schedule_allow_source_backup": True,
            "task_auto_email": not original_email,
            "smtp_server": "imported.example",
            "collect_sync_groups": [{
                "id": "imported",
                "name": "Collection preset",
                "sources": [],
                "target": "",
                "keywords": [],
                "schedule_enabled": True,
                "schedule_last_result": "running",
            }],
            "eml_tasks": [{"name": "Mail preset", "source_folder": "", "target_folder": ""}],
            "output_folder": str(self.root / "pdf"),
            "ocr_rule_mode": "custom_regex",
            "ocr_custom_pattern": "[A-Z]+",
            "bypass_output_mode": "custom",
        })

        ok.assert_called_once()
        error.assert_not_called()
        confirm.assert_not_called()
        self.assertEqual(self.task.schedule_time_edit.time().toString("HH:mm"), "07:45")
        self.assertTrue(self.task.item_checks["eml"].isChecked())
        self.assertFalse(self.task.check_schedule.isChecked())
        self.assertFalse(self.config.get("task_schedule_enabled"))
        self.assertFalse(self.config.get("task_folder_watch_enabled", False))
        self.assertFalse(self.config.get("task_schedule_allow_source_backup"))
        self.assertIsNone(self.task.folder_watcher)
        self.assertEqual(self.task.check_auto_email.isChecked(), original_email)
        self.assertEqual(self.config.get("smtp_server"), "existing.example")
        self.assertNotIn("schedule_enabled", self.config.get("collect_sync_groups")[0])
        self.assertNotIn("schedule_last_result", self.config.get("collect_sync_groups")[0])
        self.assertEqual(self.window.collect_sync_tab.group_combo.currentText(), "Collection preset")
        self.assertEqual(self.window.eml_tab.table_widget.item(0, 0).text(), "Mail preset")
        self.assertEqual(self.window.pdf_tab.output_path_input.text(), str(self.root / "pdf"))
        self.assertEqual(self.window.ocr_tab.custom_regex_input.text(), "[A-Z]+")
        self.assertTrue(self.window.bypass_tab.radio_custom.isChecked())

    def test_confirmation_cancellation_does_not_replace_active_workflow(self):
        self.assertTrue(self.config.set("task_schedule_enabled", True))
        with QSignalBlocker(self.task.check_schedule):
            self.task.check_schedule.setChecked(True)
        after_setup = Path(self.config.config_path).read_bytes()
        ok, error, confirm = self.import_settings(
            {"task_schedule_time": "07:45"}, answer=QMessageBox.StandardButton.No,
        )

        confirm.assert_called_once()
        ok.assert_not_called()
        error.assert_not_called()
        self.assertEqual(Path(self.config.config_path).read_bytes(), after_setup)

    def test_active_fallback_watcher_requires_same_sync_roots(self):
        old_groups = [{"id": "old", "name": "Old", "folders": [str(self.root / "old")]}]
        self.assertTrue(self.config.set("sync_groups", old_groups))
        with patch("src.ui.task_tab.FolderWatcher.start"):
            self.assertTrue(self.task.start_folder_watcher())
        self.addCleanup(self.task.stop_folder_watcher)

        with patch("src.ui.task_tab.QMessageBox.warning") as warning:
            ok, error, confirm = self.import_settings({
                "sync_groups": [{"id": "new", "name": "New", "folders": [str(self.root / "new")]}],
            })
        warning.assert_called_once()
        ok.assert_not_called()
        error.assert_not_called()
        confirm.assert_not_called()
        self.assertEqual(self.config.get("sync_groups"), old_groups)

        renamed = [{**old_groups[0], "name": "Renamed (same monitored roots)"}]
        ok, error, confirm = self.import_settings({"sync_groups": renamed})
        confirm.assert_called_once()
        ok.assert_called_once()
        error.assert_not_called()
        self.assertEqual(self.config.get("sync_groups"), renamed)

    def test_explicit_watcher_roots_do_not_restrict_sync_import(self):
        folder = str(self.root / "separate-watched-folder")
        with patch("src.ui.task_tab.FolderWatcher.start"):
            self.assertTrue(self.task.start_folder_watcher([folder]))
        self.addCleanup(self.task.stop_folder_watcher)
        watcher = self.task.folder_watcher
        groups = [{"id": "new", "name": "New", "folders": [str(self.root / "new")]}]
        ok, error, confirm = self.import_settings({"sync_groups": groups})

        confirm.assert_called_once()
        ok.assert_called_once()
        error.assert_not_called()
        self.assertIs(self.task.folder_watcher, watcher)
        self.assertEqual(watcher.watch_folders, [folder])
        self.assertEqual(self.config.get("sync_groups"), groups)

    def test_file_events_continue_during_picker_and_defer_during_import_confirmation(self):
        preset = self.root / "preset.json"
        preset.write_text(json.dumps({"task_schedule_time": "07:45"}), encoding="utf-8")
        with patch("src.ui.task_tab.FolderWatcher.start"):
            self.assertTrue(self.task.start_folder_watcher([str(self.root)]))
        self.addCleanup(self.task.stop_folder_watcher)

        def pick_file(*_args, **_kwargs):
            self.task._handle_folder_watcher_files(["during picker"])
            start.assert_called_once_with(scheduled=True)
            return str(preset), ""

        def confirm(*_args, **_kwargs):
            self.task._handle_folder_watcher_files(["during approval"])
            start.assert_called_once_with(scheduled=True)
            return QMessageBox.StandardButton.No

        with (
            patch.object(self.task, "start_all_tasks") as start,
            patch("src.ui.task_tab.QFileDialog.getOpenFileName", side_effect=pick_file),
            patch("src.ui.task_tab.QMessageBox.question", side_effect=confirm),
            patch("src.ui.task_tab.QTimer.singleShot") as dispatch,
        ):
            self.task.import_preset()
            dispatch.assert_called_once()
            dispatch.call_args.args[1]()
            self.assertEqual(start.call_count, 2)

    def test_reload_error_rolls_back_stored_and_displayed_configuration(self):
        original_settings = self.config.get("sync_groups")
        original_combo = self.window.sync_tab.group_combo.currentText()
        ok, error, _ = self.import_settings({
            "sync_groups": [{"id": "new", "name": "New group", "folders": []}],
            "ocr_rule_mode": "invalid",
        })

        ok.assert_not_called()
        error.assert_called_once()
        self.assertEqual(self.config.get("sync_groups"), original_settings)
        self.assertEqual(self.window.sync_tab.group_combo.currentText(), original_combo)
        self.assertFalse(self.task._preset_runtime_blocked)

    def test_failed_rollback_cannot_leave_scheduler_and_watcher_running(self):
        self.task.schedule_timer.start()
        with (
            patch.object(self.config, "update", side_effect=[True, False]),
            patch.object(self.window, "_refresh_preset_tabs", side_effect=RuntimeError("reload failed")),
            patch.object(self.task, "stop_folder_watcher") as stop_watcher,
        ):
            ok, error, _ = self.import_settings({"task_schedule_time": "07:45"})

        ok.assert_not_called()
        error.assert_called_once()
        stop_watcher.assert_called_once()
        self.assertTrue(self.task._preset_runtime_blocked)
        self.assertFalse(self.task.schedule_timer.isActive())
        self.assertFalse(self.task.check_scheduled_run())
        with patch.object(self.task, "start_all_tasks") as start:
            self.task._handle_folder_watcher_files(["queued"])
        start.assert_not_called()

    def test_completion_uses_durable_inline_result_and_keeps_failure_popup(self):
        with patch("src.ui.task_tab.QMessageBox.information") as info:
            self.task.on_tasks_finished(True, "Done processing test files", "")
        info.assert_not_called()
        self.assertIn("Done processing test files", self.task.detail_label.text())
        with patch("src.ui.task_tab.QMessageBox.critical") as critical:
            self.task.on_tasks_finished(False, "Test failure", "")
        critical.assert_called_once()


if __name__ == "__main__":
    unittest.main()
