import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.core.diagnostics import DiagnosticsCancelled, DiagnosticStatus, run_diagnostics
from src.core.probe_runner import ProbeResult
from src.core.task_contracts import (
    BypassFileConfig,
    BypassRunConfig,
    OcrRunConfig,
    RunPlan,
    SourceDisposition,
    SyncGroupConfig,
    SyncRunConfig,
    TaskStep,
)
from src.ui.diagnostics_dialog import DiagnosticsWorker


class FakeConfig:
    def __init__(self, values=None):
        self.values = {"ui_language": "en", **(values or {})}

    def get(self, key, default=None):
        return self.values.get(key, default)


class DiagnosticsTests(unittest.TestCase):
    def test_sync_paths_are_checked_without_writing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = os.path.join(temp_dir, "first")
            second = os.path.join(temp_dir, "second")
            os.makedirs(first)
            os.makedirs(second)
            plan = RunPlan({
                TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("daily", [first, second])]),
            })

            items = run_diagnostics(plan, FakeConfig(), auto_email=False)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].status, DiagnosticStatus.PASS)
            self.assertEqual(os.listdir(first), [])
            self.assertEqual(os.listdir(second), [])

    def test_missing_sync_path_points_back_to_sync_feature(self):
        plan = RunPlan({
            TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("daily", ["missing-a", "missing-b"])]),
        })

        items = run_diagnostics(plan, FakeConfig(), auto_email=False)

        self.assertEqual(items[0].status, DiagnosticStatus.FAIL)
        self.assertEqual(items[0].target, TaskStep.SYNC.value)
        self.assertIn("Missing folder", items[0].detail)

    def test_office_and_scheduled_backup_consent_are_diagnosed_separately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "book.xlsx")
            with open(source, "wb") as file:
                file.write(b"office")
            config = BypassRunConfig([
                BypassFileConfig(
                    source,
                    os.path.join(temp_dir, "book.xlsb"),
                    ".xlsb",
                    True,
                    SourceDisposition.BACKUP,
                )
            ], SourceDisposition.BACKUP)
            plan = RunPlan({TaskStep.BYPASS: config})
            settings = FakeConfig({
                "task_schedule_enabled": True,
                "task_schedule_allow_source_backup": False,
            })

            with (
                patch("src.core.diagnostics.check_office_imports", return_value=(True, "ok")),
                patch("src.core.diagnostics.check_office_apps", return_value=(True, [])),
            ):
                items = run_diagnostics(plan, settings, auto_email=False)

            by_code = {item.code: item for item in items}
            self.assertEqual(by_code["office_com"].status, DiagnosticStatus.PASS)
            self.assertEqual(by_code["scheduled_backup_consent"].status, DiagnosticStatus.FAIL)
            self.assertEqual(by_code["scheduled_backup_consent"].target, "tasks")

    def test_ocr_fallback_is_warning_and_smtp_connect_does_not_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = os.path.join(temp_dir, "image.png")
            with open(image, "wb") as file:
                file.write(b"image")
            plan = RunPlan({TaskStep.OCR: OcrRunConfig([image])})
            settings = FakeConfig({
                "smtp_server": "mail.example.com",
                "smtp_port": "587",
                "sender_email": "sender@example.com",
                "receiver_email": "recipient@example.com",
            })
            connection = MagicMock()
            connection.__enter__.return_value = connection

            with (
                patch("src.core.diagnostics.check_ocr_engines", return_value=(True, "Windows OCR", True)),
                patch("src.core.diagnostics.socket.create_connection", return_value=connection) as connect,
            ):
                items = run_diagnostics(plan, settings, auto_email=True)

            by_code = {item.code: item for item in items}
            self.assertEqual(by_code["ocr_engine"].status, DiagnosticStatus.WARNING)
            self.assertEqual(by_code["smtp_connection"].status, DiagnosticStatus.PASS)
            connect.assert_called_once_with(("mail.example.com", 587), timeout=5)

    def test_diagnostics_worker_reports_unexpected_failure(self):
        worker = DiagnosticsWorker(RunPlan(), FakeConfig(), False)
        failures = []
        worker.failed.connect(failures.append)

        with patch("src.ui.diagnostics_dialog.run_diagnostics", side_effect=RuntimeError("broken check")):
            worker.run()

        self.assertEqual(failures, ["broken check"])

    def test_isolated_path_timeout_reports_feature_and_recovery_target(self):
        plan = RunPlan({
            TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("daily", ["network-share"])]),
        })
        timeout = ProbeResult(False, error="slow", timed_out=True, elapsed_seconds=8.0)

        with patch("src.core.diagnostics.run_probe", return_value=timeout):
            items = run_diagnostics(plan, FakeConfig(), auto_email=False, isolated=True)

        self.assertEqual(items[0].status, DiagnosticStatus.FAIL)
        self.assertEqual(items[0].target, TaskStep.SYNC.value)
        self.assertIn("timed out", items[0].detail)

    def test_diagnostics_worker_emits_cancelled(self):
        worker = DiagnosticsWorker(RunPlan(), FakeConfig(), False)
        cancelled = []
        worker.cancelled.connect(lambda: cancelled.append(True))

        with patch("src.ui.diagnostics_dialog.run_diagnostics", side_effect=DiagnosticsCancelled()):
            worker.run()

        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
