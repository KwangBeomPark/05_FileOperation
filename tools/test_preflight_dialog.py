import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.core.preflight import PreflightReport
from src.core.task_contracts import RunPlan
from src.ui.preflight_dialog import PreflightWorker, run_bounded_preflight


class FakeConfig:
    def get(self, _key, default=None):
        return default


class PreflightDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hidden_scheduled_preflight_keeps_event_loop_and_returns_report(self):
        expected = PreflightReport(language="en")
        with patch("src.ui.preflight_dialog.check_run_plan", return_value=expected):
            report, error, cancelled = run_bounded_preflight(
                None,
                RunPlan(),
                FakeConfig(),
                auto_email=False,
                visible=False,
            )

        self.assertIs(report, expected)
        self.assertEqual(error, "")
        self.assertFalse(cancelled)

    def test_cancelled_worker_never_publishes_completed_report(self):
        worker = PreflightWorker(RunPlan(), FakeConfig(), False)
        completed = []
        cancelled = []
        worker.completed.connect(completed.append)
        worker.cancelled.connect(lambda: cancelled.append(True))
        worker.cancel()

        with patch("src.ui.preflight_dialog.check_run_plan", return_value=PreflightReport()):
            worker.run()

        self.assertEqual(completed, [])
        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
