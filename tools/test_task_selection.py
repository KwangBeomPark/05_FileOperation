import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

from src.core.task_contracts import (
    BypassRunConfig,
    RunPlan,
    RunReport,
    SourceDisposition,
    StepResult,
    StepStatus,
    SyncGroupConfig,
    SyncRunConfig,
    TaskStep,
)
from src.core.preflight import PreflightReport
from src.ui.bypass_tab import BypassTab
from src.ui.task_tab import TaskTab


class FakeConfig:
    def __init__(self, values=None, app_dir=None):
        self.values = {"ui_language": "en", **(values or {})}
        self.app_dir = app_dir

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

    def test_readiness_dashboard_shows_valid_selected_feature(self):
        config = FakeConfig()
        window = QMainWindow()
        task_tab = TaskTab(config)
        window.setCentralWidget(task_tab)
        window.sync_tab = Mock()
        window.sync_tab.build_run_config.return_value = SyncRunConfig([
            SyncGroupConfig("daily", ["source", "target"]),
        ])

        with patch("src.ui.task_tab.check_run_plan", return_value=PreflightReport(language="en")):
            task_tab.refresh_readiness()

        readiness = task_tab.status_table.item(0, task_tab.COL_READINESS)
        self.assertEqual(readiness.text(), "Ready")
        self.assertEqual(readiness.toolTip(), "")
        task_tab.schedule_timer.stop()
        window.deleteLater()

    def test_scheduled_backup_requires_separate_consent_before_preflight(self):
        config = FakeConfig({
            "task_schedule_enabled": True,
            "task_enabled_steps": [TaskStep.BYPASS.value],
            "task_schedule_allow_source_backup": False,
            "bypass_source_disposition": "backup",
        })
        window = QMainWindow()
        task_tab = TaskTab(config)
        window.setCentralWidget(task_tab)
        window.bypass_tab = Mock()
        window.bypass_tab.build_run_config.return_value = BypassRunConfig([], SourceDisposition.BACKUP)

        with patch("src.ui.task_tab.check_run_plan") as preflight:
            started = task_tab.start_all_tasks(scheduled=True)

        self.assertFalse(started)
        self.assertIn("separate scheduled source-backup consent", task_tab.start_failure_reason)
        self.assertFalse(task_tab.check_allow_source_backup.isHidden())
        preflight.assert_not_called()
        task_tab.schedule_timer.stop()
        window.deleteLater()

    def test_latest_result_is_persisted_and_rendered_per_feature(self):
        config = FakeConfig()
        window = QMainWindow()
        task_tab = TaskTab(config)
        window.setCentralWidget(task_tab)
        report = RunReport(
            {
                TaskStep.SYNC: StepResult(
                    step=TaskStep.SYNC,
                    status=StepStatus.COMPLETED,
                    success_count=2,
                    total_count=2,
                    details=["done"],
                )
            },
            "body",
            "done",
            True,
        )

        task_tab.capture_run_report(report)

        self.assertEqual(config.get("task_step_last_results")["sync"]["status"], "completed")
        history_text = task_tab.status_table.item(0, task_tab.COL_LAST_RESULT).text()
        self.assertIn("Completed · 2/2", history_text)
        task_tab.schedule_timer.stop()
        window.deleteLater()

    def test_run_journal_saves_report_and_marks_a_stalled_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = FakeConfig(app_dir=temp_dir)
            task_tab = TaskTab(config)
            plan = RunPlan({
                TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("daily", ["source", "target"])])
            })
            task_tab.is_running = True
            task_tab._begin_run_journal(plan, scheduled=True)
            task_tab.last_activity_monotonic = time.monotonic() - task_tab.STALL_WARNING_SECONDS - 1

            task_tab._check_run_health()

            running_entry = task_tab.run_journal.list_runs()[0]
            self.assertTrue(running_entry["possibly_stalled"])
            self.assertIn("Possibly stalled", task_tab.run_health_label.text())

            report = RunReport(
                {
                    TaskStep.SYNC: StepResult(
                        step=TaskStep.SYNC,
                        status=StepStatus.COMPLETED,
                        success_count=1,
                        total_count=1,
                    )
                },
                "# report",
                "done",
                True,
            )
            task_tab.capture_run_report(report)

            completed_entry = task_tab.run_journal.list_runs()[0]
            self.assertEqual(completed_entry["status"], "completed")
            self.assertTrue(os.path.isfile(completed_entry["report_path"]))
            task_tab.schedule_timer.stop()
            task_tab.run_health_timer.stop()
            task_tab.deleteLater()

    def test_changing_source_backup_action_revokes_scheduled_consent(self):
        config = FakeConfig({
            "bypass_source_disposition": "keep",
            "task_schedule_allow_source_backup": True,
        })
        tab = BypassTab(config)

        tab.check_backup_orig.setChecked(True)

        self.assertEqual(config.get("bypass_source_disposition"), "backup")
        self.assertFalse(config.get("task_schedule_allow_source_backup"))
        tab.deleteLater()

    def test_diagnostic_recovery_opens_feature_tab_or_settings(self):
        config = FakeConfig()
        window = QMainWindow()
        window.tab_widget = QTabWidget()
        window.setCentralWidget(window.tab_widget)
        task_tab = TaskTab(config)
        sync_tab = QWidget()
        window.task_tab = task_tab
        window.sync_tab = sync_tab
        window.tab_widget.addTab(task_tab, "Tasks")
        window.tab_widget.addTab(sync_tab, "Sync")
        window.open_settings = Mock()

        task_tab._navigate_diagnostic_target(TaskStep.SYNC.value)
        self.assertIs(window.tab_widget.currentWidget(), sync_tab)

        task_tab._navigate_diagnostic_target("settings")
        window.open_settings.assert_called_once_with()
        task_tab.schedule_timer.stop()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
