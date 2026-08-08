from __future__ import annotations

from threading import Event

from PyQt6.QtCore import QEventLoop, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from src.core.preflight import check_run_plan
from src.ui.i18n import choose, get_app_language
from src.utils.logger import get_logger


logger = get_logger()


class PreflightWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, run_plan, config_manager, auto_email: bool):
        super().__init__()
        self.run_plan = run_plan
        self.config_manager = config_manager
        self.auto_email = auto_email
        self.cancel_event = Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            report = check_run_plan(
                self.run_plan,
                self.config_manager,
                auto_email=self.auto_email,
                check_office=True,
                isolated=True,
                cancel_event=self.cancel_event,
            )
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.completed.emit(report)
        except Exception as exc:
            logger.exception("Bounded preflight failed unexpectedly")
            self.failed.emit(str(exc))


class PreflightProgressDialog(QDialog):
    def __init__(self, worker: PreflightWorker, config_manager, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.language = get_app_language(config_manager)
        self.report = None
        self.error = ""
        self.was_cancelled = False
        self._build_ui()
        QTimer.singleShot(0, self.worker.start)

    def _t(self, en: str, ko: str, pl: str) -> str:
        return choose(self.language, en, ko, pl)

    def _build_ui(self):
        self.setWindowTitle(self._t("Preflight Check", "실행 전 점검", "Kontrola przed uruchomieniem"))
        self.setModal(True)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self.message = QLabel(self._t(
            "Checking selected dependencies in isolated processes. Each external check has a fixed timeout.",
            "선택한 외부 구성요소를 격리된 프로세스에서 확인하고 있습니다. 각 검사는 정해진 제한 시간 안에 종료됩니다.",
            "Sprawdzanie zależności w odizolowanych procesach. Każda kontrola ma stały limit czasu.",
        ))
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        layout.addWidget(progress)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton(self._t("Cancel", "취소", "Anuluj"))
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)

    def cancel(self):
        if not self.worker.isRunning():
            return
        self.cancel_button.setEnabled(False)
        self.message.setText(self._t(
            "Stopping the active check...",
            "실행 중인 점검을 중지하는 중입니다...",
            "Zatrzymywanie aktywnej kontroli...",
        ))
        self.worker.cancel()

    def _completed(self, report):
        self.report = report
        self.accept()

    def _failed(self, error):
        self.error = error
        self.reject()

    def _cancelled(self):
        self.was_cancelled = True
        self.reject()

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.cancel()
            event.ignore()
            return
        super().closeEvent(event)


def run_bounded_preflight(parent, run_plan, config_manager, *, auto_email: bool, visible: bool):
    """Return (report, error, cancelled) while keeping the Qt event loop responsive."""
    worker = PreflightWorker(run_plan, config_manager, auto_email)
    if visible:
        dialog = PreflightProgressDialog(worker, config_manager, parent)
        dialog.exec()
        worker.wait(1500)
        return dialog.report, dialog.error, dialog.was_cancelled

    state = {"report": None, "error": "", "cancelled": False}
    loop = QEventLoop(parent)

    def completed(report):
        state["report"] = report
        loop.quit()

    def failed(error):
        state["error"] = error
        loop.quit()

    def cancelled():
        state["cancelled"] = True
        loop.quit()

    worker.completed.connect(completed)
    worker.failed.connect(failed)
    worker.cancelled.connect(cancelled)
    worker.start()
    loop.exec()
    worker.wait(1500)
    return state["report"], state["error"], state["cancelled"]
