import os
import time
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QProgressBar, QTextEdit, QTableWidget, QTableWidgetItem, 
    QHeaderView, QMessageBox, QCheckBox, QFrame, QTimeEdit
)
from PyQt6.QtCore import Qt, QTime, QTimer
from PyQt6.QtGui import QFont, QColor

# Core Modules
from src.core.email_sender import send_email
from src.core.diagnostics import DiagnosticItem, DiagnosticStatus
from src.core.preflight import check_run_plan
from src.core.schedule import evaluate_daily_schedule, parse_timestamp
from src.core.task_contracts import BypassRunConfig, RunPlan, SourceDisposition, StepStatus, TaskStep, TaskValidationError
from src.core.task_history import merge_run_report_history, normalize_step_history
from src.ui.i18n import get_app_language, tr
from src.ui.diagnostics_dialog import DiagnosticsDialog
from src.ui.task_worker import TaskWorker
from src.utils.logger import get_logger

logger = get_logger()

class TaskTab(QWidget):
    SCHEDULE_RETRY_MINUTES = 10
    SCHEDULE_MAX_START_ATTEMPTS = 3
    COL_RUN = 0
    COL_FEATURE = 1
    COL_READINESS = 2
    COL_STATUS = 3
    COL_LAST_RESULT = 4

    STEP_ORDER = (
        TaskStep.SYNC,
        TaskStep.EML,
        TaskStep.PDF,
        TaskStep.OCR,
        TaskStep.BYPASS,
    )

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.worker = None
        self.is_running = False
        self.is_scheduled_run = False
        self.start_failure_reason = ""
        self.init_ui()

        self.schedule_timer = QTimer(self)
        self.schedule_timer.setInterval(30_000)
        self.schedule_timer.timeout.connect(self._on_schedule_tick)
        self.schedule_timer.start()
        QTimer.singleShot(0, self._on_schedule_tick)
        QTimer.singleShot(0, self.refresh_readiness)
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 1. 상단 통제 패널 (Header & Controls)
        ctrl_frame = QFrame()
        ctrl_frame.setObjectName("controlFrame")
        ctrl_frame.setStyleSheet("""
            QFrame#controlFrame {
                background-color: #1e1e1e;
                border-radius: 8px;
                border: 1px solid #3e3e3e;
            }
        """)
        ctrl_layout = QHBoxLayout()
        ctrl_frame.setLayout(ctrl_layout)
        
        self.title_label = QLabel()
        self.title_label.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #e2e8f0;")
        ctrl_layout.addWidget(self.title_label)
        ctrl_layout.addStretch()

        self.check_schedule = QCheckBox()
        self.check_schedule.setChecked(
            bool(self.config_manager.get("task_schedule_enabled", False))
        )
        ctrl_layout.addWidget(self.check_schedule)

        self.schedule_time_edit = QTimeEdit()
        self.schedule_time_edit.setDisplayFormat("HH:mm")
        configured_time = QTime.fromString(
            str(self.config_manager.get("task_schedule_time", "18:00")),
            "HH:mm"
        )
        self.schedule_time_edit.setTime(
            configured_time if configured_time.isValid() else QTime(18, 0)
        )
        self.schedule_time_edit.setEnabled(self.check_schedule.isChecked())
        ctrl_layout.addWidget(self.schedule_time_edit)
        
        # 메일 자동 발송 체크박스
        self.check_auto_email = QCheckBox()
        self.check_auto_email.setChecked(
            bool(self.config_manager.get("task_auto_email", True))
        )
        self.check_auto_email.setStyleSheet("font-size: 11px;")
        ctrl_layout.addWidget(self.check_auto_email)

        # 시작 / 중지 버튼
        self.start_btn = QPushButton()
        self.start_btn.setMinimumHeight(35)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ece70;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 0 15px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
            QPushButton:disabled {
                background-color: #2d2d2d;
                color: #64748b;
                border: 1px solid #3e3e3e;
            }
        """)
        self.start_btn.clicked.connect(self.start_all_tasks)
        ctrl_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton()
        self.stop_btn.setMinimumHeight(35)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 0 15px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #2d2d2d;
                color: #64748b;
                border: 1px solid #3e3e3e;
            }
        """)
        self.stop_btn.clicked.connect(self.stop_tasks)
        ctrl_layout.addWidget(self.stop_btn)
        
        layout.addWidget(ctrl_frame)

        hint_layout = QHBoxLayout()
        self.selection_hint = QLabel()
        self.selection_hint.setWordWrap(True)
        self.selection_hint.setStyleSheet("color: #94a3b8; padding: 2px 4px;")
        hint_layout.addWidget(self.selection_hint, 1)
        self.readiness_btn = QPushButton()
        self.readiness_btn.setMinimumHeight(30)
        self.readiness_btn.clicked.connect(self.refresh_readiness)
        hint_layout.addWidget(self.readiness_btn)
        self.diagnostics_btn = QPushButton()
        self.diagnostics_btn.setMinimumHeight(30)
        self.diagnostics_btn.clicked.connect(self.open_diagnostics)
        hint_layout.addWidget(self.diagnostics_btn)
        layout.addLayout(hint_layout)

        self.schedule_status_label = QLabel()
        self.schedule_status_label.setWordWrap(True)
        self.schedule_status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.schedule_status_label.setStyleSheet(
            "color: #7dd3fc; background-color: #17212b; border: 1px solid #334155; "
            "border-radius: 5px; padding: 6px 8px;"
        )
        layout.addWidget(self.schedule_status_label)

        self.check_allow_source_backup = QCheckBox()
        self.check_allow_source_backup.setChecked(
            bool(self.config_manager.get("task_schedule_allow_source_backup", False))
        )
        self.check_allow_source_backup.setEnabled(self.check_schedule.isChecked())
        self.check_allow_source_backup.setStyleSheet(
            "color: #fbbf24; background-color: #2b2113; border: 1px solid #713f12; "
            "border-radius: 5px; padding: 6px 8px;"
        )
        layout.addWidget(self.check_allow_source_backup)

        self.check_schedule.toggled.connect(self._on_schedule_toggled)
        self.schedule_time_edit.timeChanged.connect(self.save_automation_settings)
        self.check_auto_email.toggled.connect(self.save_automation_settings)
        self.check_allow_source_backup.toggled.connect(self.save_automation_settings)
        
        # 2. 중간 상태 그리드 테이블 (Tab Summary Status)
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(5)
        self.status_table.setRowCount(5)
        self.status_table.setHorizontalHeaderLabels(["", "", "", "", ""])
        self.status_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.status_table.horizontalHeader().setSectionResizeMode(self.COL_RUN, QHeaderView.ResizeMode.ResizeToContents)
        self.status_table.horizontalHeader().setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.status_table.setMinimumHeight(205)
        self.status_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                color: #e2e8f0;
                gridline-color: #3e3e3e;
                border: 1px solid #3e3e3e;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #e2e8f0;
                padding: 5px;
                font-weight: bold;
                border: 1px solid #3e3e3e;
            }
        """)
        
        enabled_values = self.config_manager.get("task_enabled_steps", [TaskStep.SYNC.value])
        if not isinstance(enabled_values, list):
            enabled_values = [TaskStep.SYNC.value]
        enabled_steps = {str(value) for value in enabled_values}
        self.step_keys = {}
        self.step_checks = {}
        for row_idx, step in enumerate(self.STEP_ORDER):
            key = step.value
            self.step_keys[key] = row_idx

            run_check = QCheckBox()
            run_check.setChecked(key in enabled_steps)
            run_check.setToolTip(key)
            run_check.toggled.connect(self.save_enabled_steps)
            check_holder = QWidget()
            check_layout = QHBoxLayout(check_holder)
            check_layout.setContentsMargins(0, 0, 0, 0)
            check_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            check_layout.addWidget(run_check)
            self.status_table.setCellWidget(row_idx, self.COL_RUN, check_holder)
            self.step_checks[step] = run_check
            
            # 단계명
            name_item = QTableWidgetItem()
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name_item.setFont(QFont("Malgun Gothic", 9, QFont.Weight.Bold))
            self.status_table.setItem(row_idx, self.COL_FEATURE, name_item)

            readiness_item = QTableWidgetItem()
            readiness_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            readiness_item.setForeground(QColor("#94a3b8"))
            self.status_table.setItem(row_idx, self.COL_READINESS, readiness_item)
            
            # 상태
            status_item = QTableWidgetItem()
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor("#94a3b8"))
            self.status_table.setItem(row_idx, self.COL_STATUS, status_item)

            history_item = QTableWidgetItem()
            history_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            history_item.setForeground(QColor("#cbd5e1"))
            self.status_table.setItem(row_idx, self.COL_LAST_RESULT, history_item)
            
        layout.addWidget(self.status_table)
        
        # 3. 전체 진행률 프로그레스 바 영역
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(5)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3e3e3e;
                border-radius: 6px;
                text-align: center;
                background-color: #1e1e1e;
                font-weight: bold;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #0e639c;
                border-radius: 5px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        # 미세 진행 레이블
        self.detail_label = QLabel()
        self.detail_label.setStyleSheet("font-size: 11px; color: #a0a0a0;")
        progress_layout.addWidget(self.detail_label)
        
        layout.addLayout(progress_layout)
        
        # 4. 하단 상세 로그창
        self.log_label = QLabel()
        self.log_label.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        layout.addWidget(self.log_label)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        # 고정폭 폰트 적용
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #2f3640;
                color: #f5f6fa;
                border: 1px solid #1e272e;
                border-radius: 6px;
            }
        """)
        layout.addWidget(self.log_area)
        self.refresh_history_display()
        self._update_backup_consent_visibility()
        self.refresh_language()

    @property
    def language(self):
        return get_app_language(self.config_manager)

    def step_label(self, step):
        return tr(f"task_step_{step.value}", self.language)

    def _text(self, english, korean, polish):
        return {"ko": korean, "pl": polish}.get(self.language, english)

    def _runtime_error_text(self, value):
        text = str(value)
        if self.language == "ko":
            return text
        replacements = {
            "필수 이메일 발송 설정 항목이 누락되었습니다": "Required email settings are missing",
            "수신자 이메일 주소가 비어있습니다": "The recipient email address is empty",
            "SMTP 인증에 실패했습니다": "SMTP authentication failed",
            "이메일 주소 또는 비밀번호(앱 비밀번호)를 확인하세요": "Check the email address and app password",
            "이메일 전송 중 에러가 발생했습니다": "An error occurred while sending email",
        }
        for korean, english in replacements.items():
            text = text.replace(korean, english)
        return text

    def selected_steps(self):
        return [step for step in self.STEP_ORDER if self.step_checks[step].isChecked()]

    def save_enabled_steps(self, _checked=False):
        previous = self.config_manager.get("task_enabled_steps", [TaskStep.SYNC.value])
        previous_steps = {str(value) for value in previous} if isinstance(previous, list) else {TaskStep.SYNC.value}
        selected_values = [step.value for step in self.selected_steps()]
        self.config_manager.set("task_enabled_steps", selected_values)
        if TaskStep.BYPASS.value in selected_values and TaskStep.BYPASS.value not in previous_steps:
            self.check_allow_source_backup.setChecked(False)
        if not self.is_running:
            for step in self.STEP_ORDER:
                row = self.step_keys[step.value]
                status_key = "pending" if self.step_checks[step].isChecked() else "skipped"
                self._set_status_item(self.status_table.item(row, self.COL_STATUS), status_key)
                readiness_key = "not_checked" if self.step_checks[step].isChecked() else "not_selected"
                self._set_readiness_item(step, readiness_key)
        self._update_backup_consent_visibility()

    def _update_backup_consent_visibility(self):
        bypass_check = getattr(self, "step_checks", {}).get(TaskStep.BYPASS)
        bypass_selected = bool(bypass_check and bypass_check.isChecked())
        backup_enabled = (
            self.config_manager.get("bypass_source_disposition", SourceDisposition.KEEP.value)
            == SourceDisposition.BACKUP.value
        )
        relevant = self.check_schedule.isChecked() and bypass_selected and backup_enabled
        self.check_allow_source_backup.setVisible(relevant)
        self.check_allow_source_backup.setEnabled(relevant and not self.is_running)

    def showEvent(self, event):
        super().showEvent(event)
        self._update_backup_consent_visibility()

    def refresh_language(self):
        language = self.language
        self.title_label.setText(tr("task_title", language))
        self.check_schedule.setText(tr("task_schedule", language))
        self.check_auto_email.setText(tr("task_auto_email", language))
        self.check_allow_source_backup.setText(tr("task_schedule_allow_source_backup", language))
        self.check_allow_source_backup.setToolTip(tr("task_schedule_allow_source_backup_help", language))
        self.start_btn.setText(tr("task_start", language))
        self.stop_btn.setText(tr("task_stop", language))
        self.readiness_btn.setText(tr("task_check_readiness", language))
        self.diagnostics_btn.setText(tr("diagnostics_open", language))
        self.selection_hint.setText(tr("task_selection_hint", language))
        self.status_table.setHorizontalHeaderLabels([
            tr("task_run_header", language),
            tr("task_feature_header", language),
            tr("task_readiness_header", language),
            tr("task_status_header", language),
            tr("task_last_result_header", language),
        ])
        for step in self.STEP_ORDER:
            row = self.step_keys[step.value]
            self.status_table.item(row, self.COL_FEATURE).setText(self.step_label(step))
            readiness_item = self.status_table.item(row, self.COL_READINESS)
            readiness_key = readiness_item.data(Qt.ItemDataRole.UserRole) or (
                "not_checked" if self.step_checks[step].isChecked() else "not_selected"
            )
            readiness_detail = readiness_item.data(Qt.ItemDataRole.UserRole.value + 1) or ""
            self._set_readiness_item(step, readiness_key, readiness_detail)
            status_item = self.status_table.item(row, self.COL_STATUS)
            status_key = status_item.data(Qt.ItemDataRole.UserRole)
            if not status_key:
                status_key = "pending" if self.step_checks[step].isChecked() else "skipped"
            self._set_status_item(status_item, status_key)
        self.progress_bar.setFormat(tr("task_progress_format", language))
        self.detail_label.setText(tr("task_waiting", language))
        self.log_label.setText(tr("task_log_title", language))
        self.refresh_history_display()
        self.refresh_schedule_summary()

    def _set_status_item(self, item, status_key):
        item.setData(Qt.ItemDataRole.UserRole, status_key)
        item.setText(tr(f"task_status_{status_key}", self.language))

    def _set_readiness_item(self, step, readiness_key, detail=""):
        row = self.step_keys[step.value]
        item = self.status_table.item(row, self.COL_READINESS)
        item.setData(Qt.ItemDataRole.UserRole, readiness_key)
        item.setData(Qt.ItemDataRole.UserRole.value + 1, detail)
        item.setText(tr(f"task_readiness_{readiness_key}", self.language))
        item.setToolTip(detail)
        colors = {
            "ready": "#4ade80",
            "warning": "#fbbf24",
            "blocked": "#f87171",
            "not_checked": "#94a3b8",
            "not_selected": "#64748b",
        }
        item.setForeground(QColor(colors.get(readiness_key, "#94a3b8")))

    def refresh_history_display(self):
        history = normalize_step_history(self.config_manager.get("task_step_last_results", {}))
        for step in self.STEP_ORDER:
            row = self.step_keys[step.value]
            item = self.status_table.item(row, self.COL_LAST_RESULT)
            entry = history.get(step.value)
            if not entry:
                item.setText(tr("task_history_none", self.language))
                item.setToolTip("")
                item.setForeground(QColor("#64748b"))
                continue
            try:
                timestamp = datetime.fromisoformat(entry["timestamp"]).strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                timestamp = entry["timestamp"]
            status_text = tr(f"task_status_{entry['status']}", self.language)
            counts = ""
            if entry["total_count"]:
                counts = f" · {entry['success_count']}/{entry['total_count']}"
            item.setText(f"{status_text}{counts} · {timestamp}")
            item.setToolTip(entry["detail"])
            item.setForeground(QColor("#4ade80" if entry["status"] == "completed" else "#fbbf24" if entry["status"] == "cancelled" else "#f87171"))

    def capture_run_report(self, report):
        history = merge_run_report_history(
            self.config_manager.get("task_step_last_results", {}),
            report,
        )
        self._update_config({"task_step_last_results": history})
        self.refresh_history_display()

    def refresh_readiness(self):
        if self.is_running:
            return
        self._update_backup_consent_visibility()
        main_win = self.window()
        tabs = {
            TaskStep.SYNC: getattr(main_win, "sync_tab", None),
            TaskStep.EML: getattr(main_win, "eml_tab", None),
            TaskStep.PDF: getattr(main_win, "pdf_tab", None),
            TaskStep.OCR: getattr(main_win, "ocr_tab", None),
            TaskStep.BYPASS: getattr(main_win, "bypass_tab", None),
        }
        configs = {}
        for step in self.STEP_ORDER:
            if not self.step_checks[step].isChecked():
                self._set_readiness_item(step, "not_selected")
                continue
            tab_obj = tabs.get(step)
            if tab_obj is None or not hasattr(tab_obj, "build_run_config"):
                self._set_readiness_item(step, "blocked", tr("task_readiness_tab_unavailable", self.language))
                continue
            try:
                config = tab_obj.build_run_config()
                if config is None:
                    raise TaskValidationError(tr("task_no_config", self.language))
                configs[step] = config
                self._set_readiness_item(step, "ready")
            except TaskValidationError as exc:
                detail = tr(exc.message_key, self.language, **exc.values) if exc.message_key else exc.user_message
                self._set_readiness_item(step, "blocked", detail)
            except Exception as exc:
                self._set_readiness_item(step, "blocked", str(exc))

        if configs:
            report = check_run_plan(
                RunPlan(configs=configs),
                self.config_manager,
                auto_email=False,
                check_office=False,
            )
            for step in configs:
                blockers = [issue for issue in report.blockers if issue.step == step]
                warnings = [issue for issue in report.warnings if issue.step == step]
                if blockers:
                    detail = "\n".join(filter(None, [issue.message + (f"\n{issue.detail}" if issue.detail else "") for issue in blockers]))
                    self._set_readiness_item(step, "blocked", detail)
                elif warnings:
                    detail = "\n".join(filter(None, [issue.message + (f"\n{issue.detail}" if issue.detail else "") for issue in warnings]))
                    self._set_readiness_item(step, "warning", detail)

        bypass_config = configs.get(TaskStep.BYPASS)
        if (
            self.check_schedule.isChecked()
            and isinstance(bypass_config, BypassRunConfig)
            and bypass_config.source_disposition == SourceDisposition.BACKUP
            and not self.check_allow_source_backup.isChecked()
        ):
            self._set_readiness_item(
                TaskStep.BYPASS,
                "blocked",
                tr("task_schedule_backup_consent_required", self.language),
            )

    def open_diagnostics(self):
        selected_steps = self.selected_steps()
        if not selected_steps:
            QMessageBox.warning(
                self,
                tr("task_no_selection_title", self.language),
                tr("task_no_selection_body", self.language),
            )
            return

        main_win = self.window()
        tabs = {
            TaskStep.SYNC: getattr(main_win, "sync_tab", None),
            TaskStep.EML: getattr(main_win, "eml_tab", None),
            TaskStep.PDF: getattr(main_win, "pdf_tab", None),
            TaskStep.OCR: getattr(main_win, "ocr_tab", None),
            TaskStep.BYPASS: getattr(main_win, "bypass_tab", None),
        }
        configs = {}
        validation_items = []
        for step in selected_steps:
            tab_obj = tabs.get(step)
            try:
                if tab_obj is None or not hasattr(tab_obj, "build_run_config"):
                    raise TaskValidationError(tr("task_readiness_tab_unavailable", self.language))
                config = tab_obj.build_run_config()
                if config is None:
                    raise TaskValidationError(tr("task_no_config", self.language))
                configs[step] = config
            except TaskValidationError as exc:
                detail = tr(exc.message_key, self.language, **exc.values) if exc.message_key else exc.user_message
                validation_items.append(DiagnosticItem(
                    f"{step.value}_config",
                    tr("diagnostics_feature_config", self.language, feature=self.step_label(step)),
                    DiagnosticStatus.FAIL,
                    detail,
                    step.value,
                ))
            except Exception as exc:
                validation_items.append(DiagnosticItem(
                    f"{step.value}_config",
                    tr("diagnostics_feature_config", self.language, feature=self.step_label(step)),
                    DiagnosticStatus.FAIL,
                    str(exc),
                    step.value,
                ))

        self.diagnostics_dialog = DiagnosticsDialog(
            self.config_manager,
            RunPlan(configs=configs),
            validation_items,
            self._navigate_diagnostic_target,
            auto_email=self.check_auto_email.isChecked(),
            parent=self,
        )
        self.diagnostics_dialog.exec()
        self.refresh_readiness()

    def _navigate_diagnostic_target(self, target):
        main_win = self.window()
        if target == "settings" and hasattr(main_win, "open_settings"):
            main_win.open_settings()
            return
        if target == "tasks":
            if hasattr(main_win, "tab_widget"):
                main_win.tab_widget.setCurrentWidget(self)
            return
        try:
            step = TaskStep(target)
        except ValueError:
            return
        widgets = {
            TaskStep.SYNC: getattr(main_win, "sync_tab", None),
            TaskStep.EML: getattr(main_win, "eml_tab", None),
            TaskStep.PDF: getattr(main_win, "pdf_tab", None),
            TaskStep.OCR: getattr(main_win, "ocr_tab", None),
            TaskStep.BYPASS: getattr(main_win, "bypass_tab", None),
        }
        widget = widgets.get(step)
        if widget is not None and hasattr(main_win, "tab_widget"):
            main_win.tab_widget.setCurrentWidget(widget)
        
    def log(self, message):
        self.log_area.append(message)
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _start_rejected(self, reason):
        self.start_failure_reason = str(reason or "").strip()
        return False

    def _update_config(self, values):
        update = getattr(self.config_manager, "update", None)
        if callable(update):
            return update(values)
        result = True
        for key, value in values.items():
            result = bool(self.config_manager.set(key, value)) and result
        return result

    def _on_schedule_tick(self):
        self.check_scheduled_run()
        self.refresh_schedule_summary()

    def _schedule_decision(self, now):
        return evaluate_daily_schedule(
            now=now,
            schedule_time=self.schedule_time_edit.time().toString("HH:mm"),
            last_started_at=self.config_manager.get("task_schedule_last_started_at", ""),
            legacy_last_run_date=self.config_manager.get("task_schedule_last_run_date", ""),
            attempt_date=self.config_manager.get("task_schedule_attempt_date", ""),
            attempt_count=self.config_manager.get("task_schedule_attempt_count", 0),
            last_attempt_at=self.config_manager.get("task_schedule_last_attempt_at", ""),
            retry_minutes=self.SCHEDULE_RETRY_MINUTES,
            max_start_attempts=self.SCHEDULE_MAX_START_ATTEMPTS,
        )

    def _last_schedule_outcome_text(self):
        success_at = parse_timestamp(self.config_manager.get("task_schedule_last_success_at", ""))
        failure_at = parse_timestamp(self.config_manager.get("task_schedule_last_failure_at", ""))
        if success_at and (not failure_at or success_at >= failure_at):
            return tr(
                "task_schedule_last_success",
                self.language,
                timestamp=success_at.strftime("%Y-%m-%d %H:%M"),
            )
        if failure_at:
            reason = str(self.config_manager.get("task_schedule_last_failure_reason", "")).strip()
            if len(reason) > 140:
                reason = reason[:137] + "..."
            return tr(
                "task_schedule_last_failure",
                self.language,
                timestamp=failure_at.strftime("%Y-%m-%d %H:%M"),
                reason=reason or tr("task_schedule_unknown_failure", self.language),
            )
        return tr("task_schedule_no_history", self.language)

    def refresh_schedule_summary(self, now=None):
        now = now or datetime.now()
        if not self.check_schedule.isChecked():
            primary = tr("task_schedule_off", self.language)
        elif self.is_running and self.is_scheduled_run:
            primary = tr("task_schedule_in_progress", self.language)
        else:
            decision = self._schedule_decision(now)
            timestamp = decision.next_at.strftime("%Y-%m-%d %H:%M")
            if decision.status == "retry_wait":
                primary = tr(
                    "task_schedule_next_retry",
                    self.language,
                    timestamp=timestamp,
                    attempts=decision.attempt_count,
                    maximum=self.SCHEDULE_MAX_START_ATTEMPTS,
                )
            elif decision.status == "attempts_exhausted":
                primary = tr(
                    "task_schedule_attempts_exhausted",
                    self.language,
                    attempts=decision.attempt_count,
                    timestamp=timestamp,
                )
            elif decision.should_start:
                primary = tr("task_schedule_due_now", self.language)
            else:
                primary = tr("task_schedule_next_run", self.language, timestamp=timestamp)

        lines = [primary, self._last_schedule_outcome_text()]
        if self.check_schedule.isChecked():
            lines.append(tr("task_schedule_app_note", self.language))
        self.schedule_status_label.setText("\n".join(lines))

    def _on_schedule_toggled(self, enabled):
        self.schedule_time_edit.setEnabled(enabled and not self.is_running)
        was_enabled = bool(self.config_manager.get("task_schedule_enabled", False))
        if enabled and not was_enabled:
            # A newly enabled unattended schedule requires fresh consent for
            # moving Convert Files sources, even if an old consent was stored.
            self.check_allow_source_backup.setChecked(False)
        self.save_automation_settings()
        self._update_backup_consent_visibility()
        self.refresh_readiness()

    def save_automation_settings(self, *_args):
        """예약 실행과 이메일 자동 발송 옵션을 즉시 저장합니다."""
        enabled = self.check_schedule.isChecked()
        schedule_time = self.schedule_time_edit.time().toString("HH:mm")
        changed = (
            bool(self.config_manager.get("task_schedule_enabled", False)) != enabled
            or str(self.config_manager.get("task_schedule_time", "18:00")) != schedule_time
        )
        values = {
            "task_schedule_enabled": enabled,
            "task_schedule_time": schedule_time,
            "task_auto_email": self.check_auto_email.isChecked(),
            "task_schedule_allow_source_backup": self.check_allow_source_backup.isChecked(),
        }
        if changed:
            values.update({
                "task_schedule_attempt_date": "",
                "task_schedule_attempt_count": 0,
                "task_schedule_last_attempt_at": "",
            })
        self._update_config(values)
        self.save_enabled_steps()
        self.refresh_schedule_summary()

    def check_scheduled_run(self, now=None):
        """Start once per day, retrying only failures that occur before worker start."""
        if not self.check_schedule.isChecked() or self.is_running:
            return False

        now = now or datetime.now()
        decision = self._schedule_decision(now)
        if not decision.should_start:
            return False

        attempt_count = decision.attempt_count + 1
        timestamp = now.isoformat(timespec="seconds")
        self._update_config({
            "task_schedule_attempt_date": now.date().isoformat(),
            "task_schedule_attempt_count": attempt_count,
            "task_schedule_last_attempt_at": timestamp,
        })
        prefix = tr("task_scheduled_prefix", self.language)
        self.log(f"[{prefix}] " + tr(
            "task_scheduled_start",
            self.language,
            timestamp=now.strftime('%Y-%m-%d %H:%M:%S'),
        ))
        started = self.start_all_tasks(scheduled=True)
        if started:
            self._update_config({
                "task_schedule_last_started_at": timestamp,
                # Retained for compatibility with existing configuration files.
                "task_schedule_last_run_date": now.date().isoformat(),
                "task_schedule_last_failure_reason": "",
            })
        else:
            reason = self.start_failure_reason or tr("task_scheduled_skipped", self.language)
            self._update_config({
                "task_schedule_last_failure_at": timestamp,
                "task_schedule_last_failure_reason": reason,
            })
            next_decision = self._schedule_decision(now)
            self.log(f"[{prefix}] {tr('task_scheduled_skipped', self.language)}")
            if next_decision.status == "retry_wait":
                self.log(
                    f"[{prefix}] "
                    + tr(
                        "task_schedule_retry_planned",
                        self.language,
                        timestamp=next_decision.next_at.strftime("%Y-%m-%d %H:%M"),
                        attempts=attempt_count,
                        maximum=self.SCHEDULE_MAX_START_ATTEMPTS,
                    )
                )
            elif next_decision.status == "attempts_exhausted":
                self.log(
                    f"[{prefix}] "
                    + tr(
                        "task_schedule_retry_exhausted_log",
                        self.language,
                        attempts=attempt_count,
                    )
                )
        self.refresh_schedule_summary(now)
        return started

    def start_all_tasks(self, checked=False, scheduled=False):
        """통합 일괄 실행 시작"""
        self.start_failure_reason = ""
        if self.is_running:
            return self._start_rejected(tr("task_schedule_already_running", self.language))
            
        main_win = self.window()
        if not main_win:
            return self._start_rejected(tr("task_schedule_window_unavailable", self.language))

        selected_steps = self.selected_steps()
        if not selected_steps:
            if scheduled:
                self.log(
                    f"[{tr('task_scheduled_prefix', self.language)}] "
                    + tr("task_no_selection_body", self.language)
                )
            else:
                QMessageBox.warning(
                    self,
                    tr("task_no_selection_title", self.language),
                    tr("task_no_selection_body", self.language),
                )
            return self._start_rejected(tr("task_no_selection_body", self.language))
            
        # 1. 5개 탭의 명시적 실행 계약 수집
        configs = {}
        tabs = {
            TaskStep.SYNC: getattr(main_win, "sync_tab", None),
            TaskStep.EML: getattr(main_win, "eml_tab", None),
            TaskStep.PDF: getattr(main_win, "pdf_tab", None),
            TaskStep.OCR: getattr(main_win, "ocr_tab", None),
            TaskStep.BYPASS: getattr(main_win, "bypass_tab", None),
        }
        
        current_step = selected_steps[0]
        try:
            for step in selected_steps:
                current_step = step
                tab_obj = tabs.get(step)
                if tab_obj and hasattr(tab_obj, "build_run_config"):
                    config = tab_obj.build_run_config()
                    if config is None:
                        raise TaskValidationError(
                            tr("task_no_config", self.language),
                            message_key="task_no_config",
                        )
                    configs[step] = config
        except TaskValidationError as val_err:
            feature = self.step_label(current_step)
            problem = (
                tr(val_err.message_key, self.language, **val_err.values)
                if val_err.message_key
                else val_err.user_message
            )
            title = tr("task_validation_title", self.language, feature=feature)
            body = tr(
                "task_validation_body",
                self.language,
                feature=feature,
                problem=problem,
            )
            if scheduled:
                self.log(f"[{tr('task_scheduled_prefix', self.language)}] {title}\n{body}")
            else:
                QMessageBox.warning(self, title, body)
            return self._start_rejected(body)
        except Exception as ex:
            feature = self.step_label(current_step)
            body = tr(
                "task_validation_unexpected",
                self.language,
                feature=feature,
                detail=str(ex),
            )
            if scheduled:
                self.log(f"[{tr('task_scheduled_prefix', self.language)}] {body}")
            else:
                QMessageBox.critical(self, tr("run_error", self.language), body)
            return self._start_rejected(body)

        run_plan = RunPlan(configs=configs)
            
        if run_plan.is_empty():
            if scheduled:
                self.log(self._text("[Scheduled run] No runnable task was found.", "[예약 실행] 실행 가능한 작업이 없습니다.", "[Harmonogram] Nie znaleziono zadania do uruchomienia."))
            else:
                QMessageBox.warning(self, tr("task_no_selection_title", self.language), tr("task_no_selection_body", self.language))
            return self._start_rejected(tr("task_no_selection_body", self.language))

        bypass_config = run_plan.get(TaskStep.BYPASS)
        backup_move_requested = (
            isinstance(bypass_config, BypassRunConfig)
            and bypass_config.source_disposition == SourceDisposition.BACKUP
        )
        if scheduled and backup_move_requested and not self.check_allow_source_backup.isChecked():
            reason = tr("task_schedule_backup_consent_required", self.language)
            self.log(f"[{tr('task_scheduled_prefix', self.language)}] {reason}")
            self._set_readiness_item(TaskStep.BYPASS, "blocked", reason)
            return self._start_rejected(reason)

        # 2. 활성 단계 기준 외부 의존성 사전 점검
        preflight = check_run_plan(
            run_plan,
            self.config_manager,
            auto_email=self.check_auto_email.isChecked(),
            check_office=True,
        )
        if preflight.has_blockers:
            if scheduled:
                self.log(self._text("[Scheduled run] Preflight blocker:\n", "[예약 실행] 사전 점검 차단 항목:\n", "[Harmonogram] Problem kontroli wstępnej:\n") + preflight.format(include_warnings=False))
            else:
                QMessageBox.critical(self, self._text("Preflight check failed", "사전 점검 실패", "Kontrola wstępna nie powiodła się"), preflight.format(include_warnings=False))
            return self._start_rejected(preflight.format(include_warnings=False, language=self.language))

        if preflight.warnings:
            warning_text = preflight.format(include_warnings=True)
            if scheduled:
                self.log(self._text("[Scheduled run] Preflight warning:\n", "[예약 실행] 사전 점검 경고:\n", "[Harmonogram] Ostrzeżenie kontroli wstępnej:\n") + warning_text)
            else:
                reply = QMessageBox.question(
                    self,
                    self._text("Preflight warning", "사전 점검 경고", "Ostrzeżenie kontroli wstępnej"),
                    warning_text + "\n\n" + self._text("Continue anyway?", "계속 진행할까요?", "Czy mimo to kontynuować?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No if backup_move_requested else QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.No:
                    return False
                    
        # UI 및 탭 잠금 처리
        self.is_running = True
        self.is_scheduled_run = scheduled
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.check_auto_email.setEnabled(False)
        self.check_schedule.setEnabled(False)
        self.check_allow_source_backup.setEnabled(False)
        self.schedule_time_edit.setEnabled(False)
        self.readiness_btn.setEnabled(False)
        self.diagnostics_btn.setEnabled(False)
        for check in self.step_checks.values():
            check.setEnabled(False)
        
        # 탭 상태 초기화
        for key in self.step_keys.keys():
            row = self.step_keys[key]
            if TaskStep(key) not in run_plan.configs:
                self._set_status_item(self.status_table.item(row, self.COL_STATUS), "skipped")
                self.status_table.item(row, self.COL_STATUS).setForeground(QColor("#94a3b8"))
            else:
                self._set_status_item(self.status_table.item(row, self.COL_STATUS), "pending")
                self.status_table.item(row, self.COL_STATUS).setForeground(QColor("#38bdf8"))
                
        self.progress_bar.setValue(0)
        self.detail_label.setText(tr("task_status_running", self.language))
        self.log_area.clear()
        
        # 다른 탭들 UI 잠금 걸기
        if hasattr(main_win, "set_all_tabs_locked"):
            main_win.set_all_tabs_locked(True)
            
        # 3. TaskWorker (QThread) 생성 및 실행
        self.worker = TaskWorker(self.config_manager, run_plan)
        self.worker.log_signal.connect(self.log)
        self.worker.step_progress.connect(self.update_step_progress)
        self.worker.total_progress.connect(self.progress_bar.setValue)
        self.worker.status_changed.connect(self.update_status_cell)
        self.worker.report_ready.connect(self.capture_run_report)
        self.worker.finished.connect(self.on_tasks_finished)
        self.worker.start()
        return True

    def stop_tasks(self):
        """실행 중인 통합 태스크 강제 중지"""
        if self.worker and self.worker.isRunning():
            self.stop_btn.setEnabled(False)
            self.detail_label.setText(self._text("Requesting stop...", "작업 중지 요청 중...", "Żądanie zatrzymania..."))
            self.log(self._text(
                "⚠ Stop requested. Please wait for the current file to finish...",
                "⚠ 중지를 요청했습니다. 현재 파일 처리가 끝날 때까지 기다려 주세요...",
                "⚠ Zażądano zatrzymania. Poczekaj na zakończenie bieżącego pliku...",
            ))
            self.worker.stop()
            
    def stop_all(self):
        """MainWindow 종료 시 연동용 강제 정지 및 대기"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()

    def update_step_progress(self, current, total, detail_msg):
        self.detail_label.setText(detail_msg)
        
    def update_status_cell(self, key, status):
        if key in self.step_keys:
            row = self.step_keys[key]
            cell = self.status_table.item(row, self.COL_STATUS)
            status_keys = {
                StepStatus.PENDING.value: "pending",
                StepStatus.RUNNING.value: "running",
                StepStatus.COMPLETED.value: "completed",
                StepStatus.PARTIAL.value: "partial",
                StepStatus.FAILED.value: "failed",
                StepStatus.CANCELLED.value: "cancelled",
                StepStatus.SKIPPED.value: "skipped",
            }
            status_key = status_keys.get(status, "failed")
            self._set_status_item(cell, status_key)
            if status_key == "running":
                cell.setForeground(QColor("#38bdf8"))
            elif status_key == "completed":
                cell.setForeground(QColor("#4ade80"))
            elif status_key in ("partial", "failed"):
                cell.setForeground(QColor("#f87171"))
            elif status_key == "cancelled":
                cell.setForeground(QColor("#fbbf24"))
            else:
                cell.setForeground(QColor("#94a3b8"))

    def on_tasks_finished(self, success, message, report_body):
        scheduled_run = self.is_scheduled_run
        self.is_running = False
        self.is_scheduled_run = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.check_auto_email.setEnabled(True)
        self.check_schedule.setEnabled(True)
        self.check_allow_source_backup.setEnabled(self.check_schedule.isChecked())
        self.schedule_time_edit.setEnabled(self.check_schedule.isChecked())
        self.readiness_btn.setEnabled(True)
        self.diagnostics_btn.setEnabled(True)
        for check in self.step_checks.values():
            check.setEnabled(True)

        if not success and not report_body:
            for step in self.selected_steps():
                row = self.step_keys[step.value]
                status_item = self.status_table.item(row, self.COL_STATUS)
                if status_item.data(Qt.ItemDataRole.UserRole) in {"pending", "running"}:
                    self._set_status_item(status_item, "failed")
                    status_item.setForeground(QColor("#f87171"))
        
        main_win = self.window()
        if hasattr(main_win, "set_all_tabs_locked"):
            main_win.set_all_tabs_locked(False)
            
        self.detail_label.setText(message)

        if scheduled_run:
            finished_at = datetime.now().isoformat(timespec="seconds")
            if success:
                self._update_config({
                    "task_schedule_last_success_at": finished_at,
                    "task_schedule_last_failure_reason": "",
                })
            else:
                self._update_config({
                    "task_schedule_last_failure_at": finished_at,
                    "task_schedule_last_failure_reason": str(message),
                })
            self.refresh_schedule_summary()

        # 성공/부분 실패와 무관하게 실행 결과가 있으면 담당자에게 보고합니다.
        if self.check_auto_email.isChecked() and report_body:
            self.send_report_email(report_body)
        
        if success:
            self.log(f"\n[{self._text('Success', '성공', 'Powodzenie')}] {message}")
            if not scheduled_run:
                QMessageBox.information(
                    self,
                    self._text("Completed", "완료", "Zakończono"),
                    message,
                )
        else:
            self.log(f"\n[{self._text('Stopped/Failed', '중단/실패', 'Zatrzymano/Błąd')}] {message}")
            if not scheduled_run:
                if "중지" in message or "stopped" in message.lower() or "zatrzym" in message.lower():
                    QMessageBox.warning(self, self._text("Stopped", "중지됨", "Zatrzymano"), message)
                elif report_body:
                    QMessageBox.warning(self, self._text("Partially failed", "일부 실패", "Częściowe niepowodzenie"), message)
                else:
                    QMessageBox.critical(
                        self,
                        self._text("Failed", "실패", "Niepowodzenie"),
                        self._text("An error occurred while running the tasks.", "작업 실행 중 오류가 발생했습니다.", "Wystąpił błąd podczas wykonywania zadań.")
                        + f"\n\n{message}",
                    )

        QTimer.singleShot(0, self.refresh_readiness)

    def send_report_email(self, report_body):
        """결과 리포트 이메일 전송 및 실패 시 로컬 Fallback"""
        smtp_server = self.config_manager.get("smtp_server", "").strip()
        smtp_port_raw = self.config_manager.get("smtp_port", "")
        sender_email = self.config_manager.get("sender_email", "").strip()
        sender_password = self.config_manager.get("sender_password", "")
        receiver_email = self.config_manager.get("receiver_email", "").strip()
        mail_subject = self.config_manager.get("mail_subject", "통합 작업 완료 결과 보고서").strip()
        if self.language != "ko" and mail_subject == "통합 작업 완료 결과 보고서":
            mail_subject = "Task Result Report"
        mail_body_header = self.config_manager.get("mail_body_header", "").strip()
        
        if not smtp_server or not sender_email or not receiver_email:
            self.log(self._text("✗ Email was skipped because SMTP settings are incomplete.", "✗ SMTP 설정이 누락되어 이메일 발송을 건너뜁니다.", "✗ Pominięto e-mail z powodu niepełnych ustawień SMTP."))
            self.save_fallback_report(report_body)
            return
            
        try:
            smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
        except ValueError:
            smtp_port = 587
            
        # 메일 본문 가공
        full_body = ""
        if mail_body_header:
            full_body += f"{mail_body_header}\n\n"
            full_body += "=" * 60 + "\n\n"
        full_body += report_body
        
        self.log(self._text(f"✉ Sending the result to [{receiver_email}]...", f"✉ [{receiver_email}]에 결과를 발송합니다...", f"✉ Wysyłanie wyniku do [{receiver_email}]..."))
        
        # 비동기 발송이 아닌 동기적 발송으로 간결하게 처리 (완료 후 발송이므로 체감이 크지 않음)
        ok, send_msg = send_email(
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            sender_email=sender_email,
            sender_password=sender_password,
            receiver_emails=receiver_email,
            subject=mail_subject,
            body_text=full_body
        )
        
        if ok:
            self.log(self._text("✓ Email sent successfully.", "✓ 이메일을 전송했습니다.", "✓ E-mail wysłany pomyślnie."))
        else:
            self.log(self._text("✗ Email failed", "✗ 이메일 전송 실패", "✗ Nie udało się wysłać e-maila") + f": {self._runtime_error_text(send_msg)}")
            # 로컬 Fallback 저장
            self.save_fallback_report(full_body)
            
    def save_fallback_report(self, content):
        """이메일 발송 실패 또는 무설정 시 로컬 Fallback 텍스트 파일 저장 (Atomic Write)"""
        # AppData Local의 로그 디렉토리 획득
        local_app_data = os.environ.get('LOCALAPPDATA')
        if not local_app_data:
            user_profile = os.environ.get('USERPROFILE')
            if user_profile:
                local_app_data = os.path.join(user_profile, 'AppData', 'Local')
            else:
                local_app_data = os.getcwd()
                
        log_dir = os.path.join(local_app_data, 'IntegratedDataTool', 'logs')
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            log_dir = os.path.join(os.getcwd(), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        filename = f"task_report_{timestamp}.txt"
        
        temp_path = os.path.join(log_dir, f"{filename}.tmp")
        final_path = os.path.join(log_dir, filename)
        
        try:
            # 원자적 파일 쓰기(Atomic Write) 보장
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_path, final_path)
            
            msg = self._text("💾 Result report saved locally", "💾 결과 보고서를 로컬에 저장했습니다", "💾 Raport zapisano lokalnie") + f": {final_path}"
            self.log(msg)
            logger.info(msg)
        except Exception as e:
            logger.error(f"Failed to save fallback report atomically: {e}")
            self.log(self._text("✗ Could not save the result report", "✗ 결과 보고서를 저장하지 못했습니다", "✗ Nie można zapisać raportu") + f": {e}")
