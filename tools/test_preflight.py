import unittest
from unittest.mock import patch

from src.core.preflight import IssueLevel, check_github_updater_settings, check_run_plan
from src.core.probe_runner import ProbeResult
from src.core.release_config import DEFAULT_GITHUB_REPOSITORY_SLUG
from src.core.task_contracts import (
    BypassFileConfig,
    BypassRunConfig,
    OcrRunConfig,
    RunPlan,
    SourceDisposition,
    TaskStep,
)


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=""):
        return self.values.get(key, default)


class PreflightTests(unittest.TestCase):
    def test_ocr_dependency_failure_is_blocker(self):
        plan = RunPlan({TaskStep.OCR: OcrRunConfig(["image.png"])})
        with patch("src.core.preflight.check_ocr_engines", return_value=(False, "missing", False)):
            report = check_run_plan(plan, FakeConfig())

        self.assertTrue(report.has_blockers)
        self.assertEqual(report.blockers[0].level, IssueLevel.BLOCKER)
        self.assertEqual(report.blockers[0].step, TaskStep.OCR)

    def test_ocr_windows_fallback_is_warning_not_blocker(self):
        plan = RunPlan({TaskStep.OCR: OcrRunConfig(["image.png"])})
        with patch("src.core.preflight.check_ocr_engines", return_value=(True, "fallback", True)):
            report = check_run_plan(plan, FakeConfig())

        self.assertFalse(report.has_blockers)
        self.assertEqual(report.warnings[0].step, TaskStep.OCR)

    def test_bypass_office_tasks_emit_warning_when_not_deep_checking_com(self):
        config = BypassRunConfig(
            [BypassFileConfig("source.xlsx", "target.xlsb", ".xlsb", True, SourceDisposition.KEEP)],
            source_disposition=SourceDisposition.KEEP,
        )
        plan = RunPlan({TaskStep.BYPASS: config})
        with patch("src.core.preflight.check_office_imports", return_value=(True, "ok")):
            report = check_run_plan(plan, FakeConfig(), check_office=False)

        self.assertFalse(report.has_blockers)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("Excel.Application", report.warnings[0].detail)

    def test_bypass_office_tasks_block_when_required_app_cannot_launch(self):
        config = BypassRunConfig(
            [BypassFileConfig("source.xlsx", "target.xlsb", ".xlsb", True, SourceDisposition.KEEP)],
            source_disposition=SourceDisposition.KEEP,
        )
        plan = RunPlan({TaskStep.BYPASS: config})
        with (
            patch("src.core.preflight.check_office_imports", return_value=(True, "ok")),
            patch("src.core.preflight.check_office_apps", return_value=(False, ["Excel.Application: unavailable"])),
        ):
            report = check_run_plan(plan, FakeConfig())

        self.assertTrue(report.has_blockers)
        self.assertEqual(report.blockers[0].step, TaskStep.BYPASS)
        self.assertIn("Excel.Application", report.blockers[0].detail)

    def test_isolated_office_timeout_is_a_named_blocker(self):
        config = BypassRunConfig(
            [BypassFileConfig("source.xlsx", "target.xlsb", ".xlsb", True, SourceDisposition.KEEP)],
            source_disposition=SourceDisposition.KEEP,
        )
        plan = RunPlan({TaskStep.BYPASS: config})
        timeout = ProbeResult(False, error="slow", timed_out=True, elapsed_seconds=20.0)
        with (
            patch("src.core.preflight.check_office_imports", return_value=(True, "ok")),
            patch("src.core.preflight.run_probe", return_value=timeout),
        ):
            report = check_run_plan(plan, FakeConfig(), isolated=True)

        self.assertTrue(report.has_blockers)
        self.assertEqual(report.blockers[0].step, TaskStep.BYPASS)
        self.assertIn("timed out", report.blockers[0].detail)

    def test_bypass_backup_action_is_visible_in_preflight(self):
        config = BypassRunConfig(
            [BypassFileConfig("source.pdf", "target.zip", ".zip", True, SourceDisposition.BACKUP)],
            source_disposition=SourceDisposition.BACKUP,
        )
        plan = RunPlan({TaskStep.BYPASS: config})
        with patch("src.core.preflight.check_office_imports", return_value=(True, "ok")):
            report = check_run_plan(plan, FakeConfig(), check_office=False)

        backup_warnings = [issue for issue in report.warnings if "Original Backup" in issue.detail]
        self.assertEqual(len(backup_warnings), 1)
        self.assertEqual(backup_warnings[0].step, TaskStep.BYPASS)

    def test_smtp_missing_fields_are_warnings(self):
        plan = RunPlan({})
        report = check_run_plan(plan, FakeConfig(), auto_email=True)

        self.assertFalse(report.has_blockers)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("SMTP server", report.warnings[0].detail)

    def test_github_updater_invalid_repo_is_warning(self):
        plan = RunPlan({})
        report = check_run_plan(
            plan,
            FakeConfig({"github_repo": "owner/repo/extra", "auto_check_update": "on_start"}),
        )

        self.assertFalse(report.has_blockers)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("owner/repository", report.warnings[0].detail)

    def test_empty_github_repo_uses_the_documented_canonical_default(self):
        valid, detail = check_github_updater_settings(FakeConfig())

        self.assertTrue(valid)
        self.assertIn(DEFAULT_GITHUB_REPOSITORY_SLUG, detail)


if __name__ == "__main__":
    unittest.main()
