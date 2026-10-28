import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMainWindow

from src.core.preflight import PreflightReport
from src.core.task_contracts import (
    EmlRunConfig,
    OcrRunConfig,
    RunPlan,
    StepStatus,
    SyncGroupConfig,
    SyncRunConfig,
    TaskStep,
)
from src.core.task_runner import RunnerCallbacks, TaskRunner
from src.main import run_headless
from src.ui.task_tab import TaskTab
from src.utils.config_manager import ConfigManager


class FakeConfig:
    def __init__(self, values=None):
        self.values = {"ui_language": "en", **(values or {})}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return True


class CancelDuringExecuteSyncManager:
    """Simulates the user pressing Stop while files are being copied."""

    instances: ClassVar[list] = []

    def __init__(self, folders, move_to_deleted=True, **_kwargs):
        self.folders = folders
        self.cancelled = False
        self.runner = None
        CancelDuringExecuteSyncManager.instances.append(self)

    def cancel(self):
        self.cancelled = True

    def analyze_sync(self):
        return [{"filename": "a.txt"}, {"filename": "b.txt"}]

    def execute_sync(self, actions, progress_callback=None):
        self.runner.cancel()
        done = 0 if self.cancelled else len(actions)
        return done, 0, ["cancelled"] if self.cancelled else []


class TaskRunnerSyncCancelTests(unittest.TestCase):
    def setUp(self):
        CancelDuringExecuteSyncManager.instances = []

    def test_cancel_reaches_active_sync_manager(self):
        plan = RunPlan({TaskStep.SYNC: SyncRunConfig([
            SyncGroupConfig("g1", ["a", "b"]),
            SyncGroupConfig("g2", ["c", "d"]),
        ])})
        runner = TaskRunner(FakeConfig(), plan)

        def make_manager(*args, **kwargs):
            manager = CancelDuringExecuteSyncManager(*args, **kwargs)
            manager.runner = runner
            return manager

        with patch("src.core.task_runner.SyncManager", side_effect=make_manager):
            report = runner.run(RunnerCallbacks())

        self.assertTrue(report.cancelled)
        self.assertEqual(len(CancelDuringExecuteSyncManager.instances), 1)
        self.assertTrue(CancelDuringExecuteSyncManager.instances[0].cancelled)
        self.assertEqual(report.results[TaskStep.SYNC].status, StepStatus.CANCELLED)
        self.assertIsNone(runner.sync_manager)

    def test_cancel_without_active_sync_manager_is_safe(self):
        runner = TaskRunner(FakeConfig(), RunPlan({}))
        runner.cancel()
        self.assertFalse(runner.is_running)


class TaskTabChainedOcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_tab(self):
        config = FakeConfig({
            "task_enabled_steps": [TaskStep.EML.value, TaskStep.OCR.value],
            "task_chain_outputs": True,
            "ocr_rule_mode": "custom",
            "ocr_custom_pattern": r"\d+",
        })
        window = QMainWindow()
        task_tab = TaskTab(config)
        window.setCentralWidget(task_tab)
        window.eml_tab = Mock()
        window.eml_tab.build_run_config.return_value = EmlRunConfig([])
        window.ocr_tab = Mock()
        window.ocr_tab.build_run_config.return_value = None
        self.addCleanup(window.deleteLater)
        self.addCleanup(task_tab.schedule_timer.stop)
        return window, task_tab

    def test_readiness_accepts_chained_ocr_without_own_images(self):
        _window, task_tab = self._make_tab()
        self.assertTrue(task_tab.check_chain_outputs.isChecked())

        with patch("src.ui.task_tab.check_run_plan", return_value=PreflightReport(language="en")) as preflight:
            task_tab.refresh_readiness()

        row = task_tab.STEP_ORDER.index(TaskStep.OCR)
        self.assertEqual(task_tab.status_table.item(row, task_tab.COL_READINESS).text(), "Ready")
        plan = preflight.call_args.args[0]
        ocr_config = plan.get(TaskStep.OCR)
        self.assertIsInstance(ocr_config, OcrRunConfig)
        self.assertEqual(ocr_config.image_paths, [])
        self.assertEqual(ocr_config.rule_mode, "custom")

    def test_readiness_blocks_ocr_without_images_when_chaining_is_off(self):
        _window, task_tab = self._make_tab()
        task_tab.check_chain_outputs.setChecked(False)

        with patch("src.ui.task_tab.check_run_plan", return_value=PreflightReport(language="en")):
            task_tab.refresh_readiness()

        row = task_tab.STEP_ORDER.index(TaskStep.OCR)
        self.assertNotEqual(task_tab.status_table.item(row, task_tab.COL_READINESS).text(), "Ready")

    def test_diagnostics_receive_chained_ocr_config(self):
        _window, task_tab = self._make_tab()

        with (
            patch("src.ui.task_tab.DiagnosticsDialog") as dialog_cls,
            patch("src.ui.task_tab.check_run_plan", return_value=PreflightReport(language="en")),
        ):
            task_tab.open_diagnostics()

        run_plan, validation_items = dialog_cls.call_args.args[1], dialog_cls.call_args.args[2]
        self.assertEqual(validation_items, [])
        self.assertIsInstance(run_plan.get(TaskStep.OCR), OcrRunConfig)
        self.assertTrue(run_plan.chain_outputs)

    def test_missing_feature_tab_is_reported_as_validation_failure(self):
        window, task_tab = self._make_tab()
        del window.ocr_tab
        task_tab.check_chain_outputs.setChecked(False)

        configs, errors = task_tab._collect_step_configs(task_tab.selected_steps())

        self.assertIn(TaskStep.EML, configs)
        self.assertEqual(list(errors), [TaskStep.OCR])


class HeadlessPlanTests(unittest.TestCase):
    @patch("src.utils.config_manager.ConfigManager")
    @patch("src.core.task_runner.TaskRunner")
    def test_disabled_steps_are_not_added_to_headless_plan(self, runner_cls, config_cls):
        values = {
            "sync_groups": [{"name": "G1", "folders": ["C:/A", "C:/B"]}],
            "task_enabled_steps": ["sync"],
            "task_chain_outputs": True,
        }
        config_cls.return_value.get.side_effect = lambda key, default=None: values.get(key, default)
        runner_cls.return_value.run.return_value = Mock(overall_success=True, report_body="")

        self.assertEqual(run_headless(), 0)

        plan = runner_cls.call_args.args[1]
        self.assertEqual(plan.active_steps, [TaskStep.SYNC])
        self.assertNotIn(TaskStep.OCR, plan.configs)

    @patch("src.utils.config_manager.ConfigManager")
    @patch("src.core.task_runner.TaskRunner")
    def test_no_enabled_step_does_not_fall_back_to_every_config(self, runner_cls, config_cls):
        values = {
            "sync_groups": [{"name": "G1", "folders": ["C:/A", "C:/B"]}],
            "task_enabled_steps": ["eml"],
        }
        config_cls.return_value.get.side_effect = lambda key, default=None: values.get(key, default)
        runner_cls.return_value.run.return_value = Mock(overall_success=False, report_body="")

        run_headless()

        plan = runner_cls.call_args.args[1]
        self.assertEqual(plan.active_steps, [])


class ConfigManagerCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local"), "APPDATA": str(root / "roaming")})
        environment.start()
        self.addCleanup(environment.stop)
        self.manager = ConfigManager()

    def test_mutating_returned_list_or_dict_does_not_change_settings(self):
        self.assertTrue(self.manager.set("sync_groups", [{"name": "G1", "folders": ["C:/A"]}]))

        groups = self.manager.get("sync_groups")
        groups[0]["folders"].append("C:/B")
        groups.append({"name": "G2"})

        self.assertEqual(self.manager.get("sync_groups"), [{"name": "G1", "folders": ["C:/A"]}])

    def test_scalars_are_returned_unchanged(self):
        self.assertTrue(self.manager.set("ocr_export_txt", True))
        self.assertIs(self.manager.get("ocr_export_txt"), True)


if __name__ == "__main__":
    unittest.main()
