import os
import unittest
from datetime import datetime
from unittest.mock import Mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMainWindow

from src.core.schedule import evaluate_daily_schedule
from src.ui.task_tab import TaskTab


class FakeConfig:
    def __init__(self, values=None):
        self.values = {
            "ui_language": "en",
            "task_schedule_enabled": True,
            "task_schedule_time": "00:00",
            "task_auto_email": False,
            **(values or {}),
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return True

    def update(self, values):
        self.values.update(values)
        return True


class SchedulePolicyTests(unittest.TestCase):
    def test_waits_until_scheduled_time(self):
        decision = evaluate_daily_schedule(
            now=datetime(2026, 8, 8, 8, 59),
            schedule_time="09:00",
        )
        self.assertFalse(decision.should_start)
        self.assertEqual(decision.status, "waiting")
        self.assertEqual(decision.next_at, datetime(2026, 8, 8, 9, 0))

    def test_prestart_failure_uses_bounded_retry_delay(self):
        decision = evaluate_daily_schedule(
            now=datetime(2026, 8, 8, 9, 5),
            schedule_time="09:00",
            attempt_date="2026-08-08",
            attempt_count=1,
            last_attempt_at="2026-08-08T09:00:00",
        )
        self.assertFalse(decision.should_start)
        self.assertEqual(decision.status, "retry_wait")
        self.assertEqual(decision.next_at, datetime(2026, 8, 8, 9, 10))

    def test_attempt_limit_defers_until_tomorrow(self):
        decision = evaluate_daily_schedule(
            now=datetime(2026, 8, 8, 9, 30),
            schedule_time="09:00",
            attempt_date="2026-08-08",
            attempt_count=3,
            last_attempt_at="2026-08-08T09:20:00",
        )
        self.assertFalse(decision.should_start)
        self.assertEqual(decision.status, "attempts_exhausted")
        self.assertEqual(decision.next_at, datetime(2026, 8, 9, 9, 0))

    def test_started_run_is_never_repeated_the_same_day(self):
        decision = evaluate_daily_schedule(
            now=datetime(2026, 8, 8, 18, 0),
            schedule_time="09:00",
            last_started_at="2026-08-08T09:01:00",
        )
        self.assertFalse(decision.should_start)
        self.assertEqual(decision.status, "already_started")
        self.assertEqual(decision.next_at, datetime(2026, 8, 9, 9, 0))


class ScheduledRunIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = FakeConfig()
        self.window = QMainWindow()
        self.tab = TaskTab(self.config)
        self.window.setCentralWidget(self.tab)
        self.tab.schedule_timer.stop()

    def tearDown(self):
        self.tab.schedule_timer.stop()
        self.window.deleteLater()

    def test_failed_start_retries_without_marking_the_day_as_run(self):
        def reject_start(*_args, **_kwargs):
            self.tab.start_failure_reason = "Sync folder is unavailable"
            return False

        self.tab.start_all_tasks = Mock(side_effect=reject_start)
        self.assertFalse(self.tab.check_scheduled_run(datetime(2026, 8, 8, 9, 0)))
        self.assertEqual(self.config.get("task_schedule_attempt_count"), 1)
        self.assertEqual(self.config.get("task_schedule_last_run_date", ""), "")
        self.assertIn("Sync folder", self.config.get("task_schedule_last_failure_reason"))

        self.assertFalse(self.tab.check_scheduled_run(datetime(2026, 8, 8, 9, 5)))
        self.assertEqual(self.tab.start_all_tasks.call_count, 1)
        self.assertFalse(self.tab.check_scheduled_run(datetime(2026, 8, 8, 9, 10)))
        self.assertFalse(self.tab.check_scheduled_run(datetime(2026, 8, 8, 9, 20)))
        self.assertEqual(self.tab.start_all_tasks.call_count, 3)
        self.assertEqual(self.config.get("task_schedule_attempt_count"), 3)

        self.assertFalse(self.tab.check_scheduled_run(datetime(2026, 8, 8, 10, 0)))
        self.assertEqual(self.tab.start_all_tasks.call_count, 3)

    def test_started_run_records_day_and_completion_outcome(self):
        self.tab.start_all_tasks = Mock(return_value=True)
        self.assertTrue(self.tab.check_scheduled_run(datetime(2026, 8, 8, 9, 0)))
        self.assertEqual(self.config.get("task_schedule_last_run_date"), "2026-08-08")
        self.assertEqual(self.config.get("task_schedule_last_started_at"), "2026-08-08T09:00:00")

        self.tab.is_running = True
        self.tab.is_scheduled_run = True
        self.tab.on_tasks_finished(True, "Completed", "")
        self.assertTrue(self.config.get("task_schedule_last_success_at"))
        self.assertIn("Last success", self.tab.schedule_status_label.text())


if __name__ == "__main__":
    unittest.main()
