"""Flat task rows and lazy run-history viewer for TaskTab."""

import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QListWidgetItem,
    QTableWidgetItem,
    QWidget,
)

from src.app_identity import user_data_dir
from src.core.collect_sync_config import build_collect_group
from src.core.task_contracts import CollectRunConfig, StepStatus, TaskStep
from src.ui.i18n import tr


class TaskPanelMixin:
    def row_type_label(self, step):
        if step == TaskStep.SYNC:
            return tr("tab_sync", self.language)
        if step == TaskStep.COLLECT_SYNC:
            return tr("tab_collect_sync", self.language)
        return "SA Team"

    def rebuild_status_table(self):
        if self.is_running:
            return
        rows = []
        for step, setting in (
            (TaskStep.SYNC, "sync_groups"),
            (TaskStep.COLLECT_SYNC, "collect_sync_groups"),
        ):
            groups = self.config_manager.get(setting, [])
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict) or not group.get("id"):
                    continue
                paths = (
                    group.get("folders", [])
                    if step == TaskStep.SYNC
                    else group.get("sources", [])
                )
                detail = (
                    " ↔ ".join(paths)
                    if step == TaskStep.SYNC
                    else " → ".join([", ".join(paths), group.get("target", "")])
                )
                if group.get("keywords"):
                    detail += " · " + ", ".join(group["keywords"])
                rows.append(
                    {
                        "key": f"{step.value}:{group['id']}",
                        "step": step,
                        "name": group.get("name", ""),
                        "group": group,
                        "paths": detail,
                    }
                )
        for step in (TaskStep.EML, TaskStep.PDF, TaskStep.OCR):
            rows.append(
                {
                    "key": step.value,
                    "step": step,
                    "name": self.step_label(step),
                    "paths": self.sa_task_paths(step),
                }
            )
        if rows == self.rows:
            return
        self.rows = rows
        self.status_table.setRowCount(0)
        self.status_table.setRowCount(len(rows))
        self.item_checks = {}
        self.step_checks = {}
        self.step_keys = {}
        selected = self.config_manager.get("task_enabled_items", {}) or {}
        legacy = self.config_manager.get("task_enabled_steps", ["sync"])
        for index, row in enumerate(rows):
            step = row["step"]
            self.step_keys.setdefault(step.value, index)
            check = QCheckBox()
            check.setAccessibleName(row["name"])
            check.setChecked(
                bool(
                    selected.get(
                        row["key"],
                        step.value in legacy
                        if step not in (TaskStep.SYNC, TaskStep.COLLECT_SYNC)
                        else False,
                    )
                )
            )
            holder = QWidget()
            layout = QHBoxLayout(holder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(check)
            for widget in (check, holder):
                widget.setProperty("task_row", index)
                widget.installEventFilter(self)
            self.status_table.setCellWidget(index, self.COL_RUN, holder)
            self.item_checks[row["key"]] = check
            self.step_checks.setdefault(step, check)
            for column in range(1, 8):
                self.status_table.setItem(index, column, QTableWidgetItem())
            self.status_table.item(index, self.COL_ORDER).setText(str(index + 1))
            self.status_table.item(index, self.COL_FEATURE).setText(row["name"])
            self.status_table.item(index, self.COL_TYPE).setText(
                self.row_type_label(step)
            )
            self.status_table.item(index, self.COL_PATHS).setText(row["paths"])
            self.status_table.item(index, self.COL_PATHS).setToolTip(row["paths"])
            self._set_status_item(
                self.status_table.item(index, self.COL_STATUS),
                "pending" if check.isChecked() else "skipped",
            )
            self.set_row_readiness(
                index, "not_checked" if check.isChecked() else "not_selected"
            )
            check.toggled.connect(self.save_enabled_steps)
        self.refresh_history_display()
        self._refresh_start_button_state()

    def sa_task_paths(self, step):
        if step == TaskStep.EML:
            tasks = self.config_manager.get("eml_tasks", [])
            if isinstance(tasks, list):
                return "; ".join(
                    f"{task.get('source_folder', '')} → {task.get('target_folder', '')}"
                    for task in tasks
                    if isinstance(task, dict)
                )
        if step == TaskStep.PDF:
            tab = self._feature_tabs().get(step)
            paths = getattr(tab, "selected_pdf_paths", [])
            if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
                output = (
                    tab.output_path_input.text()
                    if tab and hasattr(tab, "output_path_input")
                    else ""
                )
                return ", ".join(paths) + (f" → {output}" if output else "")
        if step == TaskStep.OCR:
            return " · ".join(
                str(self.config_manager.get(key, default))
                for key, default in (
                    ("ocr_rule_mode", "promotion"),
                    ("ocr_custom_pattern", ""),
                    ("ocr_rename_template", "{match}"),
                )
            )
        return ""

    def build_row_config(self, row):
        tabs = self._feature_tabs()
        tab = tabs.get(row["step"])
        if tab is None:
            raise ValueError(tr("task_readiness_tab_unavailable", self.language))
        if row["step"] == TaskStep.SYNC:
            return tab.build_run_config(group_ids={row["group"]["id"]})
        if row["step"] == TaskStep.COLLECT_SYNC:
            if getattr(tab, "_invalid_saved", False) or getattr(
                tab, "_save_failed", False
            ):
                raise ValueError(tr("collect_invalid_saved", self.language))
            return CollectRunConfig(
                (build_collect_group(row["group"]),),
                str(tab.state_path),
                tuple(build_collect_group(group) for group in tab.groups),
            )
        return self._build_step_config(row["step"], tabs, self.selected_steps())

    def navigate_row(self, index, _column=0):
        if self.is_running or not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        tab = self._feature_tabs().get(row["step"])
        if tab is None:
            return
        group = row.get("group")
        if group:
            groups = tab.sync_groups if row["step"] == TaskStep.SYNC else tab.groups
            for group_index, value in enumerate(groups):
                if value.get("id") == group["id"]:
                    tab.group_combo.setCurrentIndex(group_index)
                    break
        window = self.window()
        if hasattr(window, "select_feature_tab"):
            window.select_feature_tab(tab)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonDblClick:
            row = watched.property("task_row")
            if row is not None:
                self.navigate_row(row)
                return True
        return super().eventFilter(watched, event)

    def update_item_status(self, key, status):
        for index, row in enumerate(self.rows):
            if row["key"] == key:
                status_key = next(
                    (
                        value.name.lower()
                        for value in StepStatus
                        if value.value == status
                    ),
                    "failed",
                )
                self._set_status_item(
                    self.status_table.item(index, self.COL_STATUS), status_key
                )
                self.current_step = row["step"]
                self._record_activity(current_step=row["step"], detail=row["name"])
                break

    def refresh_history_language(self):
        for combo in (self.type_filter, self.status_filter):
            combo.blockSignals(True)
        kind, status = self.type_filter.currentData(), self.status_filter.currentData()
        self.type_filter.clear()
        self.type_filter.addItem(
            self._text("All types", "전체 유형", "Wszystkie typy"), ""
        )
        self.type_filter.addItem("SA Team", "sa_team")
        for step in (
            TaskStep.SYNC,
            TaskStep.COLLECT_SYNC,
            TaskStep.EML,
            TaskStep.PDF,
            TaskStep.OCR,
            TaskStep.BYPASS,
        ):
            self.type_filter.addItem(
                self.row_type_label(step)
                if step in (TaskStep.SYNC, TaskStep.COLLECT_SYNC)
                else self.step_label(step),
                step.value,
            )
        self.status_filter.clear()
        self.status_filter.addItem(
            self._text("All statuses", "전체 상태", "Wszystkie stany"), ""
        )
        for value in (
            "running",
            "completed",
            "partial",
            "failed",
            "cancelled",
            "interrupted",
        ):
            self.status_filter.addItem(tr("run_status_" + value, self.language), value)
        self.type_filter.setCurrentIndex(max(0, self.type_filter.findData(kind)))
        self.status_filter.setCurrentIndex(max(0, self.status_filter.findData(status)))
        for combo in (self.type_filter, self.status_filter):
            combo.blockSignals(False)
        self.log_export_btn.setText(
            self._text("Export log…", "로그 내보내기…", "Eksportuj dziennik…")
        )
        self.log_search.setPlaceholderText(self._text("Search...", "검색...", "Szukaj..."))
        self.log_search_prev_btn.setText(self._text("Previous", "이전", "Poprzedni"))
        self.log_search_next_btn.setText(self._text("Next", "다음", "Następny"))
        self.log_copy_btn.setText(self._text("Copy All", "전체 복사", "Kopiuj wszystko"))
        self.log_notepad_btn.setText(self._text("Open in Notepad", "메모장으로 열기", "Otwórz w Notatniku"))
        self.log_folder_btn.setText(
            self._text("Open Folder", "폴더 열기", "Otwórz folder")
        )
        self.log_clear_btn.setText(
            self._text("Clear log", "로그 지우기", "Wyczyść dziennik")
        )
        self.refresh_run_list()

    def refresh_run_list(self, *_args):
        if not hasattr(self, "history_list"):
            return
        current = self.history_list.currentItem()
        current_id = (
            (current.data(Qt.ItemDataRole.UserRole) or {}).get("run_id")
            if current
            else None
        )
        self.history_list.blockSignals(True)
        self.history_list.clear()
        self.history_list.addItem(
            self._text(
                "● Current execution log (live)",
                "● 현재 실행 로그 (실시간)",
                "● Bieżący dziennik (na żywo)",
            )
        )
        target = 0
        if self.run_journal:
            try:
                entries = self.run_journal.list_runs(
                    status=self.status_filter.currentData() or None
                )
            except OSError as exc:
                self.log(str(exc))
                entries = []
            kind = self.type_filter.currentData()
            for entry in entries:
                active = entry.get("active_steps", [])
                if kind == "sa_team" and not set(active) & {"eml", "pdf", "ocr"}:
                    continue
                if kind and kind != "sa_team" and kind not in active:
                    continue
                item = QListWidgetItem(
                    f"{entry['started_at'].replace('T', ' ')[:16]} · {tr('run_status_' + entry['status'], self.language)}"
                )
                item.setToolTip(
                    ", ".join(
                        self.step_label(TaskStep(step))
                        for step in entry.get("active_steps", [])
                        if step in TaskStep._value2member_map_
                    )
                )
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self.history_list.addItem(item)
                if entry["run_id"] == current_id:
                    target = self.history_list.count() - 1
        self.history_list.setCurrentRow(target)
        self.history_list.blockSignals(False)
        self.show_history_item(self.history_list.currentItem())

    def show_history_item(self, item, _previous=None):
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._viewer_report_path = None
        if not entry:
            self.log_area.setMaximumBlockCount(20000)
            self.log_label.setText(tr("task_log_title", self.language))
            self.log_area.setPlainText("\n".join(self.live_log))
            scrollbar = self.log_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            self.log_clear_btn.setEnabled(True)
        else:
            self.log_area.setMaximumBlockCount(0)
            self.log_label.setText(
                f"{entry['started_at'].replace('T', ' ')[:16]} · {tr('run_status_' + entry['status'], self.language)}"
            )
            self.log_clear_btn.setEnabled(False)
            try:
                path = Path(
                    entry.get("report_path")
                    or self.run_journal.report_path(entry["run_id"])
                )
                self.log_area.setPlainText(path.read_text(encoding="utf-8-sig"))
                self._viewer_report_path = path
            except (OSError, ValueError) as exc:
                self.log_area.setPlainText(
                    self._text(
                        "Report unavailable: ",
                        "보고서를 열 수 없습니다: ",
                        "Raport niedostępny: ",
                    )
                    + str(exc)
                )
        self.find_viewer_text(restart=True)

    def find_viewer_text(self, *, backward=False, restart=False):
        query = self.log_search.text()
        cursor = self.log_area.textCursor()
        if not query:
            if cursor.hasSelection():
                cursor.clearSelection()
                self.log_area.setTextCursor(cursor)
            return
        boundary = QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
        if restart:
            cursor.movePosition(boundary)
            self.log_area.setTextCursor(cursor)
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if not self.log_area.find(query, flags):
            cursor.movePosition(boundary)
            self.log_area.setTextCursor(cursor)
            self.log_area.find(query, flags)

    def open_viewer_in_notepad(self):
        try:
            path = self._viewer_report_path
            if path is None:
                if not hasattr(self, "_log_temp_dir"):
                    self._log_temp_dir = tempfile.TemporaryDirectory(prefix="fileops-log-")
                path = Path(self._log_temp_dir.name) / "execution.txt"
                path.write_text(self.log_area.toPlainText(), encoding="utf-8-sig")
            subprocess.Popen(["notepad.exe", str(path)])
        except OSError as exc:
            self.log(str(exc))

    def clear_live_log(self):
        self.live_log.clear()
        if self.history_list.currentRow() == 0:
            self.log_area.clear()

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.log_export_btn.text(), "execution.txt", "Text (*.txt)"
        )
        if path:
            try:
                Path(path).write_text(self.log_area.toPlainText(), encoding="utf-8")
            except OSError as exc:
                self.log(str(exc))

    def open_reports_folder(self):
        folder = (
            self.run_journal.reports_dir
            if self.run_journal
            else user_data_dir() / "reports"
        )
        try:
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except OSError as exc:
            self.log(str(exc))
