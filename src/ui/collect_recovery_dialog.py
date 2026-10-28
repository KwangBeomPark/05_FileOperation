"""Guided, cancellable pending-copy recovery with explicit ownership consent."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from src.core.collect_recovery import (
    CollectRecoveryError,
    inspect_pending_copy,
    inspect_pending_release,
    recover_pending_copy,
)
from src.ui.i18n import tr
from src.utils.logger import get_logger

logger = get_logger()


class RecoveryWorker(QThread):
    """Run both the preview and the verified backup/commit off the GUI thread."""

    def __init__(self, path, decision=None, fingerprint="", parent=None):
        super().__init__(parent)
        self.path, self.decision, self.fingerprint = path, decision, fingerprint
        self.preview = None
        self.backup = None
        self.error = ""

    def run(self):
        try:
            if self.decision is None:
                try:
                    self.preview = inspect_pending_copy(
                        self.path, self.isInterruptionRequested
                    )
                except CollectRecoveryError as exc:
                    if exc.code != "unavailable":
                        raise
                    self.preview = inspect_pending_release(
                        self.path, self.isInterruptionRequested
                    )
            else:
                self.backup = recover_pending_copy(
                    self.path,
                    self.fingerprint,
                    self.decision,
                    self.isInterruptionRequested,
                )
        except CollectRecoveryError as exc:
            self.error = exc.code
        except Exception:
            logger.exception("Unexpected recovery worker error")
            self.error = "unavailable"


class CollectRecoveryDialog(QDialog):
    """Never infer ownership automatically and never close over a running worker."""

    def __init__(self, state_path, language, parent=None):
        super().__init__(parent)
        self.state_path, self.language = state_path, language
        self.worker = None
        self.preview = None
        self.backup_path = None
        self._close_requested = False
        self.setWindowTitle(self._msg("collect_recovery_title"))
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        self.status = QLabel(self._msg("collect_recovery_working"))
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        form = QFormLayout()
        self.source = QLineEdit()
        self.target = QLineEdit()
        for key, field in (
            ("collect_source", self.source),
            ("collect_recovery_target", self.target),
        ):
            field.setReadOnly(True)
            form.addRow(self._msg(key), field)
        layout.addLayout(form)
        self.note = QLabel(self._msg("collect_recovery_note"))
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        self.consent = QCheckBox(self._msg("collect_recovery_consent"))
        self.consent.toggled.connect(self._refresh_buttons)
        layout.addWidget(self.consent)
        self.ownership = QCheckBox(self._msg("collect_recovery_ownership"))
        self.ownership.toggled.connect(self._refresh_buttons)
        layout.addWidget(self.ownership)
        self.unverified_consent = QCheckBox(
            self._msg("collect_recovery_release_consent")
        )
        self.unverified_consent.toggled.connect(self._refresh_buttons)
        layout.addWidget(self.unverified_consent)
        buttons = QHBoxLayout()
        self.preserve_button = QPushButton(self._msg("collect_recovery_preserve"))
        self.adopt_button = QPushButton(self._msg("collect_recovery_adopt"))
        self.cancel_button = QPushButton(self._msg("diagnostics_cancel"))
        self.retry_button = QPushButton(self._msg("collect_recovery_retry"))
        self.retry_button.setAutoDefault(False)
        self.retry_button.clicked.connect(self._inspect)
        self.preserve_button.clicked.connect(lambda: self._apply("preserve"))
        self.adopt_button.clicked.connect(lambda: self._apply("adopt"))
        self.cancel_button.clicked.connect(self.reject)
        for button in (self.preserve_button, self.adopt_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.retry_button)
        self.cancel_button.setDefault(True)
        layout.addLayout(buttons)
        self._refresh_buttons()
        QTimer.singleShot(0, self._inspect)

    def _msg(self, key, **values):
        return tr(key, self.language, **values)

    def _refresh_buttons(self):
        ready = (
            self.worker is None
            and self.preview is not None
            and self.preview.status != "none"
        )
        self.consent.setEnabled(self.worker is None)
        self.retry_button.setEnabled(self.worker is None and not self._close_requested)
        matching = self.preview is not None and self.preview.status == "matching"
        unverified = self.preview is not None and self.preview.status == "unverified"
        self.note.setText(
            self._msg(
                "collect_recovery_unverified_note"
                if unverified
                else "collect_recovery_note"
            )
        )
        self.unverified_consent.setVisible(unverified)
        self.unverified_consent.setEnabled(self.worker is None)
        self.preserve_button.setText(
            self._msg(
                "collect_recovery_release"
                if unverified
                else "collect_recovery_preserve"
            )
        )
        self.ownership.setVisible(matching)
        self.ownership.setEnabled(self.worker is None and matching)
        self.preserve_button.setEnabled(
            ready
            and self.consent.isChecked()
            and (not unverified or self.unverified_consent.isChecked())
        )
        self.adopt_button.setEnabled(
            ready
            and self.consent.isChecked()
            and self.ownership.isChecked()
            and matching
        )

    def _inspect(self):
        if not self._close_requested and self.worker is None:
            self.preview = None
            self.consent.setChecked(False)
            self.ownership.setChecked(False)
            self.unverified_consent.setChecked(False)
            self._start_worker(RecoveryWorker(self.state_path, parent=self))

    def _start_worker(self, worker):
        self.worker = worker
        self.status.setText(self._msg("collect_recovery_working"))
        self._refresh_buttons()
        worker.finished.connect(lambda: self._finished(worker))
        try:
            worker.start()
        except Exception:
            logger.exception("Cannot start recovery worker")
            worker.error = "unavailable"
            self._finished(worker)

    def _apply(self, decision):
        if self.worker is not None or not self.preview or not self.consent.isChecked():
            return
        if self.preview.status == "unverified":
            if decision != "preserve" or not self.unverified_consent.isChecked():
                return
            decision = "release"
        if decision == "adopt" and (
            self.preview.status != "matching" or not self.ownership.isChecked()
        ):
            return
        self._start_worker(
            RecoveryWorker(self.state_path, decision, self.preview.fingerprint, self)
        )

    def _finished(self, worker):
        if self.worker is not worker or worker.isRunning():
            return
        self.worker = None
        if worker.error:
            self.preview = None
            self.status.setText(self._msg("collect_recovery_" + worker.error))
        elif worker.decision:
            self.backup_path = worker.backup
        else:
            self.preview = worker.preview
            self.source.setText(self.preview.source)
            self.target.setText(self.preview.target)
            key = (
                "preserve_status"
                if self.preview.status == "preserve"
                else self.preview.status
            )
            self.status.setText(self._msg("collect_recovery_" + key))
        worker.deleteLater()
        self._refresh_buttons()
        if self.backup_path:
            super().accept()
        elif self._close_requested:
            super().reject()

    def reject(self):
        self._close_requested = True
        if self.worker is not None:
            self.worker.requestInterruption()
            self.status.setText(self._msg("collect_stopping"))
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
            return
        super().closeEvent(event)
