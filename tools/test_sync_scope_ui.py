"""Tests for the manual folder-sync scope and staged action."""

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from src.core.task_contracts import TaskValidationError
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
              patch("src.ui.sync_tab.SyncWorker") as worker):
            tab.start_dry_run()
            tab.start_sync_execution()
        self.assertEqual(warning.call_count, 2)
        self.assertEqual(warning.call_args_list[0].args[2], warning.call_args_list[1].args[2])
        worker.assert_not_called()
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
        preview.dry_run_finished.connect(lambda *args: completed.append(args))
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
            tab.on_dry_run_finished(actions, ("preview",))
        self.assertEqual(tab.table_widget.rowCount(), 205)
        self.assertFalse(tab.sync_btn.isHidden())
        self.assertTrue(tab.sync_btn.isEnabled())
        self.assertEqual(tab.sync_btn.text(), "1개 그룹 동기화")
        self.assertTrue(tab.analyze_btn.isEnabled())
        self.assertEqual(tab.analyze_btn.text(), "다시 미리보기")

        with patch("src.ui.sync_tab.SyncWorker") as worker:
            tab.start_sync_execution()
        worker.return_value.start.assert_called_once()
        self.assertEqual([group["name"] for group in worker.call_args.args[0]], ["Ready"])
        self.assertEqual(worker.call_args.kwargs["preview_fingerprints"], ("preview",))
        self.assertFalse(tab.sync_btn.isEnabled())
        self.assertFalse(tab.analyze_btn.isEnabled())

    def test_green_button_runs_the_preview_without_confirmation(self):
        tab, _ = self.make_tab([self.ready])
        source = self.left / "report.txt"
        source.write_text("previewed", encoding="utf-8")
        with (patch("src.ui.sync_tab.QMessageBox") as popup,
              patch("src.ui.sync_tab.show_toast")):
            tab.analyze_btn.click()
            self.assertTrue(tab.worker.wait(10000))
            self.app.processEvents()
            self.assertFalse((self.right / source.name).exists())
            self.assertTrue(tab.sync_btn.isEnabled())
            self.assertIn("신규 복사 1건", tab.plan_summary_label.text())
            tab.sync_btn.click()
            self.assertTrue(tab.worker.wait(10000))
            self.app.processEvents()
        self.assertEqual((self.right / source.name).read_text(encoding="utf-8"), "previewed")
        self.assertEqual(popup.mock_calls, [])
        self.assertFalse(tab.is_running)

    def test_date_version_preview_shows_archive_destination_and_runs_without_confirmation(self):
        tab, _ = self.make_tab([{**self.ready, "date_latest_only": True, "archive_folder_name": "old"}])
        (self.left / "report_v20261125.txt").write_text("new", encoding="utf-8")
        (self.right / "report_v20261101.txt").write_text("old", encoding="utf-8")
        with (patch.object(SyncWorker, "start", new=SyncWorker.run),
              patch("src.ui.sync_tab.QMessageBox") as popup,
              patch("src.ui.sync_tab.show_toast")):
            tab.analyze_btn.click()
            self.assertIn("보관 1건", tab.plan_summary_label.text())
            self.assertIn(str(self.right / "old"), [tab.table_widget.item(i, 4).toolTip()
                                                     for i in range(tab.table_widget.rowCount())])
            tab.sync_btn.click()
        self.assertEqual((self.right / "report_v20261125.txt").read_text(encoding="utf-8"), "new")
        self.assertEqual((self.right / "old" / "report_v20261101.txt").read_text(encoding="utf-8"), "old")
        self.assertFalse((self.right / "report_v20261101.txt").exists())
        self.assertEqual(popup.mock_calls, [])

    def test_changed_later_group_blocks_earlier_group_before_any_write(self):
        later_left = self.left.parent / "later-left"
        later_right = self.left.parent / "later-right"
        later_left.mkdir()
        later_right.mkdir()
        later = {"id": "later", "name": "Later", "folders": [str(later_left), str(later_right)]}
        tab, _ = self.make_tab([self.ready, later])
        (self.left / "first.txt").write_text("previewed", encoding="utf-8")
        source = later_left / "second.txt"
        source.write_text("previewed", encoding="utf-8")
        with (patch.object(SyncWorker, "start", new=SyncWorker.run),
              patch("src.ui.sync_tab.QMessageBox") as popup):
            tab.analyze_btn.click()
            source.write_text("changed after preview", encoding="utf-8")
            tab.sync_btn.click()
        self.assertEqual(list(self.right.iterdir()), [])
        self.assertEqual(list(later_right.iterdir()), [])
        self.assertIn("실행하지 않았습니다", tab.plan_summary_label.text())
        self.assertFalse(tab.sync_btn.isEnabled())
        self.assertTrue(tab.analyze_btn.isEnabled())
        self.assertEqual(popup.mock_calls, [])

    def test_settings_change_without_editor_signal_still_blocks_execution(self):
        tab, _ = self.make_tab([self.ready])
        (self.left / "first.txt").write_text("previewed", encoding="utf-8")
        with patch.object(SyncWorker, "start", new=SyncWorker.run):
            tab.analyze_btn.click()
            tab.sync_groups[0]["sync_mode"] = "one_way"
            tab.sync_btn.click()
        self.assertEqual(list(self.right.iterdir()), [])
        self.assertIn("실행하지 않았습니다", tab.plan_summary_label.text())

    def test_new_target_after_preview_is_neither_replaced_nor_archived(self):
        tab, _ = self.make_tab([{**self.ready, "sync_mode": "one_way"}])
        (self.left / "report.txt").write_text("source", encoding="utf-8")
        destination = self.right / "report.txt"
        with patch.object(SyncWorker, "start", new=SyncWorker.run):
            tab.analyze_btn.click()
            destination.write_text("created after preview", encoding="utf-8")
            tab.sync_btn.click()
        self.assertEqual(destination.read_text(encoding="utf-8"), "created after preview")
        self.assertEqual(list(self.right.iterdir()), [destination])
        self.assertIn("실행하지 않았습니다", tab.plan_summary_label.text())

    def test_office_lock_files_are_never_planned_and_do_not_invalidate_the_preview(self):
        for date_mode, nested in ((False, False), (False, True), (True, True)):
            with self.subTest(date_mode=date_mode, nested=nested):
                left = self.left / f"{date_mode}-{nested}"
                right = self.right / f"{date_mode}-{nested}"
                left.mkdir()
                right.mkdir()
                source_parent = left / "~$reports" if nested else left
                target_parent = right / "~$reports" if nested else right
                if nested:
                    source_parent.mkdir()
                    target_parent.mkdir()
                document = "report_v20261125.xlsx"
                (source_parent / document).write_bytes(b"workbook")
                lock = source_parent / f"~${document}"
                lock.write_bytes(b"Office owner file")
                tab, _ = self.make_tab([{
                    **self.ready, "folders": [str(left), str(right)], "exclude_patterns": ["*.bak"],
                    "date_latest_only": date_mode, "include_subfolders": nested,
                }])
                with (patch.object(SyncWorker, "start", new=SyncWorker.run),
                      patch("src.ui.sync_tab.QMessageBox") as popup,
                      patch("src.ui.sync_tab.show_toast")):
                    tab.analyze_btn.click()
                    self.assertEqual(tab.table_widget.rowCount(), 1)
                    self.assertEqual(tab.table_widget.item(0, 1).text(), os.path.relpath(source_parent / document, left))
                    lock.unlink()
                    (target_parent / lock.name).write_bytes(b"target owner file")
                    # Make the directory timestamp change observable even on coarse/network-like clocks.
                    for directory in (source_parent, target_parent):
                        info = directory.stat()
                        os.utime(directory, ns=(info.st_atime_ns, info.st_mtime_ns + 10_000_000_000))
                    tab.sync_btn.click()
                self.assertEqual((target_parent / document).read_bytes(), b"workbook")
                self.assertEqual((target_parent / lock.name).read_bytes(), b"target owner file")
                self.assertFalse(lock.exists())
                self.assertEqual(popup.mock_calls, [])

    def test_replaced_destination_folder_still_invalidates_preview(self):
        tab, _ = self.make_tab([self.ready])
        (self.left / "report.xlsx").write_bytes(b"workbook")
        moved = self.right.with_name("original-destination")
        with patch.object(SyncWorker, "start", new=SyncWorker.run):
            tab.analyze_btn.click()
            self.right.rename(moved)
            self.right.mkdir()
            tab.sync_btn.click()
        self.assertFalse((self.right / "report.xlsx").exists())
        self.assertFalse((moved / "report.xlsx").exists())
        self.assertIn("실행하지 않았습니다", tab.plan_summary_label.text())

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
