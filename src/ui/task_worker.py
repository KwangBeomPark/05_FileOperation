from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.task_contracts import RunPlan, TaskStep
from src.core.task_runner import RunnerCallbacks, TaskRunner
from src.ui.i18n import get_app_language, tr
from src.utils.logger import get_logger

logger = get_logger()


class TaskWorker(QThread):
    log_signal = pyqtSignal(str)
    step_progress = pyqtSignal(int, int, str)
    total_progress = pyqtSignal(int)
    status_changed = pyqtSignal(str, str)
    item_status_changed = pyqtSignal(str, str)
    report_ready = pyqtSignal(object)
    outcome_ready = pyqtSignal(bool, str, str)

    def __init__(self, config_manager, run_plan: RunPlan):
        super().__init__()
        self.config_manager = config_manager
        self.runner = TaskRunner(config_manager, run_plan)
        self.outcome = (False, "", "")

    def stop(self):
        self.runner.cancel()

    def run(self):
        callbacks = RunnerCallbacks(
            log=self.log_signal.emit,
            item_status_changed=lambda key, status: self.item_status_changed.emit(key, status.value),
            step_progress=self.step_progress.emit,
            total_progress=self.total_progress.emit,
            status_changed=self._emit_status,
        )
        try:
            report = self.runner.run(callbacks)
            self.report_ready.emit(report)
            self.outcome = (report.overall_success, report.message, report.report_body)
        except Exception as exc:
            logger.exception("Unhandled task worker failure")
            self.outcome = (
                False,
                tr("task_worker_failed", get_app_language(self.config_manager), detail=str(exc)),
                "",
            )
        self.outcome_ready.emit(*self.outcome)

    def _emit_status(self, step: TaskStep, status):
        self.status_changed.emit(step.value, status.value)
