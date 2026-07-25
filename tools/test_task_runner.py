import os
import tempfile
import unittest
from unittest.mock import patch

from src.core.task_contracts import (
    BypassFileConfig,
    BypassRunConfig,
    EmlRunConfig,
    EmlTaskConfig,
    OcrRunConfig,
    PdfRunConfig,
    RunPlan,
    SyncGroupConfig,
    SyncRunConfig,
    TaskStep,
)
from src.core.task_runner import RunnerCallbacks, TaskRunner


class FakeConfig:
    def get(self, _key, default=None):
        return default


class FakeSyncManagerSuccess:
    def __init__(self, folders, move_to_deleted=True):
        self.folders = folders
        self.move_to_deleted = move_to_deleted

    def analyze_sync(self):
        return [{"filename": "a.txt"}]

    def execute_sync(self, _actions):
        return 1, 0, []


class FakeSyncManagerPartial(FakeSyncManagerSuccess):
    def execute_sync(self, _actions):
        return 0, 1, ["copy failed"]


class FakeEMLConverter:
    def __init__(self, _config):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def convert_eml_to_image(self, _source, output, width):
        with open(output, "wb") as file:
            file.write(f"width={width}".encode())
        return True


class FakePDFConverter:
    def __init__(self, _config):
        pass

    def convert(self, source, output_folder):
        output = os.path.join(output_folder, os.path.basename(source) + ".jpg")
        with open(output, "wb") as file:
            file.write(b"pdf-image")
        return [output]


class FakeOCRProcessor:
    def __init__(self, _config):
        pass

    def process_image(self, _source):
        return True, "PL-ATSZ-20261234-6789", "recognized", None


class FakeBypassConverter:
    def convert_file(self, **_kwargs):
        return True, "ok"


class TaskRunnerTests(unittest.TestCase):
    def test_sync_success_report(self):
        plan = RunPlan({TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("g", ["a", "b"])])})
        with patch("src.core.task_runner.SyncManager", FakeSyncManagerSuccess):
            report = TaskRunner(FakeConfig(), plan).run()

        self.assertTrue(report.overall_success)
        self.assertIn("Folder Sync", report.report_body)
        self.assertIn("1 / 1", report.report_body)

    def test_sync_partial_failure_report(self):
        plan = RunPlan({TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("g", ["a", "b"])])})
        with patch("src.core.task_runner.SyncManager", FakeSyncManagerPartial):
            report = TaskRunner(FakeConfig(), plan).run()

        self.assertFalse(report.overall_success)
        self.assertIn("일부 실패", report.report_body)
        self.assertIn("copy failed", "\n".join(report.results[TaskStep.SYNC].details))

    def test_all_task_steps_produce_a_complete_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            eml_dir = os.path.join(temp_dir, "eml")
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(eml_dir)
            os.makedirs(output_dir)
            eml_path = os.path.join(eml_dir, "notice.eml")
            pdf_path = os.path.join(temp_dir, "document.pdf")
            image_path = os.path.join(temp_dir, "image.png")
            source_doc = os.path.join(temp_dir, "book.xlsx")
            for path in (eml_path, pdf_path, image_path, source_doc):
                with open(path, "wb") as file:
                    file.write(b"source")

            plan = RunPlan({
                TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("g", [temp_dir, output_dir])]),
                TaskStep.EML: EmlRunConfig([EmlTaskConfig("mail", eml_dir, output_dir)], width=900),
                TaskStep.PDF: PdfRunConfig([pdf_path], output_dir),
                TaskStep.OCR: OcrRunConfig([image_path]),
                TaskStep.BYPASS: BypassRunConfig(
                    [BypassFileConfig(source_doc, os.path.join(output_dir, "book.xlsb"), ".xlsb", True, False)],
                    False,
                ),
            })
            with (
                patch("src.core.task_runner.SyncManager", FakeSyncManagerSuccess),
                patch("src.core.task_runner.EMLConverter", FakeEMLConverter),
                patch("src.core.task_runner.PDFConverter", FakePDFConverter),
                patch("src.core.task_runner.OCRProcessor", FakeOCRProcessor),
                patch("src.core.task_runner.BypassConverter", FakeBypassConverter),
            ):
                report = TaskRunner(FakeConfig(), plan).run()

        self.assertTrue(report.overall_success)
        self.assertEqual(set(report.results), set(plan.active_steps))
        self.assertIn("Bypass Convert", report.report_body)

    def test_cancel_marks_report_as_cancelled(self):
        plan = RunPlan({TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("g", ["a", "b"])])})
        with patch("src.core.task_runner.SyncManager", FakeSyncManagerSuccess):
            runner = TaskRunner(FakeConfig(), plan)
            callbacks = RunnerCallbacks(status_changed=lambda _step, _status: runner.cancel())
            report = runner.run(callbacks)

        self.assertTrue(report.cancelled)
        self.assertFalse(report.overall_success)
        self.assertEqual(report.results[TaskStep.SYNC].status.value, "취소됨")


if __name__ == "__main__":
    unittest.main()
