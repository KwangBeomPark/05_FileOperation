from datetime import datetime
import unittest

from src.core.task_contracts import RunReport, StepResult, StepStatus, TaskStep
from src.core.task_history import merge_run_report_history, normalize_step_history


class TaskHistoryTests(unittest.TestCase):
    def test_report_updates_only_steps_that_ran(self):
        existing = {
            "sync": {
                "status": "completed",
                "timestamp": "2026-08-07T10:00:00",
                "success_count": 2,
                "total_count": 2,
                "detail": "old",
            }
        }
        result = StepResult(
            step=TaskStep.BYPASS,
            status=StepStatus.PARTIAL,
            success_count=1,
            total_count=2,
            details=["backup failed"],
        )
        report = RunReport({TaskStep.BYPASS: result}, "body", "partial", False)

        history = merge_run_report_history(existing, report, datetime(2026, 8, 8, 12, 30))

        self.assertEqual(history["sync"]["detail"], "old")
        self.assertEqual(history["bypass"]["status"], "partial")
        self.assertEqual(history["bypass"]["success_count"], 1)
        self.assertEqual(history["bypass"]["timestamp"], "2026-08-08T12:30:00")

    def test_malformed_history_entries_are_ignored(self):
        history = normalize_step_history({
            "unknown": {"status": "completed", "timestamp": "now"},
            "sync": {"status": "invented", "timestamp": "now"},
            "pdf": "broken",
        })

        self.assertEqual(history, {})


if __name__ == "__main__":
    unittest.main()
