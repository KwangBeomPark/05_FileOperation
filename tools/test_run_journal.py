import json
import tempfile
import unittest
from pathlib import Path

from src.core.run_journal import RunJournal
from src.core.task_contracts import RunReport, StepResult, StepStatus, TaskStep


class RunJournalTests(unittest.TestCase):
    def test_completed_run_saves_metadata_and_readable_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = RunJournal(temp_dir)
            run_id = journal.start_run([TaskStep.SYNC], scheduled=True, language="en")
            journal.touch(
                run_id,
                current_step=TaskStep.SYNC,
                detail="Synchronizing invoice.pdf",
                current=1,
                total=2,
            )
            report = RunReport(
                {
                    TaskStep.SYNC: StepResult(
                        step=TaskStep.SYNC,
                        status=StepStatus.COMPLETED,
                        success_count=2,
                        total_count=2,
                    )
                },
                "# Saved report",
                "done",
                True,
            )

            report_path = journal.finish_run(run_id, report)
            entries = journal.list_runs()

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["status"], "completed")
            self.assertTrue(entries[0]["scheduled"])
            self.assertEqual(entries[0]["current_step"], "sync")
            self.assertEqual(entries[0]["progress_current"], 1)
            self.assertEqual(Path(report_path).read_text(encoding="utf-8").strip(), "# Saved report")

    def test_unfinished_run_is_recovered_as_interrupted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = RunJournal(temp_dir)
            run_id = journal.start_run([TaskStep.PDF], scheduled=False, language="ko")
            journal.mark_possibly_stalled(run_id)

            recovered = RunJournal(temp_dir).recover_interrupted_runs()
            entry = RunJournal(temp_dir).list_runs()[0]

            self.assertEqual(recovered, 1)
            self.assertEqual(entry["status"], "interrupted")
            self.assertFalse(entry["possibly_stalled"])
            self.assertTrue(entry["finished_at"])

    def test_corrupt_metadata_is_ignored_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir) / "reports"
            reports_dir.mkdir()
            broken_path = reports_dir / "run_broken.json"
            broken_path.write_text("{not-json", encoding="utf-8")

            entries = RunJournal(temp_dir).list_runs()

            self.assertEqual(entries, [])
            self.assertTrue(broken_path.exists())

    def test_report_path_rejects_directory_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = RunJournal(temp_dir)

            with self.assertRaises(ValueError):
                journal.report_path("../outside")

    def test_failed_worker_gets_a_report_even_without_runner_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = RunJournal(temp_dir)
            run_id = journal.start_run([TaskStep.OCR], scheduled=False, language="en")

            path = journal.finish_failed(run_id, "unexpected failure")
            metadata_path = Path(temp_dir) / "reports" / f"{run_id}.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

            self.assertEqual(metadata["status"], "failed")
            self.assertIn("unexpected failure", Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
