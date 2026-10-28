from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.task_notifier import ReportNotification, deliver_report
from src.utils.logger import get_logger

logger = get_logger()


class NotificationWorker(QThread):
    """Deliver the result report off the UI thread so slow SMTP/webhooks cannot freeze it."""

    log_signal = pyqtSignal(str)

    def __init__(self, notification: ReportNotification, report_body: str, parent=None):
        super().__init__(parent)
        self.notification = notification
        self.report_body = report_body

    def run(self):
        try:
            deliver_report(self.notification, self.report_body, self.log_signal.emit)
        except Exception as exc:
            logger.exception("Unhandled notification worker failure")
            self.log_signal.emit(f"✗ {exc}")
