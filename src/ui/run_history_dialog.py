from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core.run_journal import RunJournal
from src.ui.i18n import tr


class RunHistoryDialog(QDialog):
    COL_STARTED = 0
    COL_TYPE = 1
    COL_STATUS = 2
    COL_FEATURES = 3
    COL_DETAIL = 4

    STATUS_COLORS = {
        "running": "#38bdf8",
        "completed": "#4ade80",
        "partial": "#fbbf24",
        "failed": "#f87171",
        "cancelled": "#fbbf24",
        "interrupted": "#f87171",
    }

    def __init__(self, journal: RunJournal, language: str, parent=None):
        super().__init__(parent)
        self.journal = journal
        self.language = language
        self.setWindowTitle(tr("run_history_title", language))
        self.resize(1050, 520)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(tr("run_history_intro", self.language))
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #94a3b8;")
        layout.addWidget(intro)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel(tr("run_history_filter", self.language)))
        self.status_filter = QComboBox()
        self.status_filter.addItem(tr("run_history_all", self.language), "")
        for status in ("completed", "partial", "failed", "cancelled", "interrupted", "running"):
            self.status_filter.addItem(tr(f"run_status_{status}", self.language), status)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filter_layout.addWidget(self.status_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            tr("run_history_started", self.language),
            tr("run_history_type", self.language),
            tr("run_history_status", self.language),
            tr("run_history_features", self.language),
            tr("run_history_detail", self.language),
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_STARTED, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.open_selected_report)
        layout.addWidget(self.table)

        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #64748b; padding: 8px;")
        layout.addWidget(self.empty_label)

        button_layout = QHBoxLayout()
        self.refresh_btn = QPushButton(tr("run_history_refresh", self.language))
        self.refresh_btn.clicked.connect(self.refresh)
        button_layout.addWidget(self.refresh_btn)
        self.open_btn = QPushButton(tr("run_history_open_report", self.language))
        self.open_btn.clicked.connect(self.open_selected_report)
        button_layout.addWidget(self.open_btn)
        self.folder_btn = QPushButton(tr("run_history_open_folder", self.language))
        self.folder_btn.clicked.connect(self.open_reports_folder)
        button_layout.addWidget(self.folder_btn)
        button_layout.addStretch()
        close_btn = QPushButton(tr("run_history_close", self.language))
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

    def refresh(self, _index: int | None = None) -> None:
        status = str(self.status_filter.currentData() or "")
        entries = self.journal.list_runs(status=status or None)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            started = self._format_timestamp(str(entry.get("started_at", "")))
            run_type = tr(
                "run_history_scheduled" if entry.get("scheduled") else "run_history_manual",
                self.language,
            )
            status_key = str(entry.get("status", "failed"))
            if status_key == "running" and entry.get("possibly_stalled"):
                status_text = tr("run_status_possibly_stalled", self.language)
            else:
                status_text = tr(f"run_status_{status_key}", self.language)
            features = ", ".join(
                tr(f"task_step_{step}", self.language)
                for step in entry.get("active_steps", [])
                if isinstance(step, str)
            )
            detail = str(entry.get("detail") or entry.get("message") or "")
            values = (started, run_type, status_text, features, detail)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == self.COL_STARTED:
                    item.setData(Qt.ItemDataRole.UserRole, entry["run_id"])
                if column == self.COL_STATUS:
                    item.setForeground(QColor(self.STATUS_COLORS.get(status_key, "#cbd5e1")))
                self.table.setItem(row, column, item)
        has_entries = bool(entries)
        self.empty_label.setText("" if has_entries else tr("run_history_empty", self.language))
        self.open_btn.setEnabled(has_entries)
        if has_entries:
            self.table.selectRow(0)

    def selected_run_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, self.COL_STARTED)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def open_selected_report(self, _index=None) -> None:
        run_id = self.selected_run_id()
        if not run_id:
            return
        try:
            report_path = self.journal.report_path(run_id)
        except ValueError:
            report_path = ""
        if not report_path or not os.path.isfile(report_path):
            QMessageBox.information(
                self,
                tr("run_history_report_unavailable_title", self.language),
                tr("run_history_report_unavailable", self.language),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(report_path))

    def open_reports_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.journal.reports_dir)))

    @staticmethod
    def _format_timestamp(value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return value
