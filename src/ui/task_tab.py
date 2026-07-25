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
from src.core.task_contracts import RunPlan, TaskStep, TaskValidationError
from src.ui.task_worker import TaskWorker
from src.utils.logger import get_logger

logger = get_logger()

class TaskTab(QWidget):
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
        
        title_label = QLabel("통합 태스크 실행 센터")
        title_label.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #e2e8f0;")
        ctrl_layout.addWidget(title_label)
        ctrl_layout.addStretch()

        self.check_schedule = QCheckBox("매일 자동 실행")
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
        self.check_auto_email = QCheckBox("작업 완료 후 결과 이메일 자동 발송")
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
        self.start_btn = QPushButton("일괄 작업 시작")
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
        
        self.stop_btn = QPushButton("작업 중지")
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
        
        # 2. 중간 상태 그리드 테이블 (Tab Summary Status)
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(2)
        self.status_table.setRowCount(5)
        self.status_table.setHorizontalHeaderLabels(["작업 단계", "현재 진행 상태"])
        self.status_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
        
        steps = [
            ("Folder Sync", "sync"),
            ("EML Image", "eml"),
            ("PDF Image", "pdf"),
            ("Image OCR", "ocr"),
            ("Bypass Convert", "bypass")
        ]
        self.step_keys = {}
        for row_idx, (name, key) in enumerate(steps):
            self.step_keys[key] = row_idx
            
            # 단계명
            name_item = QTableWidgetItem(name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name_item.setFont(QFont("Malgun Gothic", 9, QFont.Weight.Bold))
            self.status_table.setItem(row_idx, 0, name_item)
            
            # 상태
            status_item = QTableWidgetItem("대기 중")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor("#94a3b8"))
            self.status_table.setItem(row_idx, 1, status_item)
            
        layout.addWidget(self.status_table)
        
        # 3. 전체 진행률 프로그레스 바 영역
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(5)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("통합 진행률: %p%")
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
        self.detail_label = QLabel("대기 중...")
        self.detail_label.setStyleSheet("font-size: 11px; color: #a0a0a0;")
        progress_layout.addWidget(self.detail_label)
        
        layout.addLayout(progress_layout)
        
        # 4. 하단 상세 로그창
        log_label = QLabel("실시간 작업 로그")
        log_label.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        layout.addWidget(log_label)
        
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
        self.log(
            f"[예약 실행] {now.strftime('%Y-%m-%d %H:%M:%S')} 일괄 작업을 시작합니다."
        )
        started = self.start_all_tasks(scheduled=True)
        if not started:
            self.log("[예약 실행] 실행 가능한 작업 설정이 없어 오늘 작업을 건너뜁니다.")
        return started

    def start_all_tasks(self, checked=False, scheduled=False):
        """통합 일괄 실행 시작"""
        if self.is_running:
            return False
            
        main_win = self.window()
        if not main_win:
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
        
        try:
            for step, tab_obj in tabs.items():
                if tab_obj and hasattr(tab_obj, "build_run_config"):
                    config = tab_obj.build_run_config()
                    if config is not None:
                        configs[step] = config
        except TaskValidationError as val_err:
            if scheduled:
                self.log(f"[예약 실행] 설정 오류: {val_err.user_message}")
            else:
                QMessageBox.warning(self, "설정 오류", f"작업 실행을 준비하는 과정에서 설정 누락 또는 오입력이 감지되었습니다:\n\n{val_err.user_message}")
            return False
        except Exception as ex:
            if scheduled:
                self.log(f"[예약 실행] 설정 검증 오류: {ex}")
            else:
                QMessageBox.critical(self, "오류", f"설정을 검증하는 도중 오류가 발생했습니다: {ex}")
            return False

        run_plan = RunPlan(configs=configs)
            
        if run_plan.is_empty():
            if scheduled:
                self.log("[예약 실행] 활성화된 태스크가 없습니다.")
            else:
                QMessageBox.warning(self, "실행 대상 없음", "활성화된 태스크가 하나도 없습니다.\n각 탭에서 변환 대상이나 그룹을 설정한 후 시작해 주세요.")
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
                self.log("[예약 실행] 사전 점검 차단 이슈:\n" + preflight.format(include_warnings=False))
            else:
                QMessageBox.critical(self, "사전 점검 실패", preflight.format(include_warnings=False))
            return False

        if preflight.warnings:
            warning_text = preflight.format(include_warnings=True)
            if scheduled:
                self.log("[예약 실행] 사전 점검 경고:\n" + warning_text)
            else:
                reply = QMessageBox.question(
                    self,
                    "사전 점검 경고",
                    warning_text + "\n\n경고를 확인했습니다. 계속 진행할까요?",
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
        
        # 탭 상태 초기화
        for key in self.step_keys.keys():
            row = self.step_keys[key]
            if TaskStep(key) not in run_plan.configs:
                self.status_table.item(row, 1).setText("건너뜀")
                self.status_table.item(row, 1).setForeground(QColor("#94a3b8"))
            else:
                self.status_table.item(row, 1).setText("대기 중")
                self.status_table.item(row, 1).setForeground(QColor("#38bdf8"))
                
        self.progress_bar.setValue(0)
        self.detail_label.setText("통합 태스크 분석 중...")
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
            self.detail_label.setText("작업 중지 요청 중...")
            self.log("⚠ 작업 중지 요청을 전송하였습니다. 잠시만 기다려 주세요...")
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
            cell = self.status_table.item(row, 1)
            cell.setText(status)
            if status == "진행 중":
                cell.setForeground(QColor("#38bdf8"))
            elif status == "완료":
                cell.setForeground(QColor("#4ade80"))
            elif status == "일부 실패":
                cell.setForeground(QColor("#f87171"))
            elif status == "실패":
                cell.setForeground(QColor("#f87171"))
            elif status == "취소됨":
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
        
        main_win = self.window()
        if hasattr(main_win, "set_all_tabs_locked"):
            main_win.set_all_tabs_locked(False)
            
        self.detail_label.setText(message)

        # 성공/부분 실패와 무관하게 실행 결과가 있으면 담당자에게 보고합니다.
        if self.check_auto_email.isChecked() and report_body:
            self.send_report_email(report_body)
        
        if success:
            self.log(f"\n[성공] {message}")
            if not scheduled_run:
                QMessageBox.information(self, "완료", f"통합 태스크 실행이 성공적으로 완료되었습니다.\n\n{message}")
        else:
            self.log(f"\n[중단/실패] {message}")
            if not scheduled_run:
                if "중지" in message:
                    QMessageBox.warning(self, "중지됨", message)
                elif report_body:
                    QMessageBox.warning(self, "일부 실패", message)
                else:
                    QMessageBox.critical(self, "실패", f"작업 도중 오류가 발생했습니다:\n\n{message}")

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
            self.log("✗ SMTP 설정 정보가 누락되어 이메일 발송을 취소합니다.")
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
        
        self.log(f"✉ [{receiver_email}] 수신자에게 이메일 발송을 시작합니다...")
        
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
            self.log("✓ 이메일이 성공적으로 전송되었습니다.")
        else:
            self.log(f"✗ 이메일 전송에 실패하였습니다: {send_msg}")
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
            
            msg = f"💾 결과 보고서가 로컬 파일로 저장되었습니다: {final_path}"
            self.log(msg)
            logger.info(msg)
        except Exception as e:
            logger.error(f"Failed to save fallback report atomically: {e}")
            self.log(f"✗ 결과 보고서 로컬 저장에 실패하였습니다: {e}")
