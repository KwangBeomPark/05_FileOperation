import copy
import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QListWidgetItem, QMainWindow, QWidget

from src.core.preflight import PreflightReport
from src.core.probe_runner import ProbeResult
from src.core.run_summary import ChangeEntry, RunChangeSummary
from src.core.task_contracts import (
    BypassFileConfig, BypassRunConfig, PdfRunConfig, RunPlan,
    SyncGroupConfig, SyncRunConfig, TaskStep,
)
from src.ui.bypass_tab import BypassTab
from src.ui.eml_tab import EMLTab
from src.ui.ocr_tab import OCRTab
from src.ui.pdf_tab import PDFTab
from src.ui.run_summary_dialog import (
    RunSummaryDialog, SummaryProgressDialog, SummaryWorker,
    analyze_run_summary, confirm_run_summary,
)
from src.ui.sync_tab import SyncTab
from src.ui.task_tab import TaskTab
from src.ui.main_window import MainWindow
from src.utils.config_manager import ConfigManager


class FakeConfig:
    def __init__(self, language="en"):
        self.values = copy.deepcopy(ConfigManager.DEFAULT_CONFIG)
        self.values["ui_language"] = language
        self.app_dir = None

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return True


class RunSummaryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QWidget()
        self.addCleanup(self.parent.deleteLater)
        self.config = FakeConfig()
        self.summary = RunChangeSummary(
            entries=[ChangeEntry("sync", "daily", "delete", "old.txt", "")],
            counts={"delete": 1}, risks=["delete_policy"], total_entries=1,
            fingerprint="first",
        )

    def test_risky_run_requires_explicit_acknowledgement(self):
        dialog = RunSummaryDialog(self.summary, "ko")
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.run_button.isEnabled())
        self.assertTrue(dialog.cancel_button.isDefault())
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        dialog.acknowledgement.setChecked(True)
        self.assertTrue(dialog.run_button.isEnabled())
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_language_specific_labels_and_plain_text(self):
        for language, title in (("ko", "실행 전 변경 요약"), ("en", "Review changes before running"),
                                ("pl", "Sprawdź zmiany przed uruchomieniem")):
            dialog = RunSummaryDialog(self.summary, language)
            self.addCleanup(dialog.deleteLater)
            self.assertEqual(dialog.windowTitle(), title)
            self.assertEqual(dialog.risk_label.textFormat(), Qt.TextFormat.PlainText)
            self.assertEqual(dialog.table.item(0, 2).text(), "old.txt")
            if language == "en":
                self.assertNotIn("영구", dialog.risk_label.text())
                self.assertTrue(all("변경" not in label.text() for label in dialog.findChildren(QLabel)))

    def test_safe_run_does_not_require_risk_checkbox(self):
        dialog = RunSummaryDialog(RunChangeSummary(), "en")
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.run_button.isEnabled())
        self.assertTrue(dialog.acknowledgement.isHidden())

    def test_cancel_does_not_reanalyze_or_execute(self):
        with (patch("src.ui.run_summary_dialog.analyze_run_summary", return_value=(self.summary, "", False)) as analyze,
              patch.object(RunSummaryDialog, "exec", return_value=QDialog.DialogCode.Rejected)):
            self.assertFalse(confirm_run_summary(self.parent, RunPlan(), self.config))
        self.assertEqual(analyze.call_count, 1)
        self.assertFalse(self.parent._run_confirmation_active)

    def test_stale_summary_aborts_and_restores_window_guard(self):
        changed = RunChangeSummary(fingerprint="changed")
        with (patch("src.ui.run_summary_dialog.analyze_run_summary", side_effect=[(self.summary, "", False), (changed, "", False)]),
              patch.object(RunSummaryDialog, "exec", return_value=QDialog.DialogCode.Accepted),
              patch("src.ui.run_summary_dialog.QMessageBox.warning") as warning):
            self.assertFalse(confirm_run_summary(self.parent, RunPlan(), self.config))
        self.assertIn("changed", warning.call_args.args[2])
        self.assertFalse(self.parent._run_confirmation_active)

    def test_unchanged_summary_is_accepted_after_second_analysis(self):
        with (patch("src.ui.run_summary_dialog.analyze_run_summary", return_value=(self.summary, "", False)) as analyze,
              patch.object(RunSummaryDialog, "exec", return_value=QDialog.DialogCode.Accepted)):
            self.assertTrue(confirm_run_summary(self.parent, RunPlan(), self.config))
        self.assertEqual(analyze.call_count, 2)
        self.assertTrue(analyze.call_args.kwargs["recheck"])

    def test_scheduled_run_logs_without_showing_confirmation(self):
        with (patch("src.ui.run_summary_dialog.analyze_run_summary", return_value=(self.summary, "", False)) as analyze,
              patch.object(RunSummaryDialog, "exec") as dialog,
              patch("src.ui.run_summary_dialog.logger.info") as log):
            self.assertTrue(confirm_run_summary(self.parent, RunPlan(), self.config, scheduled=True))
        dialog.assert_not_called()
        self.assertFalse(analyze.call_args.kwargs["visible"])
        log.assert_called_once()

    def test_failed_scheduled_analysis_preserves_existing_policy_without_popup(self):
        with (patch("src.ui.run_summary_dialog.analyze_run_summary", return_value=(None, "timed out", False)),
              patch("src.ui.run_summary_dialog.QMessageBox.warning") as warning):
            self.assertTrue(confirm_run_summary(self.parent, RunPlan(), self.config, scheduled=True))
        warning.assert_not_called()

    def test_cancel_before_worker_start_is_safe(self):
        worker = SummaryWorker(RunPlan())
        with patch("src.ui.run_summary_dialog.run_probe", return_value=ProbeResult(False, cancelled=True)):
            dialog = SummaryProgressDialog(worker, self.config, self.parent)
            dialog.reject()  # Escape before QTimer.singleShot starts the worker.
            dialog.exec()
            worker.wait()
        self.assertTrue(dialog.was_cancelled)
        dialog.deleteLater()

    def test_bounded_analysis_runs_registered_probe_on_temporary_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.pdf"
            source.write_bytes(b"fixture; no PDF parser should be called")
            output = Path(temporary) / "new-output"
            summary, error, cancelled = analyze_run_summary(
                self.parent, RunPlan({TaskStep.PDF: PdfRunConfig([str(source)], str(output))}),
                self.config, visible=False,
            )
            self.assertIsNotNone(summary, error)
            self.assertFalse(cancelled)
            self.assertEqual(summary.counts, {"convert": 1})
            self.assertFalse(output.exists())

    def test_main_window_cannot_dispose_active_review_worker(self):
        window = SimpleNamespace(_run_confirmation_active=True)
        event = Mock()
        MainWindow.closeEvent(window, event)
        event.ignore.assert_called_once()

    def test_close_before_worker_start_cancels_without_disposing_worker(self):
        worker = SummaryWorker(RunPlan())
        dialog = SummaryProgressDialog(worker, self.config, self.parent)
        event = Mock()
        dialog.closeEvent(event)
        event.ignore.assert_called_once()
        self.assertTrue(worker.cancel_event.is_set())
        dialog.exec()
        worker.wait()
        self.assertTrue(dialog.was_cancelled)
        dialog.deleteLater()

    def test_worker_timeout_returns_failure_instead_of_hanging(self):
        with patch("src.ui.run_summary_dialog.run_probe", return_value=ProbeResult(False, error="exceeded 30 seconds", timed_out=True)):
            summary, error, cancelled = analyze_run_summary(self.parent, RunPlan(), self.config, visible=False)
        self.assertIsNone(summary)
        self.assertIn("30 seconds", error)
        self.assertFalse(cancelled)


class SummaryEntryPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "not-created"
        self.config = FakeConfig()

    def keep(self, tab):
        self.addCleanup(tab.deleteLater)
        if hasattr(tab, "schedule_timer"):
            tab.schedule_timer.stop()
        return tab

    def test_pdf_cancel_does_not_create_output_or_worker(self):
        tab = self.keep(PDFTab(self.config))
        file = self.source / "sample.pdf"
        file.write_bytes(b"pdf fixture")
        tab.selected_pdf_paths = [str(file)]
        tab.output_path_input.setText(str(self.output))
        with (patch("src.ui.pdf_tab.confirm_run_summary", return_value=False) as confirm,
              patch("src.ui.pdf_tab.PDFConvertWorker") as worker):
            tab.start_conversion()
        confirm.assert_called_once()
        worker.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertFalse(tab.is_converting)

    def test_eml_cancel_does_not_create_worker(self):
        tab = self.keep(EMLTab(self.config))
        tab.tasks = [{"name": "mail", "source_folder": str(self.source), "target_folder": str(self.output)}]
        with (patch("src.ui.eml_tab.confirm_run_summary", return_value=False) as confirm,
              patch("src.ui.eml_tab.EMLWorker") as worker):
            tab.start_conversion()
        confirm.assert_called_once()
        worker.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_ocr_cancel_does_not_create_worker(self):
        tab = self.keep(OCRTab(self.config))
        file = self.source / "sample.png"
        file.write_bytes(b"image fixture")
        item = QListWidgetItem("sample.png")
        item.setData(Qt.ItemDataRole.UserRole, str(file))
        item.setCheckState(Qt.CheckState.Checked)
        tab.image_list_widget.addItem(item)
        with (patch("src.ui.ocr_tab.confirm_run_summary", return_value=False) as confirm,
              patch("src.ui.ocr_tab.OCRWorker") as worker):
            tab.start_ocr()
        confirm.assert_called_once()
        worker.assert_not_called()

    def test_sync_cancel_does_not_create_worker(self):
        tab = self.keep(SyncTab(self.config))
        self.output.mkdir()
        tab.sync_groups = [{"name": "daily", "folders": [str(self.source), str(self.output)]}]
        tab._analysis_is_current = True
        tab._analysis_has_actions = True
        with (patch("src.ui.sync_tab.confirm_run_summary", return_value=False) as confirm,
              patch("src.ui.sync_tab.SyncWorker") as worker):
            tab.start_sync_execution()
        confirm.assert_called_once()
        worker.assert_not_called()

    def test_bypass_cancel_does_not_create_worker(self):
        tab = self.keep(BypassTab(self.config))
        file = self.source / "book.xlsx"
        file.write_bytes(b"office fixture")
        tab.scanned_files = [str(file)]
        config = BypassRunConfig([BypassFileConfig(str(file), str(self.output / "book.xlsm"), ".xlsm", True)])
        with (patch.object(tab, "build_run_config", return_value=config),
              patch("src.ui.bypass_tab.run_bounded_preflight", return_value=(PreflightReport(language="en"), "", False)),
              patch("src.ui.bypass_tab.confirm_run_summary", return_value=False) as confirm,
              patch("src.ui.bypass_tab.BypassConvertWorker") as worker):
            tab.start_conversion()
        confirm.assert_called_once()
        worker.assert_not_called()
        self.assertTrue(file.exists())

    def test_unified_cancel_does_not_create_worker(self):
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        tab = self.keep(TaskTab(self.config))
        window.setCentralWidget(tab)
        self.output.mkdir()
        window.sync_tab = self.keep(SyncTab(self.config))
        tab.rebuild_status_table()
        # Groups created after task setup now require explicit opt-in.
        tab.step_checks[TaskStep.SYNC].setChecked(True)
        config = SyncRunConfig([SyncGroupConfig("daily", [str(self.source), str(self.output)])])
        with (patch.object(window.sync_tab, "build_run_config", return_value=config),
              patch("src.ui.task_tab.run_bounded_preflight", return_value=(PreflightReport(language="en"), "", False)),
              patch("src.ui.task_tab.confirm_run_summary", return_value=False) as confirm,
              patch("src.ui.task_tab.TaskWorker") as worker):
            self.assertFalse(tab.start_all_tasks())
        confirm.assert_called_once()
        worker.assert_not_called()
        self.assertFalse(tab.is_running)

    def test_active_review_defers_schedule_without_consuming_attempt(self):
        tab = self.keep(TaskTab(self.config))
        tab.check_schedule.setChecked(True)
        tab._run_confirmation_active = True
        before = copy.deepcopy(self.config.values)
        with patch.object(tab, "start_all_tasks") as start:
            self.assertFalse(tab.check_scheduled_run())
        self.assertEqual(self.config.values, before)
        start.assert_not_called()

    def test_pdf_approved_review_starts_the_worker(self):
        tab = self.keep(PDFTab(self.config))
        file = self.source / "sample.pdf"
        file.write_bytes(b"pdf fixture")
        tab.selected_pdf_paths = [str(file)]
        tab.output_path_input.setText(str(self.output))
        with (patch("src.ui.pdf_tab.confirm_run_summary", return_value=True),
              patch("src.ui.pdf_tab.PDFConvertWorker") as worker):
            tab.start_conversion()
        worker.return_value.start.assert_called_once()
        self.assertEqual(worker.call_args.kwargs["pdf_paths"], [str(file)])
        self.assertTrue(tab.is_converting)

    def test_sync_approved_review_starts_worker_with_the_reviewed_groups(self):
        tab = self.keep(SyncTab(self.config))
        self.output.mkdir()
        tab.sync_groups = [{"name": "daily", "folders": [str(self.source), str(self.output)]}]
        tab._analysis_is_current = True
        tab._analysis_has_actions = True
        with (patch("src.ui.sync_tab.confirm_run_summary", return_value=True) as confirm,
              patch("src.ui.sync_tab.SyncWorker") as worker):
            tab.start_sync_execution()
        worker.return_value.start.assert_called_once()
        reviewed = confirm.call_args.args[1].get(TaskStep.SYNC).to_legacy_dict()["sync_groups"]
        self.assertEqual(worker.call_args.args[0], reviewed)


if __name__ == "__main__":
    unittest.main()
