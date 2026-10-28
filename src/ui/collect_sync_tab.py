"""Keyword collection editor and cancellable manual preview/test worker."""

from __future__ import annotations

import copy
import os
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from time import monotonic

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.app_identity import user_data_dir
from src.core.collect_report import collect_step_result
from src.core.collect_sync import (
    ACTION_COPY,
    ACTION_ERROR,
    ACTION_REPLACE,
    ACTION_TARGET_NEWER,
    ACTION_UNCHANGED,
    CollectAction,
    CollectConfigError,
    CollectRecoveryRequired,
    CollectReport,
    CollectRunError,
    CollectStateError,
    run_collect_groups,
)
from src.core.collect_sync_config import (
    build_collect_group,
    collect_group_dict,
    collect_schedule_decision,
    local_now,
    new_collect_group,
)
from src.core.run_journal import RunJournal
from src.core.task_contracts import RunReport, StepStatus, TaskStep
from src.ui.collect_recovery_dialog import CollectRecoveryDialog
from src.ui.i18n import get_app_language, tr
from src.utils.atomic_write import atomic_write_json
from src.utils.logger import get_logger

logger = get_logger()
KINDS = (
    ACTION_COPY,
    ACTION_REPLACE,
    ACTION_UNCHANGED,
    ACTION_TARGET_NEWER,
    ACTION_ERROR,
)


class CollectWorker(QThread):
    """Run all disk access off the GUI thread; stop at the next file boundary."""

    progress = pyqtSignal(int, int, str)

    def __init__(
        self,
        groups,
        state_path,
        report_path,
        dry_run=False,
        parent=None,
        *,
        configured_groups=None,
        language="en",
        journal_dir=None,
    ):
        super().__init__(parent)
        self.groups = tuple(groups)
        self.configured_groups = (
            tuple(configured_groups) if configured_groups is not None else self.groups
        )
        self.state_path = state_path
        self.report_path = report_path
        self.dry_run = dry_run
        self.report = CollectReport()
        self.error_code = ""
        self.blocked_before_run = False
        self._last_progress_at = 0.0
        self.language = language
        self.journal_dir = journal_dir
        self.run_id = ""

    def stop(self):
        self.requestInterruption()

    def _emit_progress(self, current, total, message):
        """Avoid flooding the GUI queue while processing many unchanged small files."""
        now = monotonic()
        if current in (0, total) or now - self._last_progress_at >= 0.1:
            self._last_progress_at = now
            self.progress.emit(current, total, message)

    def run(self):
        journal = None
        if not self.dry_run:
            try:
                journal = RunJournal(self.journal_dir or self.state_path.parent)
                self.run_id = journal.start_run([TaskStep.COLLECT_SYNC], scheduled=False, language=self.language)
            except Exception:
                logger.exception("Cannot start collect journal")
        try:
            self.report = run_collect_groups(
                self.groups,
                self.state_path,
                dry_run=self.dry_run,
                progress_callback=self._emit_progress,
                should_cancel=self.isInterruptionRequested,
                configured_groups=self.configured_groups,
            )
        except (CollectStateError, CollectRunError) as exc:
            logger.exception("Collect execution stopped with partial results")
            self.report = exc.report or CollectReport()
            self.blocked_before_run = (
                isinstance(exc, CollectStateError) and exc.report is None
            )
            if not self.report.count(ACTION_ERROR):
                self.report.actions.append(
                    CollectAction(
                        ACTION_ERROR,
                        source=str(self.state_path),
                        message_code="pending"
                        if isinstance(exc, CollectRecoveryRequired)
                        else "state",
                    )
                )
            self.error_code = (
                "collect_recovery_required"
                if isinstance(exc, CollectRecoveryRequired)
                else "collect_state_error"
                if isinstance(exc, CollectStateError)
                else "collect_error_io"
            )
        except Exception:
            logger.exception("Collect worker failed")
            self.error_code = "collect_error_io"
        if not self.dry_run:
            try:
                report_path = self.report_path
                if self.blocked_before_run:
                    report_path = report_path.with_name(
                        f"{report_path.stem}.blocked{report_path.suffix}"
                    )
                atomic_write_json(
                    report_path,
                    {
                        "finished_at": local_now().isoformat(timespec="seconds"),
                        "groups": [collect_group_dict(group) for group in self.groups],
                        "cancelled": self.report.cancelled,
                        "error_code": self.error_code,
                        "actions": [asdict(action) for action in self.report.actions],
                    },
                    ensure_ascii=True,
                )
            except (OSError, ValueError):
                logger.exception("Cannot save collect run report")
                self.error_code = self.error_code or "collect_save_error"
            if journal and self.run_id:
                result = collect_step_result(self.report, self.language, self.error_code)
                status = result.status
                body = "\n".join([
                    "# " + tr("task_step_collect_sync", self.language),
                    ", ".join(group.name for group in self.groups),
                    tr("task_status_" + status.name.lower(), self.language),
                    *result.details,
                ])
                try:
                    journal.finish_run(self.run_id, RunReport({TaskStep.COLLECT_SYNC: result}, body,
                                       result.error_message, status == StepStatus.COMPLETED, self.report.cancelled))
                except Exception:
                    logger.exception("Cannot finish collect journal")


