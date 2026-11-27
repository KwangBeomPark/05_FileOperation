from __future__ import annotations

from threading import Event

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
    sync_review_requested = pyqtSignal(str, object)

    def __init__(self, config_manager, run_plan: RunPlan):
        super().__init__()
        self.config_manager = config_manager
        self.runner = TaskRunner(config_manager, run_plan)
        self.outcome = (False, "", "")
        self._sync_review_ready = Event()
        self._sync_review_accepted = False

    def stop(self):
        try:
            self.runner.cancel()
        finally:
            self._sync_review_ready.set()

    def _request_sync_review(self, name, summary):
        self._sync_review_ready.clear()
        self._sync_review_accepted = False
        if not self.runner.is_running:
            return False
        self.sync_review_requested.emit(name, summary)
        self._sync_review_ready.wait()
        return self.runner.is_running and self._sync_review_accepted

    def resolve_sync_review(self, accepted):
        """Release the worker after the GUI records the user's decision."""
        self._sync_review_accepted = accepted
        self._sync_review_ready.set()

    def run(self):
        callbacks = RunnerCallbacks(
            log=self.log_signal.emit,
            item_status_changed=lambda key, status: self.item_status_changed.emit(key, status.value),
            step_progress=self.step_progress.emit,
            total_progress=self.total_progress.emit,
            status_changed=self._emit_status,
            review_sync=self._request_sync_review,
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
