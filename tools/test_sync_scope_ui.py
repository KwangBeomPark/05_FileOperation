"""Tests for the manual folder-sync scope and staged action."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from src.core.task_contracts import TaskStep, TaskValidationError
from src.ui.sync_tab import SyncTab, SyncWorker


class MemoryConfig:
    def __init__(self, groups):
        self.values = {"ui_language": "ko", "sync_groups": groups}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = copy.deepcopy(value)
        return True


class SyncScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.left = root / "first"
        self.right = root / "second"
        self.left.mkdir()
        self.right.mkdir()
        self.ready = {"id": "ready", "name": "Ready", "folders": [str(self.left), str(self.right)]}
        self.empty = {"id": "empty", "name": "Empty", "folders": []}
        self.draft = {"id": "draft", "name": "Draft", "folders": [str(self.left)]}

    def make_tab(self, groups):
        config = MemoryConfig(copy.deepcopy(groups))
        tab = SyncTab(config)
        self.addCleanup(tab.close)
        return tab, config

    def test_incomplete_group_blocks_both_manual_paths_without_hiding_the_group(self):
        tab, _ = self.make_tab([self.ready, self.empty, self.draft])
        self.assertIn("편집 중인 그룹", tab.editing_group_label.text())
        self.assertEqual(tab.group_combo.currentText(), "Ready")
        self.assertIn("전체 그룹", tab.sync_scope_label.text())
        self.assertIn("빈 그룹 1개 제외", tab.sync_scope_label.text())
        self.assertIn("Draft", tab.action_hint_label.text())
        self.assertFalse(tab.analyze_btn.isEnabled())

        with (patch("src.ui.sync_tab.QMessageBox.warning") as warning,
              patch("src.ui.sync_tab.SyncWorker") as worker,
              patch("src.ui.sync_tab.confirm_run_summary") as confirm):
            tab.start_dry_run()
            tab.start_sync_execution()
        self.assertEqual(warning.call_count, 2)
        self.assertEqual(warning.call_args_list[0].args[2], warning.call_args_list[1].args[2])
        worker.assert_not_called()
        confirm.assert_not_called()
        # A selected scheduled group is still validated independently.
        self.assertEqual(tab.build_run_config(["ready"]).sync_groups[0].name, "Ready")
        with self.assertRaises(TaskValidationError):
            tab.build_run_config()

    def test_paths_are_checked_in_preview_worker_not_on_gui_thread(self):
        group = {**self.ready, "folders": [str(self.left), str(self.right / "missing")]}
        tab, config = self.make_tab([group])
        with (patch("src.ui.sync_tab._validate_group_paths") as validate,
              patch("src.ui.sync_tab.SyncWorker") as worker):
            tab.start_dry_run()
        validate.assert_not_called()
        worker.return_value.start.assert_called_once()
        snapshot = worker.call_args.args[0]

        preview = SyncWorker(snapshot, config)
        completed, failures = [], []
        preview.dry_run_finished.connect(completed.append)
        preview.finished.connect(lambda *args: failures.append(args))
        preview.run()
        self.assertFalse(completed)
        self.assertEqual(len(failures), 1)
        self.assertIn("Ready", failures[0][3][0])
        self.assertIn("missing", failures[0][3][0])

    def test_invalid_exclude_patterns_cannot_crash_preview_or_widen_scope(self):
        for patterns in (None, "*.tmp", ["*.tmp", 3]):
            with self.subTest(patterns=patterns):
                tab, _ = self.make_tab([{**self.ready, "exclude_patterns": patterns}])
                with (patch("src.ui.sync_tab.QMessageBox.warning") as warning,
                      patch("src.ui.sync_tab.SyncWorker") as worker):
                    tab.start_dry_run()
                    tab.start_sync_execution()
                self.assertEqual(warning.call_count, 2)
                self.assertIn("Ready", warning.call_args.args[2])
                self.assertIn("제외 패턴", warning.call_args.args[2])
                worker.assert_not_called()

    def test_full_preview_and_refresh_remain_available_when_run_becomes_primary(self):
        tab, _ = self.make_tab([self.ready, self.empty])
        self.assertTrue(tab.sync_btn.isHidden())
        self.assertEqual(tab.analyze_btn.text(), "변경 내용 보기")
        self.assertTrue(tab.stop_btn.isHidden())
        actions = [
            {"group_name": "Ready", "filename": f"{index}.txt", "action": "복사",
             "source_folder": str(self.left), "target_folder": str(self.right)}
            for index in range(205)
        ]
        with patch("src.ui.sync_tab.show_toast"):
            tab.on_dry_run_finished(actions)
        self.assertEqual(tab.table_widget.rowCount(), 205)
        self.assertFalse(tab.sync_btn.isHidden())
        self.assertTrue(tab.sync_btn.isEnabled())
        self.assertEqual(tab.sync_btn.text(), "1개 그룹 동기화")
        self.assertTrue(tab.analyze_btn.isEnabled())
        self.assertEqual(tab.analyze_btn.text(), "다시 미리보기")

        with (patch("src.ui.sync_tab.confirm_run_summary", return_value=False) as review,
              patch("src.ui.sync_tab.SyncWorker") as worker):
            tab.start_sync_execution()
        worker.assert_not_called()
        plan = review.call_args.args[1].get(TaskStep.SYNC)
        self.assertEqual([group.name for group in plan.sync_groups], ["Ready"])
        self.assertTrue(tab.sync_btn.isEnabled())
        self.assertTrue(tab.analyze_btn.isEnabled())

    def test_no_write_reload_updates_group_and_invalidates_old_preview(self):
        tab, config = self.make_tab([self.ready])
        tab._analysis_is_current = True
        tab._analysis_has_actions = True
        tab.table_widget.setRowCount(1)
        incoming = {**self.ready, "id": "incoming", "name": "Imported"}
        config.values["sync_groups"] = [incoming]
        with patch.object(config, "set", wraps=config.set) as save:
            self.assertTrue(tab.load_saved_data(persist=False))
        save.assert_not_called()
        self.assertEqual(tab.group_combo.currentText(), "Imported")
        self.assertEqual(tab.table_widget.rowCount(), 0)
        self.assertFalse(tab._analysis_is_current)
        self.assertTrue(tab.sync_btn.isHidden())


if __name__ == "__main__":
    unittest.main()
