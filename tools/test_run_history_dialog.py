import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.core.run_journal import RunJournal
from src.core.task_contracts import RunReport, StepResult, StepStatus, TaskStep
from src.ui.run_history_dialog import RunHistoryDialog


class RunHistoryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_history_lists_and_filters_saved_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = RunJournal(temp_dir)
            completed_id = journal.start_run([TaskStep.SYNC], scheduled=True, language="en")
            journal.finish_run(
                completed_id,
                RunReport(
                    {TaskStep.SYNC: StepResult(TaskStep.SYNC, StepStatus.COMPLETED, success_count=1, total_count=1)},
                    "# report",
                    "done",
                    True,
                ),
            )
            failed_id = journal.start_run([TaskStep.OCR], scheduled=False, language="en")
            journal.finish_failed(failed_id, "OCR failed")

            dialog = RunHistoryDialog(journal, "en")

            self.assertEqual(dialog.table.rowCount(), 2)
            failed_index = dialog.status_filter.findData("failed")
            dialog.status_filter.setCurrentIndex(failed_index)
            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.table.item(0, dialog.COL_STATUS).text(), "Failed")
            self.assertIn("Read Images", dialog.table.item(0, dialog.COL_FEATURES).text())
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
