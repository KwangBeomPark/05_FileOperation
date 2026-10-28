"""Master selection, sequential execution, cancellation and integrated history."""

import copy
import json
import os
import tempfile
import threading
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QMainWindow,
    QPlainTextEdit,
    QTabWidget,
)

from src.core.collect_sync_config import build_collect_group, new_collect_group
from src.core.preflight import PreflightReport
from src.core.task_contracts import (
    CollectRunConfig,
    ExecutionItem,
    RunPlan,
    RunReport,
    StepResult,
    StepStatus,
    SyncGroupConfig,
    SyncRunConfig,
    TaskStep,
)
from src.core.task_items import migrate_task_selection
from src.core.task_runner import RunnerCallbacks, TaskRunner
from src.ui.collect_sync_tab import CollectSyncTab
from src.ui.sync_tab import SyncTab
from src.ui.task_tab import TaskTab
from tools.test_collect_sync_config import wall_time
from tools.test_collect_sync_ui import MemoryConfig, wait_until


class MasterTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.target = self.root / "source", self.root / "target"
        self.source.mkdir()
        self.target.mkdir()
        (self.source / "report.txt").write_text("contents", encoding="utf-8")
        collect = new_collect_group("Collect daily")
        collect.update(
            sources=[str(self.source)],
            target=str(self.target),
            keywords=["report"],
            schedule_enabled=True,
        )
        self.config = MemoryConfig([collect])
        self.config.app_dir = str(self.root)
        self.config.values.update(
            task_auto_email=False,
            task_schedule_enabled=True,
            task_enabled_steps=["sync", "bypass"],
            sync_groups=[
                {
                    "name": "Folder daily",
                    "folders": [str(self.source), str(self.root / "mirror")],
                }
            ],
        )
        (self.root / "mirror").mkdir()
        self.window = QMainWindow()
        self.tabs = QTabWidget()
        self.window.setCentralWidget(self.tabs)
        self.window.sync_tab = SyncTab(self.config)
        # Scheduler tests drive the clock explicitly; migration now enables the
        # master schedule and its queued startup tick must not run fixture work.
        with patch.object(TaskTab, "_on_schedule_tick"):
            self.window.task_tab = self.tab = TaskTab(self.config)
        self.window.collect_sync_tab = CollectSyncTab(self.config)
        self.window.collect_sync_tab.state_path = self.root / "collect_sync_state.json"
        for widget in (self.tab, self.window.sync_tab, self.window.collect_sync_tab):
            self.tabs.addTab(widget, "fixture")
        self.window.select_feature_tab = self.tabs.setCurrentWidget
        self.window.set_all_tabs_locked = Mock()
        self.tab.schedule_timer.stop()
        self.tab.run_health_timer.stop()
        self.app.processEvents()

    def tearDown(self):
        self.tab.stop_all()
        self.window.collect_sync_tab.stop_all()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_migration_and_dynamic_order_exclude_bypass(self):
        sync_id = self.config.get("sync_groups")[0]["id"]
        self.assertTrue(sync_id)
        migrate_task_selection(self.config)
        self.assertEqual(self.config.get("sync_groups")[0]["id"], sync_id)
        self.assertFalse(self.config.get("collect_sync_groups")[0]["schedule_enabled"])
        self.assertEqual(
            [r["step"] for r in self.tab.rows],
            [
                TaskStep.SYNC,
                TaskStep.COLLECT_SYNC,
                TaskStep.EML,
                TaskStep.PDF,
                TaskStep.OCR,
            ],
        )
        self.assertEqual(self.tab.status_table.columnCount(), 8)
        self.assertEqual(
            self.tab.selected_steps(), [TaskStep.SYNC, TaskStep.COLLECT_SYNC]
        )
        self.assertNotIn(TaskStep.BYPASS, self.tab.step_checks)
        collect_tab = self.window.collect_sync_tab
        for name in ("schedule_timer", "schedule_check", "schedule_time"):
            self.assertFalse(hasattr(collect_tab, name))
        self.assertFalse(collect_tab.check_scheduled_run(wall_time(2026, 10, 28, 23)))

    def test_legacy_bypass_notice_is_logged_once_at_startup(self):
        for _ in range(2):
            self.tab.refresh_language()
            self.tab.rebuild_status_table()
            self.tab.refresh_run_list()
        notices = [line for line in self.tab.live_log if "BYPASS" in line]
        self.assertEqual(len(notices), 1)
        self.assertIn("own tab", notices[0])

    def test_exact_headers_order_and_navigation_from_every_column(self):
        for language in ("en", "ko", "pl"):
            self.config.values["ui_language"] = language
            self.tab.refresh_language()
            self.assertEqual(
                [self.tab.status_table.horizontalHeaderItem(i).text() for i in range(8)],
                self.tab.table_headers(),
            )
            self.assertTrue(all(self.tab.table_headers()))
        self.config.values["ui_language"] = "en"
        self.tab.refresh_language()
        self.assertEqual(self.tab.table_headers(), ["Run", "Order", "Type", "Name", "Summary", "Readiness", "Status", "Last Result"])
        for i, row in enumerate(self.tab.rows):
            self.assertEqual(self.tab.status_table.item(i, 1).text(), str(i + 1))
            self.assertEqual(self.tab.status_table.item(i, 3).text(), row["name"])
        for row, feature in ((0, self.window.sync_tab), (1, self.window.collect_sync_tab)):
            for column in range(8):
                self.tabs.setCurrentWidget(self.tab)
                self.tab.status_table.cellDoubleClicked.emit(row, column)
                self.assertIs(self.tabs.currentWidget(), feature)
        self.tabs.setCurrentWidget(self.tab)
        check = self.tab.status_table.cellWidget(1, 0).findChild(QCheckBox)
        QTest.mouseDClick(check, Qt.MouseButton.LeftButton)
        self.assertIs(self.tabs.currentWidget(), self.window.collect_sync_tab)

    def test_new_sync_group_is_persistently_unchecked(self):
        self.window.sync_tab.sync_groups.append({"name": "unattended risk", "folders": []})
        self.window.sync_tab.save_data()
        key = "sync:" + self.window.sync_tab.sync_groups[-1]["id"]
        self.assertIs(self.config.get("task_enabled_items")[key], False)
        self.tab.rebuild_status_table()
        self.assertFalse(self.tab.item_checks[key].isChecked())
        migrate_task_selection(self.config)
        self.assertIs(self.config.get("task_enabled_items")[key], False)

    def test_viewer_search_copy_notepad_and_reports_folder(self):
        text = "alpha needle middle needle 한글"
        self.tab.log(text)
        self.tab.log_search.setText("needle")
        cursor = self.tab.log_area.textCursor()
        self.assertEqual(cursor.selectedText(), "needle")
        first = cursor.selectionStart()
        self.tab.log_search_next_btn.click()
        self.assertGreater(self.tab.log_area.textCursor().selectionStart(), first)
        self.tab.log_search_prev_btn.click()
        self.assertEqual(self.tab.log_area.textCursor().selectionStart(), first)
        self.tab.log_search_prev_btn.click()
        self.assertGreater(self.tab.log_area.textCursor().selectionStart(), first)
        self.tab.log_copy_btn.click()
        self.assertEqual(QApplication.clipboard().text(), self.tab.log_area.toPlainText())
        with patch("src.ui.task_panel.subprocess.Popen") as launch:
            self.tab.log_notepad_btn.click()
            command = launch.call_args.args[0]
            self.assertEqual(command[0], "notepad.exe")
            self.assertEqual(Path(command[1]).read_text(encoding="utf-8-sig"), self.tab.log_area.toPlainText())
        with patch("src.ui.task_panel.QDesktopServices.openUrl", return_value=True) as launch:
            self.tab.log_folder_btn.click()
            self.assertEqual(Path(launch.call_args.args[0].toLocalFile()), self.tab.run_journal.reports_dir)

    def test_large_report_is_complete_and_live_log_is_bounded(self):
        report = "\n".join(f"line {i}" for i in range(20005)) + "\n"
        run_id = self.tab.run_journal.start_run([TaskStep.SYNC], scheduled=False, language="en")
        self.tab.run_journal.finish_run(run_id, RunReport({TaskStep.SYNC: StepResult(TaskStep.SYNC, StepStatus.COMPLETED)}, report, "done", True))
        self.tab.refresh_run_list()
        self.tab.history_list.setCurrentRow(1)
        self.assertEqual(self.tab.log_area.maximumBlockCount(), 0)
        self.assertEqual(self.tab.log_area.toPlainText(), report)
        with patch("src.ui.task_panel.subprocess.Popen") as launch:
            self.tab.log_notepad_btn.click()
            self.assertEqual(Path(launch.call_args.args[0][1]), Path(self.tab.run_journal.report_path(run_id)))
        self.assertIsInstance(self.tab.live_log, deque)
        for i in range(20005):
            self.tab.log(f"live {i}")
        self.assertEqual(len(self.tab.live_log), 20000)
        self.assertEqual(self.tab.live_log[0], "live 5")
        self.assertEqual(self.tab.log_area.toPlainText(), report)
        self.tab.history_list.setCurrentRow(0)
        self.assertEqual(self.tab.log_area.maximumBlockCount(), 20000)
        self.assertTrue(self.tab.log_area.toPlainText().startswith("live 5\n"))

    def test_late_stop_preserves_finished_item_status(self):
        for status in (StepStatus.COMPLETED, StepStatus.PARTIAL, StepStatus.FAILED):
            with self.subTest(status=status):
                items = [ExecutionItem(f"sync:{i}", TaskStep.SYNC, str(i), SyncRunConfig([])) for i in range(2)]
                runner = TaskRunner(self.config, RunPlan(items=items))
                cur_status = status
                cur_runner = runner
                def finish_then_stop(_config, result, _callbacks, s=cur_status, r=cur_runner):
                    result.status = s
                    result.success_count = result.total_count = 1
                    r.cancel()
                runner._run_sync = finish_then_stop
                report = runner.run()
                self.assertEqual(report.item_results["sync:0"].status, status)
                self.assertEqual(report.item_results["sync:1"].status, StepStatus.CANCELLED)

    def test_group_selection_survives_rename_and_reorder_and_navigation_uses_id(self):
        groups = self.window.sync_tab.sync_groups
        second = copy.deepcopy(groups[0])
        second.update(id="second", name="second")
        groups.append(second)
        self.window.sync_tab.save_data()
        self.tab.rebuild_status_table()
        key = self.tab.rows[0]["key"]
        self.tab.item_checks[key].setChecked(False)
        groups[0]["name"] = "renamed"
        groups.reverse()
        self.window.sync_tab.save_data()
        self.window.sync_tab.load_saved_data()
        self.tab.rebuild_status_table()
        self.assertFalse(self.tab.item_checks[key].isChecked())
        self.assertEqual(self.tab.rows[1]["name"], "renamed")
        self.tab.navigate_row(1)
        self.assertIs(self.tabs.currentWidget(), self.window.sync_tab)
        self.assertEqual(self.window.sync_tab.group_combo.currentIndex(), 1)
        self.tab.navigate_row(2)
        self.assertIs(self.tabs.currentWidget(), self.window.collect_sync_tab)

    def test_master_schedule_runs_all_checked_items_once_and_saves_reports(self):
        self.tab.check_schedule.setChecked(True)
        self.tab.schedule_time_edit.setTime(
            self.tab.schedule_time_edit.time().fromString("12:00", "HH:mm")
        )
        order = []
        original_sync = TaskRunner._run_sync
        original_collect = TaskRunner._run_collect_sync

        def sync(runner, config, result, callbacks):
            order.append("sync")
            original_sync(runner, config, result, callbacks)

        def collect(runner, config, result, callbacks):
            order.append("collect")
            original_collect(runner, config, result, callbacks)

        with (
            patch(
                "src.ui.task_tab.run_bounded_preflight",
                return_value=(PreflightReport(language="en"), "", False),
            ),
            patch("src.ui.task_tab.confirm_run_summary", return_value=True),
            patch.object(TaskRunner, "_run_sync", sync),
            patch.object(TaskRunner, "_run_collect_sync", collect),
        ):
            self.assertTrue(
                self.tab.check_scheduled_run(wall_time(2026, 10, 28, 12, 1))
            )
            wait_until(lambda: not self.tab.is_running)
            self.assertFalse(
                self.tab.check_scheduled_run(wall_time(2026, 10, 28, 12, 2))
            )
        self.assertEqual(order, ["sync", "collect"])
        self.assertEqual((self.target / "report.txt").read_text(), "contents")
        entry = self.tab.run_journal.list_runs()[0]
        self.assertTrue(entry["scheduled"])
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(len(entry["item_results"]), 2)
        self.assertIn(
            "Collect daily", Path(entry["report_path"]).read_text(encoding="utf-8")
        )
        self.window.set_all_tabs_locked.assert_any_call(True)
        self.window.set_all_tabs_locked.assert_called_with(False)

    def test_failed_group_continues_to_next_sync_and_collect_and_is_journalled(self):
        sync = SyncRunConfig([SyncGroupConfig("good", ["a", "b"])])
        collect = CollectRunConfig(
            (build_collect_group(self.config.get("collect_sync_groups")[0]),),
            str(self.root / "state.json"),
        )
        items = [
            ExecutionItem("sync:bad", TaskStep.SYNC, "bad", error="unavailable folder"),
            ExecutionItem("sync:good", TaskStep.SYNC, "good", sync),
            ExecutionItem("collect:good", TaskStep.COLLECT_SYNC, "collect", collect),
        ]
        runner = TaskRunner(self.config, RunPlan(items=items))
        order = []

        def successful_sync(_config, result, _callbacks):
            result.status = StepStatus.COMPLETED
            result.success_count = result.total_count = 1

        runner._run_sync = successful_sync
        report = runner.run(
            RunnerCallbacks(
                item_status_changed=lambda key, status: (
                    order.append(key) if status == StepStatus.RUNNING else None
                )
            )
        )
        self.assertEqual(order, [item.key for item in items])
        self.assertEqual(report.item_results["sync:bad"].status, StepStatus.FAILED)
        self.assertEqual(report.item_results["sync:good"].status, StepStatus.COMPLETED)
        self.assertEqual(report.results[TaskStep.SYNC].status, StepStatus.PARTIAL)
        run_id = self.tab.run_journal.start_run(
            [TaskStep.SYNC, TaskStep.COLLECT_SYNC], scheduled=False, language="en"
        )
        self.tab.run_journal.finish_run(run_id, report)
        self.assertEqual(self.tab.run_journal.list_runs()[0]["status"], "partial")

    def test_stop_cancels_remaining_groups_and_keeps_partial_report(self):
        items = [
            ExecutionItem(f"sync:{i}", TaskStep.SYNC, str(i), SyncRunConfig([]))
            for i in range(3)
        ]
        runner = TaskRunner(self.config, RunPlan(items=items))
        seen = []

        def stop_in_first(_config, result, _callbacks):
            seen.append("first")
            result.details.append("finished current file")
            runner.cancel()

        runner._run_sync = stop_in_first
        report = runner.run()
        self.assertEqual(seen, ["first"])
        self.assertTrue(report.cancelled)
        self.assertTrue(
            all(r.status == StepStatus.CANCELLED for r in report.item_results.values())
        )
        self.assertIn("finished current file", report.report_body)

    def test_history_lazy_load_filters_and_live_buffer_are_independent(self):
        run_id = self.tab.run_journal.start_run(
            [TaskStep.COLLECT_SYNC], scheduled=False, language="en"
        )
        result = StepResult(TaskStep.COLLECT_SYNC, StepStatus.COMPLETED)
        self.tab.run_journal.finish_run(
            run_id,
            RunReport({TaskStep.COLLECT_SYNC: result}, "past report", "done", True),
        )
        self.assertIsInstance(self.tab.log_area, QPlainTextEdit)
        self.tab.log("<live> plain text")
        with patch.object(
            Path, "read_text", autospec=True, return_value="past report"
        ) as read:
            self.tab.refresh_run_list()
            read.assert_not_called()
            self.tab.history_list.setCurrentRow(1)
            read.assert_called_once()
        self.assertEqual(self.tab.log_area.toPlainText(), "past report")
        self.tab.log("new live line")
        self.assertEqual(self.tab.log_area.toPlainText(), "past report")
        self.tab.history_list.setCurrentRow(0)
        self.assertIn("new live line", self.tab.log_area.toPlainText())
        self.tab.is_running = True
        with patch.object(Path, "read_text", return_value="past report"):
            self.tab.history_list.setCurrentRow(1)
            self.tab.log("running while reading history")
            self.assertEqual(self.tab.history_list.currentRow(), 1)
            self.assertEqual(self.tab.log_area.toPlainText(), "past report")
            self.tab.refresh_run_list()
            self.assertEqual(self.tab.history_list.currentRow(), 1)
            self.assertEqual(self.tab.log_area.toPlainText(), "past report")
        self.tab.history_list.setCurrentRow(0)
        self.assertIn("running while reading history", self.tab.log_area.toPlainText())
        self.tab.log("live again")
        self.assertIn("live again", self.tab.log_area.toPlainText())
        self.tab.is_running = False
        self.tab.type_filter.setCurrentIndex(self.tab.type_filter.findData("sync"))
        self.assertEqual(self.tab.history_list.count(), 1)
        self.tab.type_filter.setCurrentIndex(
            self.tab.type_filter.findData("collect_sync")
        )
        self.assertEqual(self.tab.history_list.count(), 2)
        self.tab.status_filter.setCurrentIndex(
            self.tab.status_filter.findData("failed")
        )
        self.assertEqual(self.tab.history_list.count(), 1)
        self.tab.is_running = True
        self.tab.log("running now")
        self.assertEqual(self.tab.history_list.currentRow(), 0)
        self.tab.is_running = False

    def test_manual_collect_produces_shared_history_but_preview_does_not(self):
        collect = self.window.collect_sync_tab
        self.assertTrue(collect.start_dry_run())
        wait_until(lambda: not collect.is_running)
        self.assertEqual(self.tab.run_journal.list_runs(), [])
        self.assertTrue(collect._start())
        wait_until(lambda: not collect.is_running)
        entry = self.tab.run_journal.list_runs()[0]
        self.assertEqual(entry["active_steps"], ["collect_sync"])
        self.assertEqual(entry["status"], "completed")
        self.assertTrue(Path(entry["report_path"]).is_file())
        self.tab.refresh_run_list()
        self.assertEqual(self.tab.history_list.count(), 2)

    def test_stop_button_cancels_remaining_collect_and_waits_for_thread_exit(self):
        entered, released = threading.Event(), threading.Event()

        def hold_sync(runner, _config, result, _callbacks):
            entered.set()
            self.assertTrue(released.wait(5))
            result.details.append("current file finished safely")

        with (
            patch(
                "src.ui.task_tab.run_bounded_preflight",
                return_value=(PreflightReport(language="en"), "", False),
            ),
            patch("src.ui.task_tab.confirm_run_summary", return_value=True),
            patch.object(TaskRunner, "_run_sync", hold_sync),
        ):
            self.assertTrue(self.tab.start_all_tasks(scheduled=True))
            wait_until(entered.is_set)
            worker = self.tab.worker
            thread_stopped = []
            worker.finished.connect(lambda: thread_stopped.append(True))
            self.tab.stop_tasks()
            self.assertFalse(self.tab.stop_btn.isEnabled())
            self.assertTrue(self.tab.is_running)
            released.set()
            wait_until(lambda: not self.tab.is_running)
            self.assertTrue(thread_stopped)
            self.assertIsNone(self.tab.worker)
        self.assertFalse((self.target / "report.txt").exists())
        entry = self.tab.run_journal.list_runs()[0]
        self.assertEqual(entry["status"], "cancelled")
        self.assertTrue(
            all(
                result["status"] == "cancelled"
                for result in entry["item_results"].values()
            )
        )

    def test_worker_construction_failure_restores_ui_and_finalizes_journal(self):
        with (
            patch(
                "src.ui.task_tab.run_bounded_preflight",
                return_value=(PreflightReport(language="en"), "", False),
            ),
            patch("src.ui.task_tab.confirm_run_summary", return_value=True),
            patch(
                "src.ui.task_tab.TaskWorker",
                side_effect=RuntimeError("constructor failed"),
            ),
        ):
            self.assertFalse(self.tab.start_all_tasks(scheduled=True))
        self.assertFalse(self.tab.is_running)
        self.assertTrue(self.tab.start_btn.isEnabled())
        self.assertEqual(self.tab.run_journal.list_runs()[0]["status"], "failed")
        self.window.set_all_tabs_locked.assert_called_with(False)

    def test_one_dependency_blocker_is_recorded_without_blocking_independent_tasks(
        self,
    ):
        from src.core.task_contracts import OcrRunConfig

        self.window.ocr_tab = Mock()
        self.window.ocr_tab.build_run_config.return_value = OcrRunConfig([])
        self.tab.item_checks["ocr"].setChecked(True)
        preflight = PreflightReport(language="en")
        preflight.add_blocker("No OCR engine", step=TaskStep.OCR)
        with (
            patch(
                "src.ui.task_tab.run_bounded_preflight",
                return_value=(preflight, "", False),
            ),
            patch("src.ui.task_tab.confirm_run_summary", return_value=True),
        ):
            self.assertTrue(self.tab.start_all_tasks(scheduled=True))
            wait_until(lambda: not self.tab.is_running)
        entry = self.tab.run_journal.list_runs()[0]
        self.assertEqual(entry["status"], "partial")
        self.assertEqual(entry["results"]["ocr"]["status"], "failed")
        self.assertEqual(entry["results"]["collect_sync"]["status"], "completed")

    def test_all_blocked_tasks_are_rejected_before_worker_or_confirmation(self):
        for scheduled in (False, True):
            for global_blocker in (False, True):
                with self.subTest(scheduled=scheduled, global_blocker=global_blocker):
                    preflight = PreflightReport(language="en")
                    if global_blocker:
                        preflight.add_blocker("Global safety blocker")
                    else:
                        for step in self.tab.selected_steps():
                            preflight.add_blocker("Dependency unavailable", step=step)
                    with (
                        patch("src.ui.task_tab.run_bounded_preflight", return_value=(preflight, "", False)),
                        patch("src.ui.task_tab.TaskWorker") as worker,
                        patch("src.ui.task_tab.confirm_run_summary") as confirm,
                        patch("src.ui.task_tab.QMessageBox.warning") as warning,
                    ):
                        self.assertFalse(self.tab.start_all_tasks(scheduled=scheduled))
                    worker.assert_not_called()
                    confirm.assert_not_called()
                    self.assertEqual(warning.call_count, 0 if scheduled else 1)
                    self.assertIn("blocker" if global_blocker else "No runnable tasks", self.tab.start_failure_reason)
                    self.assertIn(self.tab.start_failure_reason, "\n".join(self.tab.live_log))
                    self.assertFalse(self.tab.is_running)
                    self.assertIsNone(self.tab.worker)
                    self.assertEqual(self.tab.run_journal.list_runs(), [])
                    self.window.set_all_tabs_locked.assert_not_called()

    def test_invalid_configs_are_rejected_before_preflight_or_worker(self):
        for scheduled in (False, True):
            with (
                self.subTest(scheduled=scheduled),
                patch.object(self.tab, "build_row_config", side_effect=ValueError("Invalid saved configuration")),
                patch("src.ui.task_tab.run_bounded_preflight") as preflight,
                patch("src.ui.task_tab.TaskWorker") as worker,
                patch("src.ui.task_tab.QMessageBox.warning") as warning,
            ):
                self.assertFalse(self.tab.start_all_tasks(scheduled=scheduled))
                preflight.assert_not_called()
                worker.assert_not_called()
                self.assertEqual(warning.call_count, 0 if scheduled else 1)
                self.assertIn("No runnable tasks", self.tab.start_failure_reason)
                self.assertIn("Invalid saved configuration", self.tab.start_failure_reason)
                self.assertFalse(self.tab.is_running)
                self.assertEqual(self.tab.run_journal.list_runs(), [])

    def test_schedule_save_failure_prevents_an_unrecorded_start(self):
        self.tab.check_schedule.setChecked(True)
        previous = copy.deepcopy(self.config.values)
        self.config.fail = True
        with patch.object(self.tab, "start_all_tasks") as start:
            self.assertFalse(self.tab.check_scheduled_run(wall_time(2026, 10, 28, 23)))
        start.assert_not_called()
        self.assertEqual(self.config.values, previous)

    def test_eml_and_pdf_outputs_are_chained_into_ocr_in_the_same_runner(self):
        from src.core.task_contracts import (
            EmlRunConfig,
            EmlTaskConfig,
            OcrRunConfig,
            PdfRunConfig,
        )
        from tools.test_task_runner import (
            FakeEMLConverter,
            FakeOCRProcessor,
            FakePDFConverter,
        )

        (self.source / "notice.eml").write_bytes(b"eml fixture")
        pdf = self.root / "document.pdf"
        pdf.write_bytes(b"pdf fixture")
        eml_output, pdf_output = self.root / "eml_images", self.root / "pdf_images"
        items = [
            ExecutionItem(
                "eml",
                TaskStep.EML,
                "EML",
                EmlRunConfig(
                    [EmlTaskConfig("mail", str(self.source), str(eml_output))]
                ),
            ),
            ExecutionItem(
                "pdf", TaskStep.PDF, "PDF", PdfRunConfig([str(pdf)], str(pdf_output))
            ),
            ExecutionItem("ocr", TaskStep.OCR, "OCR", OcrRunConfig([])),
        ]
        processed = []

        class RecordingOCR(FakeOCRProcessor):
            def process_image(self, source, **_kwargs):
                processed.append(source)
                return super().process_image(source)

        with (
            patch("src.core.task_runner.EMLConverter", FakeEMLConverter),
            patch("src.core.task_runner.PDFConverter", FakePDFConverter),
            patch("src.core.task_runner.OCRProcessor", RecordingOCR),
        ):
            report = TaskRunner(
                self.config, RunPlan(items=items, chain_outputs=True)
            ).run()
        self.assertTrue(report.overall_success)
        self.assertEqual(len(processed), 2)
        self.assertEqual(
            {Path(path).parent for path in processed}, {eml_output, pdf_output}
        )
        self.assertEqual(report.item_results["ocr"].success_count, 2)


class MasterMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_schedule_moves_to_earliest_time_once(self):
        groups = [new_collect_group(str(i)) for i in range(3)]
        for group, clock in zip(groups, ("17:30", "06:45", "12:00"), strict=True):
            group.update(schedule_enabled=True, schedule_time=clock)
        config = MemoryConfig(groups)
        config.values.update(sync_groups=[{"name": "existing", "folders": []}], task_enabled_steps=["sync"])
        migrate_task_selection(config)
        self.assertTrue(config.get("task_schedule_enabled"))
        self.assertEqual(config.get("task_schedule_time"), "06:45")
        self.assertTrue(all(not g["schedule_enabled"] for g in config.get("collect_sync_groups")))
        selected = config.get("task_enabled_items")
        sync_key = "sync:" + config.get("sync_groups")[0]["id"]
        for key in (sync_key, "eml", "pdf", "ocr"):
            self.assertIs(selected[key], False)
        for group in config.get("collect_sync_groups"):
            self.assertIs(selected["collect_sync:" + group["id"]], True)
        previous = copy.deepcopy(config.values)
        migrate_task_selection(config)
        self.assertEqual(config.values, previous)
        config.values["sync_groups"].append({"name": "new", "folders": []})
        migrate_task_selection(config)
        key = "sync:" + config.get("sync_groups")[-1]["id"]
        self.assertFalse(config.get("task_enabled_items")[key])

    def test_existing_master_schedule_is_preserved(self):
        group = new_collect_group("legacy")
        group.update(schedule_enabled=True, schedule_time="06:00")
        config = MemoryConfig([group])
        config.values.update(
            task_schedule_enabled=True,
            task_schedule_time="19:30",
            sync_groups=[{"id": "existing", "name": "existing", "folders": []}],
            task_enabled_steps=["sync", "eml", "pdf", "ocr"],
            task_enabled_items={"pdf": False},
        )
        migrate_task_selection(config)
        self.assertEqual(config.get("task_schedule_time"), "19:30")
        selected = config.get("task_enabled_items")
        for key in ("sync:existing", "eml", "ocr"):
            self.assertIs(selected[key], True)
        self.assertIs(selected["pdf"], False)

    def test_collect_schedule_activation_clears_existing_non_collect_selections(self):
        for initialized in (False, True):
            with self.subTest(initialized=initialized):
                group = new_collect_group("legacy")
                group["schedule_enabled"] = True
                config = MemoryConfig([group])
                non_collect = ("sync:existing", "sync:removed", "eml", "pdf", "ocr", "bypass")
                config.values.update(
                    task_selection_migrated=initialized,
                    sync_groups=[{"id": "existing", "name": "existing", "folders": []}],
                    task_enabled_steps=["sync", "eml", "pdf", "ocr", "bypass"],
                    task_enabled_items=dict.fromkeys(non_collect, True),
                )
                migrate_task_selection(config)
                self.assertTrue(config.get("task_schedule_enabled"))
                selected = config.get("task_enabled_items")
                for key in non_collect:
                    self.assertIs(selected[key], False)
                self.assertIs(selected["collect_sync:" + group["id"]], True)

    def test_ui_startup_survives_failed_migration_and_sync_saves(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                group = new_collect_group("legacy")
                group["schedule_enabled"] = True
                config = MemoryConfig([group])
                config.values["sync_groups"] = [{"name": "old", "folders": []}]
                previous = copy.deepcopy(config.values)
                config.fail = True
                if raises:
                    config.update = Mock(side_effect=PermissionError("locked"))
                    config.set = Mock(side_effect=PermissionError("locked"))
                with patch.object(TaskTab, "_on_schedule_tick"):
                    tab = TaskTab(config)
                    sync = SyncTab(config)
                self.assertIn("Could not save task selection migration", "\n".join(tab.live_log))
                self.assertFalse(tab.start_btn.isEnabled())
                self.assertEqual(config.values, previous)
                tab.schedule_timer.stop()
                tab.run_health_timer.stop()
                tab.deleteLater()
                sync.deleteLater()
        self.app.processEvents()

    def test_config_load_survives_identity_migration_save_error(self):
        from src.utils.config_manager import ConfigManager
        with tempfile.TemporaryDirectory() as directory, patch("src.utils.config_manager.user_data_dir", return_value=Path(directory)):
            initial = ConfigManager()
            data = copy.deepcopy(initial.config)
            data["sync_groups"] = [{"name": "old", "folders": []}]
            path = Path(initial.config_path)
            path.write_text(json.dumps(data), encoding="utf-8")
            previous = path.read_bytes()
            with patch.object(ConfigManager, "_save_config_raw", return_value=False):
                loaded = ConfigManager()
            self.assertTrue(loaded.get("sync_groups")[0]["id"])
            self.assertEqual(path.read_bytes(), previous)

    def test_sync_uuids_are_persisted_on_load_and_duplicates_repaired(self):
        from src.utils.config_manager import ConfigManager

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "src.utils.config_manager.user_data_dir", return_value=Path(directory)
            ),
        ):
            config = ConfigManager()
            config.set(
                "sync_groups",
                [
                    {"name": "old", "folders": []},
                    {"id": "duplicate", "name": "a", "folders": []},
                    {"id": "duplicate", "name": "b", "folders": []},
                ],
            )
            loaded = ConfigManager().get("sync_groups")
            identities = [group["id"] for group in loaded]
            self.assertEqual(len(set(identities)), 3)
            self.assertEqual(ConfigManager().get("sync_groups"), loaded)

    def test_failed_atomic_migration_preserves_original_configuration(self):
        group = new_collect_group("legacy")
        group["schedule_enabled"] = True
        config = MemoryConfig([group])
        previous = copy.deepcopy(config.values)
        config.fail = True
        with self.assertRaises(OSError):
            migrate_task_selection(config)
        self.assertEqual(config.values, previous)

    def test_migration_save_failure_does_not_block_task_tab_startup(self):
        QApplication.instance() or QApplication([])
        group = new_collect_group("legacy")
        group["schedule_enabled"] = True
        config = MemoryConfig([group])
        config.fail = True
        tab = TaskTab(config)
        try:
            tab.schedule_timer.stop()
            self.assertTrue(config.values["collect_sync_groups"][0]["schedule_enabled"])
        finally:
            tab.stop_all()
            tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
