import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.core.task_contracts import RunPlan
from src.ui.task_worker import TaskWorker


class FakeConfig:
    def get(self, key, default=None):
        return "en" if key == "ui_language" else default


class TaskWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unhandled_runner_error_still_emits_finished(self):
        worker = TaskWorker(FakeConfig(), RunPlan())
        worker.runner.run = Mock(side_effect=RuntimeError("unexpected"))
        outcomes = []
        worker.finished.connect(lambda success, message, body: outcomes.append((success, message, body)))

        worker.run()

        self.assertEqual(len(outcomes), 1)
        self.assertFalse(outcomes[0][0])
        self.assertIn("unexpected", outcomes[0][1])
        self.assertEqual(outcomes[0][2], "")


if __name__ == "__main__":
    unittest.main()
