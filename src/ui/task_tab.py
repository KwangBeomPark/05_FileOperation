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
from src.core.preflight import check_run_plan
from src.core.task_contracts import RunPlan, StepStatus, TaskStep, TaskValidationError
from src.ui.i18n import get_app_language, tr
from src.ui.task_worker import TaskWorker
from src.utils.logger import get_logger

logger = get_logger()

class TaskTab(QWidget):
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
        self.init_ui()

        self.schedule_timer = QTimer(self)
        self.schedule_timer.setInterval(30_000)
        self.schedule_timer.timeout.connect(self.check_scheduled_run)
        self.schedule_timer.start()
        QTimer.singleShot(0, self.check_scheduled_run)
        
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

        self.check_schedule.toggled.connect(self.schedule_time_edit.setEnabled)
        self.check_schedule.toggled.connect(self.save_automation_settings)
        self.schedule_time_edit.timeChanged.connect(self.save_automation_settings)
        self.check_auto_email.toggled.connect(self.save_automation_settings)
        
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

        self.selection_hint = QLabel()
        self.selection_hint.setWordWrap(True)
        self.selection_hint.setStyleSheet("color: #94a3b8; padding: 2px 4px;")
        layout.addWidget(self.selection_hint)
        
        # 2. 중간 상태 그리드 테이블 (Tab Summary Status)
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(3)
        self.status_table.setRowCount(5)
        self.status_table.setHorizontalHeaderLabels(["", "", ""])
        self.status_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.status_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.status_table.setMinimumHeight(180)
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
            self.status_table.setCellWidget(row_idx, 0, check_holder)
            self.step_checks[step] = run_check
            
            # 단계명
            name_item = QTableWidgetItem()
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name_item.setFont(QFont("Malgun Gothic", 9, QFont.Weight.Bold))
            self.status_table.setItem(row_idx, 1, name_item)
            
            # 상태
            status_item = QTableWidgetItem()
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor("#94a3b8"))
            self.status_table.setItem(row_idx, 2, status_item)
            
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
        self.refresh_language()

    @property
    def language(self):
        return get_app_language(self.config_manager)

    def step_label(self, step):
        return tr(f"task_step_{step.value}", self.language)

    def _text(self, english, korean, polish):
        return {"ko": korean, "pl": polish}.get(self.language, english)

    def selected_steps(self):
        return [step for step in self.STEP_ORDER if self.step_checks[step].isChecked()]

    def save_enabled_steps(self, _checked=False):
        self.config_manager.set("task_enabled_steps", [step.value for step in self.selected_steps()])
        if not self.is_running:
            for step in self.STEP_ORDER:
                row = self.step_keys[step.value]
                status_key = "pending" if self.step_checks[step].isChecked() else "skipped"
                self._set_status_item(self.status_table.item(row, 2), status_key)

    def refresh_language(self):
        language = self.language
        self.title_label.setText(tr("task_title", language))
        self.check_schedule.setText(tr("task_schedule", language))
        self.check_auto_email.setText(tr("task_auto_email", language))
        self.start_btn.setText(tr("task_start", language))
        self.stop_btn.setText(tr("task_stop", language))
        self.selection_hint.setText(tr("task_selection_hint", language))
        self.status_table.setHorizontalHeaderLabels([
            tr("task_run_header", language),
            tr("task_feature_header", language),
            tr("task_status_header", language),
        ])
        for step in self.STEP_ORDER:
            row = self.step_keys[step.value]
            self.status_table.item(row, 1).setText(self.step_label(step))
            status_item = self.status_table.item(row, 2)
            status_key = status_item.data(Qt.ItemDataRole.UserRole)
            if not status_key:
                status_key = "pending" if self.step_checks[step].isChecked() else "skipped"
            self._set_status_item(status_item, status_key)
        self.progress_bar.setFormat(tr("task_progress_format", language))
        self.detail_label.setText(tr("task_waiting", language))
        self.log_label.setText(tr("task_log_title", language))

    def _set_status_item(self, item, status_key):
        item.setData(Qt.ItemDataRole.UserRole, status_key)
        item.setText(tr(f"task_status_{status_key}", self.language))
        
    def log(self, message):
        self.log_area.append(message)
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def save_automation_settings(self):
        """예약 실행과 이메일 자동 발송 옵션을 즉시 저장합니다."""
        self.config_manager.set(
            "task_schedule_enabled", self.check_schedule.isChecked()
        )
        self.config_manager.set(
            "task_schedule_time", self.schedule_time_edit.time().toString("HH:mm")
        )
        self.config_manager.set(
            "task_auto_email", self.check_auto_email.isChecked()
        )
        self.save_enabled_steps()

    def check_scheduled_run(self, now=None):
        """앱이 실행 중일 때 지정 시각 이후 하루 한 번 일괄 작업을 시작합니다."""
        if not self.check_schedule.isChecked() or self.is_running:
            return False

        now = now or datetime.now()
        scheduled_time = self.schedule_time_edit.time()
        scheduled_minutes = scheduled_time.hour() * 60 + scheduled_time.minute()
        current_minutes = now.hour * 60 + now.minute
        today = now.strftime("%Y-%m-%d")

        if current_minutes < scheduled_minutes:
            return False
        if self.config_manager.get("task_schedule_last_run_date", "") == today:
            return False

        # 잘못된 설정으로 30초마다 재시도하지 않도록 당일 실행 시도를 먼저 기록합니다.
        self.config_manager.set("task_schedule_last_run_date", today)
        prefix = tr("task_scheduled_prefix", self.language)
        self.log(f"[{prefix}] " + tr(
            "task_scheduled_start",
            self.language,
            timestamp=now.strftime('%Y-%m-%d %H:%M:%S'),
        ))
        started = self.start_all_tasks(scheduled=True)
        if not started:
            self.log(f"[{prefix}] {tr('task_scheduled_skipped', self.language)}")
        return started

    def start_all_tasks(self, checked=False, scheduled=False):
        """통합 일괄 실행 시작"""
        if self.is_running:
            return False
            
        main_win = self.window()
        if not main_win:
            return False

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
            return False
            
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
            return False
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
            return False

        run_plan = RunPlan(configs=configs)
            
        if run_plan.is_empty():
            if scheduled:
                self.log(self._text("[Scheduled run] No runnable task was found.", "[예약 실행] 실행 가능한 작업이 없습니다.", "[Harmonogram] Nie znaleziono zadania do uruchomienia."))
            else:
                QMessageBox.warning(self, tr("task_no_selection_title", self.language), tr("task_no_selection_body", self.language))
            return False

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
            return False

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
                    QMessageBox.StandardButton.Yes,
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
        self.schedule_time_edit.setEnabled(False)
        for check in self.step_checks.values():
            check.setEnabled(False)
        
        # 탭 상태 초기화
        for key in self.step_keys.keys():
            row = self.step_keys[key]
            if TaskStep(key) not in run_plan.configs:
                self._set_status_item(self.status_table.item(row, 2), "skipped")
                self.status_table.item(row, 2).setForeground(QColor("#94a3b8"))
            else:
                self._set_status_item(self.status_table.item(row, 2), "pending")
                self.status_table.item(row, 2).setForeground(QColor("#38bdf8"))
                
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
            cell = self.status_table.item(row, 2)
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
        self.schedule_time_edit.setEnabled(self.check_schedule.isChecked())
        for check in self.step_checks.values():
            check.setEnabled(True)
        
        main_win = self.window()
        if hasattr(main_win, "set_all_tabs_locked"):
            main_win.set_all_tabs_locked(False)
            
        self.detail_label.setText(message)

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

    def send_report_email(self, report_body):
        """결과 리포트 이메일 전송 및 실패 시 로컬 Fallback"""
        smtp_server = self.config_manager.get("smtp_server", "").strip()
        smtp_port_raw = self.config_manager.get("smtp_port", "")
        sender_email = self.config_manager.get("sender_email", "").strip()
        sender_password = self.config_manager.get("sender_password", "")
        receiver_email = self.config_manager.get("receiver_email", "").strip()
        mail_subject = self.config_manager.get("mail_subject", "통합 작업 완료 결과 보고서").strip()
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
            self.log(self._text("✗ Email failed", "✗ 이메일 전송 실패", "✗ Nie udało się wysłać e-maila") + f": {send_msg}")
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