class CollectSyncTab(QWidget):
    """Edit rules and manually preview/test one group. TaskTab owns scheduling."""

    RESULT_ROW_LIMIT = 2000

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.groups = []
        self.current_group_idx = -1
        self.worker = None
        self.is_running = False
        self._confirmation_active = False
        self._ui_locked = False
        self._loading = False
        self._invalid_saved = False
        self._save_failed = False
        self._status_key = "collect_ready"
        self._last_report = None
        self._result_page = 0
        self._report_dry_run = False
        self._result_group_id = ""
        self._result_group_name = ""
        self._scheduled = False
        self.state_path = user_data_dir() / "collect_sync_state.json"
        self._init_ui()
        self.load_saved_data()
        self.refresh_language()
        self.setAcceptDrops(True)

    @property
    def language(self):
        return get_app_language(self.config_manager)

    @property
    def is_busy(self):
        """Include modal interactions: their nested event loop also dispatches timers."""
        return self.is_running or self._confirmation_active

    @contextmanager
    def _interaction_guard(self):
        """Hold the execution gate while a modal editor/confirmation is open."""
        self._confirmation_active = True
        window = self.window()
        try:
            self._refresh_enabled()
            if hasattr(window, "set_all_tabs_locked"):
                window.set_all_tabs_locked(True)
            yield
        finally:
            self._confirmation_active = False
            if hasattr(window, "set_all_tabs_locked"):
                window.set_all_tabs_locked(False)
            self._refresh_enabled()

    def _msg(self, key, **values):
        return tr(key, self.language, **values)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.editor = QGroupBox()
        layout.addWidget(self.editor)
        form = QVBoxLayout(self.editor)
        self._labels = {}
        self._buttons = {}
        row = QHBoxLayout()
        self.group_combo = QComboBox()
        row.addWidget(self.group_combo, 1)
        for key, handler in (
            ("collect_add", self.add_group),
            ("collect_rename", self.rename_group),
            ("collect_delete", self.delete_group),
        ):
            button = QPushButton()
            button.clicked.connect(handler)
            self._buttons[key] = button
            row.addWidget(button)
        form.addLayout(row)
        self.group_combo.currentIndexChanged.connect(self.on_group_changed)
        self._labels["collect_sources"] = QLabel()
        form.addWidget(self._labels["collect_sources"])
        self.source_list = QListWidget()
        self.source_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.source_list.setMaximumHeight(110)
        self.source_list.setAcceptDrops(False)
        form.addWidget(self.source_list)
        row = QHBoxLayout()
        for key, handler in (
            ("collect_add_source", self.add_source),
            ("collect_remove_source", self.remove_sources),
        ):
            button = QPushButton()
            button.clicked.connect(handler)
            self._buttons[key] = button
            row.addWidget(button)
        row.addStretch()
        form.addLayout(row)
        fields = QFormLayout()
        self.keywords_input = QLineEdit()
        self.subfolders_check = QCheckBox()
        self.target_input = QLineEdit()
        self.target_button = QPushButton()
        self.target_button.clicked.connect(self.choose_target)
        target_row = QHBoxLayout()
        target_row.addWidget(self.target_input, 1)
        target_row.addWidget(self.target_button)
        for key, field in (
            ("collect_keywords", self.keywords_input),
            ("collect_target", target_row),
        ):
            label = QLabel()
            self._labels[key] = label
            fields.addRow(label, field)
        form.addLayout(fields)
        form.addWidget(self.subfolders_check)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        self.preview_button = QPushButton()
        self.run_button = QPushButton()
        self.stop_button = QPushButton()
        self.recovery_button = QPushButton()
        self.preview_button.clicked.connect(self.start_dry_run)
        self.run_button.clicked.connect(self.start_execution)
        self.stop_button.clicked.connect(self.stop)
        self.recovery_button.clicked.connect(self.start_recovery)
        for button in (
            self.preview_button,
            self.run_button,
            self.stop_button,
            self.recovery_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel()
        self.summary_label = QLabel()
        for label in (self.status_label, self.summary_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.table = QTableWidget(0, 5)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((125, 390, 220, 230)):
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 1)
        self.result_pager = QWidget()
        pager = QHBoxLayout(self.result_pager)
        pager.setContentsMargins(0, 0, 0, 0)
        self.previous_page_button = QPushButton()
        self.next_page_button = QPushButton()
        self.page_label = QLabel()
        self.previous_page_button.clicked.connect(lambda: self._change_result_page(-1))
        self.next_page_button.clicked.connect(lambda: self._change_result_page(1))
        pager.addWidget(self.previous_page_button)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_page_button)
        pager.addStretch()
        layout.addWidget(self.result_pager)
        self.result_pager.hide()
        for widget in (self.keywords_input, self.target_input):
            widget.editingFinished.connect(self._save_editor)
        for widget in (self.subfolders_check,):
            widget.toggled.connect(self._save_editor)

    def load_saved_data(self):
        """Keep malformed saved content untouched rather than silently resetting it."""
        saved = copy.deepcopy(self.config_manager.get("collect_sync_groups", []))
        interrupted = False
        try:
            if not isinstance(saved, list):
                raise CollectConfigError("Group list expected")
            ids = set()
            for group in saved:
                build_collect_group(group)
                identity = group.setdefault("id", uuid.uuid4().hex)
                if (
                    not isinstance(identity, str)
                    or not identity.isalnum()
                    or identity in ids
                ):
                    raise CollectConfigError("Invalid or duplicate group id")
                ids.add(identity)
                collect_schedule_decision(group, local_now())
                if group.get("schedule_last_result") == "running":
                    group.update(
                        schedule_last_result="interrupted",
                        schedule_last_failure_reason="collect_interrupted",
                        schedule_last_failure_at=local_now().isoformat(
                            timespec="seconds"
                        ),
                    )
                    interrupted = True
        except (CollectConfigError, TypeError, ValueError):
            logger.exception("Invalid saved collect groups; not overwritten")
            self._invalid_saved = True
            self._status_key = "collect_invalid_saved"
            saved = []
        self.groups = saved
        self._reload_combo(0)
        if interrupted and not self._invalid_saved:
            self.save_data()

    def save_data(self):
        """ConfigManager atomically commits disk before memory; check its result."""
        if self._invalid_saved:
            return False
        try:
            success = self.config_manager.set(
                "collect_sync_groups", copy.deepcopy(self.groups)
            )
        except Exception:
            logger.exception("Collect settings save failed")
            success = False
        self._save_failed = not bool(success)
        if self._save_failed:
            self._status_key = "collect_save_error"
        self.status_label.setText(self._msg(self._status_key))
        return not self._save_failed

    def _reload_combo(self, index):
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        for group in self.groups:
            self.group_combo.addItem(group["name"])
        self.group_combo.setCurrentIndex(min(index, len(self.groups) - 1))
        self.group_combo.blockSignals(False)
        self.on_group_changed(self.group_combo.currentIndex())

    def on_group_changed(self, index):
        self.current_group_idx = index
        self._loading = True
        group = self.groups[index] if 0 <= index < len(self.groups) else {}
        self.source_list.clear()
        self.source_list.addItems(group.get("sources", []))
        self.keywords_input.setText(", ".join(group.get("keywords", [])))
        self.target_input.setText(group.get("target", ""))
        self.subfolders_check.setChecked(bool(group.get("include_subfolders", False)))
        self._loading = False
        self._clear_results()
        self._refresh_enabled()
        self.refresh_schedule_summary()

    def _save_editor(self, *_args):
        if (
            self._loading
            or self.is_running
            or self._ui_locked
            or self.current_group_idx < 0
        ):
            return
        group = self.groups[self.current_group_idx]
        group.update(
            sources=[
                self.source_list.item(i).text() for i in range(self.source_list.count())
            ],
            keywords=[
                item.strip()
                for item in self.keywords_input.text().split(",")
                if item.strip()
            ],
            target=self.target_input.text().strip(),
            include_subfolders=self.subfolders_check.isChecked(),
        )
        self._clear_results()
        self.save_data()
        self._refresh_enabled()
        self.refresh_schedule_summary()

    def add_group(self):
        if (
            self.is_busy
            or self._ui_locked
            or self._invalid_saved
            or self._other_tasks_running()
        ):
            return
        with self._interaction_guard():
            name, accepted = QInputDialog.getText(
                self, self._msg("collect_add"), self._msg("collect_name")
            )
        if accepted and name.strip():
            self.groups.append(new_collect_group(name.strip()))
            self.save_data()
            self._reload_combo(len(self.groups) - 1)

    def rename_group(self):
        if (
            self.current_group_idx < 0
            or self.is_busy
            or self._ui_locked
            or self._other_tasks_running()
        ):
            return
        group = self.groups[self.current_group_idx]
        with self._interaction_guard():
            name, accepted = QInputDialog.getText(
                self,
                self._msg("collect_rename"),
                self._msg("collect_name"),
                text=group["name"],
            )
        if accepted and name.strip():
            group["name"] = name.strip()
            self.save_data()
            self._reload_combo(self.current_group_idx)

    def delete_group(self):
        if (
            self.current_group_idx < 0
            or self.is_busy
            or self._ui_locked
            or self._other_tasks_running()
        ):
            return
        with self._interaction_guard():
            reply = QMessageBox.question(
                self,
                self._msg("collect_delete"),
                self._msg("collect_delete_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self.groups[self.current_group_idx]
        self.save_data()
        self._reload_combo(max(0, self.current_group_idx - 1))

    def add_source_paths(self, paths):
        """Add paths without network/stat calls in the GUI thread."""
        if self.is_running or self._ui_locked or self.current_group_idx < 0:
            return
        used = {
            os.path.normcase(os.path.abspath(self.source_list.item(i).text()))
            for i in range(self.source_list.count())
        }
        for path in paths:
            key = os.path.normcase(os.path.abspath(path))
            if path and key not in used:
                self.source_list.addItem(path)
                used.add(key)
        self._save_editor()

    def add_source(self):
        if (
            self.is_busy
            or self._ui_locked
            or self.current_group_idx < 0
            or self._other_tasks_running()
        ):
            return
        with self._interaction_guard():
            path = QFileDialog.getExistingDirectory(
                self, self._msg("collect_add_source")
            )
        if path:
            self.add_source_paths([path])

    def remove_sources(self):
        if self.is_running or self._ui_locked:
            return
        for item in self.source_list.selectedItems():
            self.source_list.takeItem(self.source_list.row(item))
        self._save_editor()

    def choose_target(self):
        if (
            self.is_busy
            or self._ui_locked
            or self.current_group_idx < 0
            or self._other_tasks_running()
        ):
            return
        with self._interaction_guard():
            path = QFileDialog.getExistingDirectory(self, self._msg("collect_target"))
        if path:
            self.target_input.setText(path)
            self._save_editor()

    def dragEnterEvent(self, event):
        if (
            not self.is_running
            and not self._ui_locked
            and self.current_group_idx >= 0
            and event.mimeData().hasUrls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_source_paths(
            [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        )
        event.acceptProposedAction()

    def build_run_config(self, index=None):
        """Create a typed snapshot; filesystem checks happen only in CollectWorker."""
        index = self.current_group_idx if index is None else index
        if not 0 <= index < len(self.groups):
            return None
        return build_collect_group(self.groups[index])

    def get_task_info(self):
        config = self.build_run_config()
        return collect_group_dict(config) if config else None

    def _other_tasks_running(self):
        if QApplication.activeModalWidget() is not None:
            return True
        window = self.window()
        if getattr(window, "_run_confirmation_active", False):
            # A run change summary is being analyzed or reviewed for another feature.
            return True
        for name in (
            "task_tab",
            "sync_tab",
            "eml_tab",
            "pdf_tab",
            "ocr_tab",
            "bypass_tab",
        ):
            tab = getattr(window, name, None)
            if tab and (
                getattr(tab, "is_running", False)
                or getattr(tab, "is_converting", False)
                or getattr(tab, "is_preflighting", False)
            ):
                return True
        return False

    def start_recovery(self):
        """Hold all execution gates until the recovery dialog's worker has stopped."""
        if self.is_busy or self._ui_locked or self._other_tasks_running():
            return False
        with self._interaction_guard():
            dialog = CollectRecoveryDialog(self.state_path, self.language, self)
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                self._status_key = "collect_recovery_done"
                self.status_label.setText(self._msg(self._status_key))
                self.status_label.setToolTip(str(dialog.backup_path))
            dialog.deleteLater()
        return result == QDialog.DialogCode.Accepted

    def start_dry_run(self, _checked=False):
        return self._start(dry_run=True)

    def start_execution(self, _checked=False):
        if (
            self.is_busy
            or self._ui_locked
            or self.current_group_idx < 0
            or self._other_tasks_running()
        ):
            return False
        with self._interaction_guard():
            reply = QMessageBox.question(
                self,
                self._msg("tab_collect_sync"),
                self._msg("collect_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        return self._start()

    def _start(self, dry_run=False, index=None, scheduled=False, now=None):
        """Reserve single execution before constructing a worker, with persisted history."""
        if (
            self.is_busy
            or self._ui_locked
            or self._invalid_saved
            or self._other_tasks_running()
        ):
            return False
        if not scheduled:
            self._save_editor()
        if self._save_failed:
            return False
        index = self.current_group_idx if index is None else index
        if not 0 <= index < len(self.groups):
            return False
        group = self.groups[index]
        now = now or local_now()
        timestamp = now.isoformat(timespec="seconds")
        previous_history = {
            key: group[key]
            for key in (
                "schedule_last_started_at",
                "schedule_last_finished_at",
                "schedule_last_result",
                "schedule_last_failure_reason",
            )
            if key in group
        }
        if scheduled:
            group.update(
                schedule_last_started_at=timestamp,
                schedule_last_finished_at="",
                schedule_last_failure_reason="",
                schedule_last_result="running",
            )
            if not self.save_data():
                for key in (
                    "schedule_last_started_at",
                    "schedule_last_finished_at",
                    "schedule_last_result",
                    "schedule_last_failure_reason",
                ):
                    group.pop(key, None)
                group.update(previous_history)
                return False
        self._result_group_id = group["id"]
        self._result_group_name = group["name"]
        self._scheduled = scheduled
        self._clear_results()
        config = self.build_run_config(index)
        report_path = (
            self.state_path.parent / "collect_sync_reports" / f"{group['id']}.json"
        )
        worker = CollectWorker(
            (config,),
            self.state_path,
            report_path,
            dry_run,
            self,
            configured_groups=tuple(
                build_collect_group(value) for value in self.groups
            ),
            language=self.language,
            journal_dir=getattr(self.config_manager, "app_dir", None),
        )
        self.worker = worker
        self.is_running = True
        self._status_key = "collect_working"
        self.status_label.setText(self._msg(self._status_key))
        self.progress_bar.setRange(0, 0)
        self._refresh_enabled()
        window = self.window()
        if hasattr(window, "set_all_tabs_locked"):
            window.set_all_tabs_locked(True)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(lambda: self._worker_finished(worker))
        try:
            worker.start()
        except Exception:
            logger.exception("Cannot start collect worker")
            worker.error_code = "collect_error_io"
            worker.start_failed = True
            if scheduled:
                for key in (
                    "schedule_last_started_at",
                    "schedule_last_finished_at",
                    "schedule_last_result",
                    "schedule_last_failure_reason",
                ):
                    group.pop(key, None)
                group.update(previous_history)
                # A native start failure is an attempt, not a new completed run.
                self._scheduled = False
                if not self.save_data():
                    worker.error_code = "collect_save_error"
            self._worker_finished(worker)
            return False
        return True

    def _on_progress(self, current, total, message):
        self.progress_bar.setRange(0, total if total else 0)
        self.progress_bar.setValue(current)
        # Paths/group names are user data, not interpreted as rich text.
        self.status_label.setText(message)

    def _worker_finished(self, worker):
        """Only release UI after the native thread is finished, never on an early signal."""
        if self.worker is not worker or worker.isRunning():
            return
        report = worker.report
        error = worker.error_code
        self.is_running = False
        self._last_report = report
        self._result_page = 0
        self._report_dry_run = worker.dry_run
        self._status_key = error or (
            "collect_cancelled"
            if report.cancelled
            else "collect_finished_errors"
            if report.count(ACTION_ERROR)
            else "collect_preview_note"
            if worker.dry_run
            else "collect_done"
        )
        if not worker.dry_run and not getattr(worker, "start_failed", False):
            group = next(
                (g for g in self.groups if g["id"] == self._result_group_id), None
            )
            if group:
                counts = {kind: report.count(kind) for kind in KINDS}
                finished_at = local_now().isoformat(timespec="seconds")
                if not worker.blocked_before_run:
                    group["last_result_counts"] = counts
                    group["last_finished_at"] = finished_at
                if self._scheduled:
                    failed = bool(
                        error or report.cancelled or report.count(ACTION_ERROR)
                    )
                    group.update(
                        schedule_last_finished_at=finished_at,
                        schedule_last_result="failure" if failed else "success",
                        schedule_last_failure_reason=self._status_key if failed else "",
                    )
                    group[
                        "schedule_last_failure_at"
                        if failed
                        else "schedule_last_success_at"
                    ] = finished_at
                self.save_data()
        logger.info(
            "Collect result group=%s scheduled=%s cancelled=%s error=%s counts=%s",
            self._result_group_id,
            self._scheduled,
            report.cancelled,
            error,
            {kind: report.count(kind) for kind in KINDS},
        )
        self.worker = None
        worker.deleteLater()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if not report.cancelled and not error else 0)
        window = self.window()
        if hasattr(window, "set_all_tabs_locked"):
            window.set_all_tabs_locked(False)
        self._refresh_enabled()
        self.refresh_language()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self._status_key = "collect_stopping"
            self.status_label.setText(self._msg(self._status_key))
            self.stop_button.setEnabled(False)

    def stop_all(self):
        """Request cancellation and refuse shutdown if an OS operation is still blocked."""
        if self._confirmation_active:
            return False
        if self.worker:
            worker = self.worker
            self.stop()
            if not worker.wait(1500):
                return False
            self._worker_finished(worker)
        return True

    def set_ui_locked(self, locked):
        self._ui_locked = bool(locked)
        self._refresh_enabled()

    def _refresh_enabled(self):
        editable = not self.is_busy and not self._ui_locked and not self._invalid_saved
        has_group = self.current_group_idx >= 0
        self.editor.setEnabled(editable)
        for widget in (
            self.source_list,
            self.keywords_input,
            self.target_input,
            self.subfolders_check,
            self.target_button,
        ):
            widget.setEnabled(has_group)
        for key in (
            "collect_rename",
            "collect_delete",
            "collect_add_source",
            "collect_remove_source",
        ):
            self._buttons[key].setEnabled(has_group)
        self.preview_button.setEnabled(editable and has_group)
        self.run_button.setEnabled(editable and has_group)
        self.recovery_button.setEnabled(not self.is_busy and not self._ui_locked)
        self.stop_button.setEnabled(
            self.is_busy
            and self.worker is not None
            and not self.worker.isInterruptionRequested()
        )

    def check_scheduled_run(self, now=None):
        """Deprecated compatibility entry point. Only TaskTab may schedule work."""
        return False

    def refresh_schedule_summary(self):
        """Legacy callers may refresh; the per-group scheduler has been retired."""

    def _action_message(self, action):
        if action.message_code == "newer" or action.kind == ACTION_TARGET_NEWER:
            return self._msg("collect_newer_message")
        if action.kind == ACTION_ERROR:
            return self._msg("collect_error_" + (action.message_code or "io"))
        return action.message

    def _change_result_page(self, delta):
        """Page through all results without allocating an unbounded Qt table."""
        if self._last_report is not None:
            self._result_page += delta
            self._render_report()

    def _clear_results(self):
        """Clear the result table and its navigation together at every invalidation."""
        self._last_report = None
        self._result_page = 0
        self._report_dry_run = False
        self.table.setRowCount(0)
        self.summary_label.clear()
        self.result_pager.hide()
        self.previous_page_button.setEnabled(False)
        self.next_page_button.setEnabled(False)
        self.page_label.clear()

    def _render_report(self):
        report = self._last_report
        if report is None:
            return
        total = len(report.actions)
        pages = max(1, (total + self.RESULT_ROW_LIMIT - 1) // self.RESULT_ROW_LIMIT)
        self._result_page = min(max(0, self._result_page), pages - 1)
        start = self._result_page * self.RESULT_ROW_LIMIT
        end = min(total, start + self.RESULT_ROW_LIMIT)
        self.table.setRowCount(end - start)
        for row, action in enumerate(report.actions[start:end]):
            for column, text in enumerate(
                (
                    self._msg("collect_" + action.kind),
                    action.source,
                    action.target_name,
                    action.archived_name,
                    self._action_message(action),
                )
            ):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
        text = self._msg(
            "collect_summary",
            copy=report.count(ACTION_COPY),
            replace=report.count(ACTION_REPLACE),
            unchanged=report.count(ACTION_UNCHANGED),
            newer=report.count(ACTION_TARGET_NEWER),
            error=report.count(ACTION_ERROR),
        )
        text = (
            self._msg("collect_results_group", name=self._result_group_name)
            + "\n"
            + text
        )
        self.result_pager.setVisible(pages > 1)
        self.previous_page_button.setEnabled(self._result_page > 0)
        self.next_page_button.setEnabled(self._result_page + 1 < pages)
        self.previous_page_button.setText(self._msg("collect_previous_page"))
        self.next_page_button.setText(self._msg("collect_next_page"))
        self.page_label.setText(
            self._msg("collect_page", current=self._result_page + 1, pages=pages)
        )
        if pages > 1:
            text += "\n" + self._msg(
                "collect_results_limit", first=start + 1, last=end, total=total
            )
        if self._report_dry_run:
            text += "\n" + self._msg("collect_preview_report_note")
        self.summary_label.setText(text)

    def refresh_language(self):
        self.editor.setTitle(self._msg("collect_groups"))
        for key, label in self._labels.items():
            label.setText(self._msg(key))
        for key, button in self._buttons.items():
            button.setText(self._msg(key))
        for widget, key in (
            (self.subfolders_check, "collect_subfolders"),
            (self.target_button, "collect_browse"),
            (self.preview_button, "collect_preview"),
            (self.run_button, "collect_run"),
            (self.stop_button, "collect_stop"),
            (self.recovery_button, "collect_recovery_title"),
            (self.note, "collect_note"),
        ):
            widget.setText(self._msg(key))
        self.keywords_input.setPlaceholderText(self._msg("collect_keyword_hint"))
        self.table.setHorizontalHeaderLabels(
            [
                self._msg(key)
                for key in (
                    "collect_kind",
                    "collect_source",
                    "collect_target_name",
                    "collect_archive_name",
                    "collect_message",
                )
            ]
        )
        if not self.is_running:
            self.status_label.setText(self._msg(self._status_key))
        self._render_report()
        self.refresh_schedule_summary()
