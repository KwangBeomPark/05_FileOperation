from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
)

from src.core.diagnostics import DiagnosticItem, DiagnosticStatus, run_diagnostics
from src.core.task_contracts import RunPlan
from src.ui.i18n import get_app_language, tr
from src.utils.logger import get_logger


logger = get_logger()


class DiagnosticsWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, run_plan, config_manager, auto_email, initial_items=None):
        super().__init__()
        self.run_plan = run_plan
        self.config_manager = config_manager
        self.auto_email = auto_email
        self.initial_items = list(initial_items or [])

    def run(self):
        try:
            items = self.initial_items + run_diagnostics(
                self.run_plan,
                self.config_manager,
                auto_email=self.auto_email,
            )
            self.completed.emit(items)
        except Exception as exc:
            logger.exception("Diagnostics failed unexpectedly")
            self.failed.emit(str(exc))


class DiagnosticsDialog(QDialog):
    def __init__(
        self,
        config_manager,
        run_plan: RunPlan,
        initial_items: list[DiagnosticItem],
        navigate: Callable[[str], None],
        *,
        auto_email: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.config_manager = config_manager
        self.run_plan = run_plan
        self.initial_items = initial_items
        self.navigate = navigate
        self.auto_email = auto_email
        self.worker = None
        self.is_running = False
        self._build_ui()
        QTimer.singleShot(0, self.start_diagnostics)

    @property
    def language(self):
        return get_app_language(self.config_manager)

    def _build_ui(self):
        self.setWindowTitle(tr("diagnostics_title", self.language))
        self.resize(900, 560)
        self.setMinimumSize(720, 460)
        layout = QVBoxLayout(self)

        self.intro_label = QLabel(tr("diagnostics_intro", self.language))
        self.intro_label.setWordWrap(True)
        self.intro_label.setStyleSheet("color: #cbd5e1; padding: 4px;")
        layout.addWidget(self.intro_label)

        self.summary_label = QLabel(tr("diagnostics_running", self.language))
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #7dd3fc; font-weight: bold; padding: 4px;")
        layout.addWidget(self.summary_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            tr("diagnostics_check_header", self.language),
            tr("diagnostics_status_header", self.language),
            tr("diagnostics_detail_header", self.language),
            tr("diagnostics_fix_header", self.language),
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.run_again_btn = QPushButton(tr("diagnostics_run_again", self.language))
        self.run_again_btn.setEnabled(False)
        self.run_again_btn.clicked.connect(self.start_diagnostics)
        buttons.addWidget(self.run_again_btn)
        self.close_btn = QPushButton(tr("diagnostics_close", self.language))
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    def start_diagnostics(self):
        if self.is_running:
            return
        self.is_running = True
        self.table.setRowCount(0)
        self.summary_label.setText(tr("diagnostics_running", self.language))
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.run_again_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.worker = DiagnosticsWorker(
            self.run_plan,
            self.config_manager,
            self.auto_email,
            self.initial_items,
        )
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_completed(self, items):
        self.is_running = False
        self._populate(items)
        failures = sum(item.status == DiagnosticStatus.FAIL for item in items)
        warnings = sum(item.status == DiagnosticStatus.WARNING for item in items)
        passed = sum(item.status == DiagnosticStatus.PASS for item in items)
        self.summary_label.setText(tr(
            "diagnostics_summary",
            self.language,
            passed=passed,
            warnings=warnings,
            failures=failures,
        ))
        self.summary_label.setStyleSheet(
            "color: #f87171; font-weight: bold; padding: 4px;"
            if failures else
            "color: #fbbf24; font-weight: bold; padding: 4px;"
            if warnings else
            "color: #4ade80; font-weight: bold; padding: 4px;"
        )
        self.progress_bar.hide()
        self.run_again_btn.setEnabled(True)
        self.close_btn.setEnabled(True)

    def _on_failed(self, detail):
        self.is_running = False
        self.summary_label.setText(tr("diagnostics_unexpected_failure", self.language, detail=detail))
        self.summary_label.setStyleSheet("color: #f87171; font-weight: bold; padding: 4px;")
        self.progress_bar.hide()
        self.run_again_btn.setEnabled(True)
        self.close_btn.setEnabled(True)

    def _populate(self, items: list[DiagnosticItem]):
        self.table.setRowCount(len(items))
        status_keys = {
            DiagnosticStatus.PASS: "diagnostics_status_pass",
            DiagnosticStatus.WARNING: "diagnostics_status_warning",
            DiagnosticStatus.FAIL: "diagnostics_status_fail",
        }
        status_colors = {
            DiagnosticStatus.PASS: QColor("#4ade80"),
            DiagnosticStatus.WARNING: QColor("#fbbf24"),
            DiagnosticStatus.FAIL: QColor("#f87171"),
        }
        for row, diagnostic in enumerate(items):
            title_item = QTableWidgetItem(diagnostic.title)
            status_item = QTableWidgetItem(tr(status_keys[diagnostic.status], self.language))
            status_item.setForeground(status_colors[diagnostic.status])
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            detail_item = QTableWidgetItem(diagnostic.detail)
            detail_item.setToolTip(diagnostic.detail)
            self.table.setItem(row, 0, title_item)
            self.table.setItem(row, 1, status_item)
            self.table.setItem(row, 2, detail_item)

            if diagnostic.status != DiagnosticStatus.PASS and diagnostic.target:
                action = QPushButton(tr("diagnostics_open_fix", self.language))
                action.clicked.connect(lambda _checked=False, target=diagnostic.target: self._open_target(target))
                self.table.setCellWidget(row, 3, action)
        self.table.resizeRowsToContents()

    def _open_target(self, target):
        self.accept()
        self.navigate(target)

    def closeEvent(self, event):
        if self.is_running:
            event.ignore()
            return
        super().closeEvent(event)
