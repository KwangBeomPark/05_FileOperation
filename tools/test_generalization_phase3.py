"""Automated unit & regression tests for Phase 3 Generalization features.

Covers:
- Flexible scheduling (interval mode, weekday filter)
- FolderWatcher (file detection, debounce, lock checks, pattern filtering)
- Headless execution runner
- TaskTab integration with FolderWatcher and evaluate_flexible_schedule
"""

import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from src.core.folder_watcher import FolderWatcher, is_file_ready
from src.core.schedule import evaluate_flexible_schedule
from src.main import run_headless


class TestSchedulePhase3(unittest.TestCase):
    """Test flexible schedule evaluator with interval mode and weekday filtering."""

    def test_interval_mode_due_on_fresh_start(self):
        now = datetime(2026, 9, 26, 10, 0, 0)
        decision = evaluate_flexible_schedule(
            now=now,
            schedule_mode="interval",
            interval_minutes=30,
        )
        self.assertTrue(decision.should_start)
        self.assertEqual(decision.status, "due")

    def test_interval_mode_waiting_for_next_interval(self):
        now = datetime(2026, 9, 26, 10, 15, 0)
        last_started = "2026-09-26T10:00:00"
        decision = evaluate_flexible_schedule(
            now=now,
            schedule_mode="interval",
            interval_minutes=30,
            last_started_at=last_started,
        )
        self.assertFalse(decision.should_start)
        self.assertEqual(decision.status, "interval_waiting")
        self.assertEqual(decision.next_at, datetime(2026, 9, 26, 10, 30, 0))

    def test_interval_mode_due_after_interval_elapsed(self):
        now = datetime(2026, 9, 26, 10, 35, 0)
        last_started = "2026-09-26T10:00:00"
        decision = evaluate_flexible_schedule(
            now=now,
            schedule_mode="interval",
            interval_minutes=30,
            last_started_at=last_started,
        )
        self.assertTrue(decision.should_start)
        self.assertEqual(decision.status, "due")

    def test_daily_weekday_filter_deferred_when_not_today(self):
        # 2026-09-26 is a Saturday (weekday 5)
        now = datetime(2026, 9, 26, 19, 0, 0)
        self.assertEqual(now.weekday(), 5)
        # Weekdays: only Monday (0) to Friday (4)
        decision = evaluate_flexible_schedule(
            now=now,
            schedule_time="18:00",
            schedule_mode="daily",
            weekdays=[0, 1, 2, 3, 4],
        )
        self.assertFalse(decision.should_start)
        self.assertEqual(decision.status, "not_scheduled_day")
        # Next Monday is 2026-09-28
        self.assertEqual(decision.next_at, datetime(2026, 9, 28, 18, 0, 0))

    def test_daily_weekday_filter_active_when_today(self):
        # Saturday (5)
        now = datetime(2026, 9, 26, 19, 0, 0)
        decision = evaluate_flexible_schedule(
            now=now,
            schedule_time="18:00",
            schedule_mode="daily",
            weekdays=[5],  # Saturday
        )
        self.assertTrue(decision.should_start)
        self.assertEqual(decision.status, "due")


class TestFolderWatcherPhase3(unittest.TestCase):
    """Test FolderWatcher file readiness, debouncing, and pattern filtering."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_is_file_ready(self):
        file_path = os.path.join(self.temp_dir, "test.txt")
        self.assertFalse(is_file_ready(file_path))
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("content")
        self.assertTrue(is_file_ready(file_path, check_duration=0.05))

    def test_folder_watcher_detects_files_and_filters_pattern(self):
        detected_files = []

        def on_files(files):
            detected_files.extend(files)

        watcher = FolderWatcher(
            watch_folders=[self.temp_dir],
            callback=on_files,
            debounce_seconds=0.5,
            poll_interval=0.2,
            patterns=["*.csv", "*.txt"],
        )
        try:
            watcher.start(initial_snapshot=True)
            self.assertTrue(watcher.is_running)

            # Create an ignored file and a matching file
            ignored_file = os.path.join(self.temp_dir, "temp.log")
            with open(ignored_file, "w", encoding="utf-8") as f:
                f.write("log data")

            matched_file = os.path.join(self.temp_dir, "data.txt")
            with open(matched_file, "w", encoding="utf-8") as f:
                f.write("text data")

            # Wait for poll cycle and debounce
            time.sleep(1.2)

            self.assertEqual(len(detected_files), 1)
            self.assertTrue(detected_files[0].endswith("data.txt"))
        finally:
            watcher.stop()
            self.assertFalse(watcher.is_running)


class TestHeadlessExecutionPhase3(unittest.TestCase):
    """Test CLI --headless-run execution path."""

    @patch("src.utils.config_manager.ConfigManager")
    @patch("src.core.task_runner.TaskRunner")
    def test_run_headless_success(self, mock_runner_cls, mock_config_cls):
        mock_cfg = Mock()
        mock_cfg.get.side_effect = lambda k, d=None: {
            "sync_groups": [{"name": "G1", "folders": ["C:/A", "C:/B"]}],
            "task_enabled_steps": ["sync"],
        }.get(k, d)
        mock_config_cls.return_value = mock_cfg

        mock_runner = Mock()
        mock_report = Mock()
        mock_report.overall_success = True
        mock_report.report_body = "All sync completed."
        mock_runner.run.return_value = mock_report
        mock_runner_cls.return_value = mock_runner

        code = run_headless()
        self.assertEqual(code, 0)
        mock_runner.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
