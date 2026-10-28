import os
import time
from collections import deque
from dataclasses import replace
from datetime import datetime

from PyQt6.QtCore import Qt, QTime, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

# Core Modules
from src.core.diagnostics import DiagnosticItem, DiagnosticStatus
from src.core.folder_watcher import FolderWatcher
from src.core.preflight import check_run_plan
from src.core.preset_manager import (
    apply_workflow_preset,
    export_workflow_preset,
    load_workflow_preset,
)
from src.core.run_journal import RunJournal
from src.core.schedule import evaluate_flexible_schedule, parse_timestamp
from src.core.task_contracts import (
    BypassRunConfig,
    ExecutionItem,
    OcrRunConfig,
    RunPlan,
    SourceDisposition,
    StepStatus,
    SyncRunConfig,
    TaskStep,
    TaskValidationError,
)
from src.core.task_history import merge_run_report_history, normalize_step_history
from src.core.task_items import migrate_task_selection
from src.core.task_notifier import (
    ReportNotification,
    localize_runtime_error,
    save_fallback_report,
)
from src.ui.diagnostics_dialog import DiagnosticsDialog
from src.ui.i18n import get_app_language, tr
from src.ui.notification_worker import NotificationWorker
from src.ui.preflight_dialog import run_bounded_preflight
from src.ui.run_history_dialog import RunHistoryDialog
from src.ui.run_summary_dialog import confirm_run_summary
from src.ui.task_panel import TaskPanelMixin
from src.ui.task_worker import TaskWorker
from src.utils.logger import get_logger

logger = get_logger()

class TaskTab(TaskPanelMixin, QWidget):
    SCHEDULE_RETRY_MINUTES = 10
    SCHEDULE_MAX_START_ATTEMPTS = 3
    STALL_WARNING_SECONDS = 300
    COL_RUN = 0
    COL_ORDER = 1
    COL_TYPE = 2
    COL_FEATURE = 3
    COL_PATHS = 4
    COL_READINESS = 5
    COL_STATUS = 6
    COL_LAST_RESULT = 7

    STEP_ORDER = (
        TaskStep.SYNC,
        TaskStep.COLLECT_SYNC,
        TaskStep.EML,
        TaskStep.PDF,
        TaskStep.OCR,
    )

    folder_files_detected = pyqtSignal(list)

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.worker = None
        self.notification_workers = []
        self.folder_watcher = None
        self.is_running = False
        self.is_scheduled_run = False
        self.is_preflighting = False
        self.start_failure_reason = ""
        self.current_run_id = ""
        self.current_report_path = ""
        self.current_run_finalized = False
        self.current_step = None
        self.last_activity_monotonic = 0.0
        self.stall_warning_shown = False
        self.run_journal = None
        app_dir = getattr(config_manager, "app_dir", None)
        if app_dir:
            try:
                self.run_journal = RunJournal(app_dir)
                self.run_journal.recover_interrupted_runs()
            except Exception:
                logger.exception("Could not initialize the run journal")
        migration_warning = ""
        try:
            migrate_task_selection(self.config_manager)
        except OSError as exc:
            migration_warning = f"Could not save task selection migration: {exc}"
            logger.warning(migration_warning)
            self._selection_save_failed = True
        self.live_log = deque(maxlen=20000)
        self.init_ui()
        if migration_warning:
            self.log(migration_warning)
        if "bypass" in self.config_manager.get("task_enabled_steps", []):
            self.log(self._text(
                "File conversion (BYPASS) is excluded from the integrated four-step run. Use its own tab to run it.",
                "파일 변환(BYPASS)은 통합 4단계 실행에 포함되지 않으며 개별 탭에서 실행하세요.",
                "Konwersja plików (BYPASS) jest wyłączona ze zintegrowanego uruchomienia czterech etapów. Uruchom ją na osobnej karcie.",
            ))

        self.schedule_timer = QTimer(self)
        self.schedule_timer.setInterval(30_000)
        self.schedule_timer.timeout.connect(self._on_schedule_tick)
        self.schedule_timer.start()
        self.run_health_timer = QTimer(self)
        self.run_health_timer.setInterval(15_000)
        self.run_health_timer.timeout.connect(self._check_run_health)
        self.run_health_timer.start()
        self.folder_files_detected.connect(self._handle_folder_watcher_files)
        self._init_folder_watcher()
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
        self.next_run_label = QLabel()
        self.next_run_label.setStyleSheet("color: #7dd3fc;")
        ctrl_layout.addWidget(self.next_run_label)
        
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
        self.history_btn = QPushButton()
        self.history_btn.setMinimumHeight(30)
        self.history_btn.clicked.connect(self.open_run_history)
        self.history_btn.setEnabled(self.run_journal is not None)
        hint_layout.addWidget(self.history_btn)
        self.readiness_btn = QPushButton()
        self.readiness_btn.setMinimumHeight(30)
        self.readiness_btn.clicked.connect(self.refresh_readiness)
        hint_layout.addWidget(self.readiness_btn)
        self.diagnostics_btn = QPushButton()
        self.diagnostics_btn.setMinimumHeight(30)
        self.diagnostics_btn.clicked.connect(self.open_diagnostics)
        hint_layout.addWidget(self.diagnostics_btn)
        self.export_preset_btn = QPushButton()
        self.export_preset_btn.setMinimumHeight(30)
        self.export_preset_btn.clicked.connect(self.export_preset)
        hint_layout.addWidget(self.export_preset_btn)
        self.import_preset_btn = QPushButton()
        self.import_preset_btn.setMinimumHeight(30)
        self.import_preset_btn.clicked.connect(self.import_preset)
        hint_layout.addWidget(self.import_preset_btn)
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

        self.check_chain_outputs = QCheckBox()
        self.check_chain_outputs.setChecked(
            bool(self.config_manager.get("task_chain_outputs", False))
        )
        self.check_chain_outputs.setStyleSheet(
            "color: #a7f3d0; background-color: #064e3b; border: 1px solid #047857; "
            "border-radius: 5px; padding: 6px 8px;"
        )
        layout.addWidget(self.check_chain_outputs)

        self.check_schedule.toggled.connect(self._on_schedule_toggled)
        self.schedule_time_edit.timeChanged.connect(self.save_automation_settings)
        self.check_auto_email.toggled.connect(self.save_automation_settings)
        self.check_allow_source_backup.toggled.connect(self.save_automation_settings)
        self.check_chain_outputs.toggled.connect(self.save_automation_settings)
        
        # 2. 중간 상태 그리드 테이블 (Tab Summary Status)
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(8)
        self.status_table.setRowCount(0)
        self.status_table.setHorizontalHeaderLabels(self.table_headers())
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
        
        self.rows = []
        self.item_checks = {}
        self.step_keys = {}
        self.step_checks = {}
        self.status_table.cellDoubleClicked.connect(self.navigate_row)
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self.status_table)
        layout.addWidget(self.main_splitter, 1)
        self.rebuild_status_table()

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

        self.run_health_label = QLabel()
        self.run_health_label.setStyleSheet("font-size: 10px; color: #64748b;")
        progress_layout.addWidget(self.run_health_label)
        
        layout.insertLayout(layout.indexOf(self.main_splitter), progress_layout)
        
        # 4. 하단 상세 로그창
        self.log_label = QLabel()
        self.log_label.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setMaximumBlockCount(20000)
        self.history_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.history_splitter.setChildrenCollapsible(False)
        history_panel = QWidget()
        history_panel.setMinimumWidth(260)
        history_layout = QVBoxLayout(history_panel)
        self.type_filter = QComboBox()
        self.status_filter = QComboBox()
        self.history_list = QListWidget()
        history_layout.addWidget(self.type_filter)
        history_layout.addWidget(self.status_filter)
        history_layout.addWidget(self.history_list, 1)
        self.type_filter.currentIndexChanged.connect(self.refresh_run_list)
        self.status_filter.currentIndexChanged.connect(self.refresh_run_list)
        self.history_list.currentItemChanged.connect(self.show_history_item)
        viewer = QWidget()
        viewer_layout = QVBoxLayout(viewer)
        viewer_layout.addWidget(self.log_label)
        toolbar = QHBoxLayout()
        self.log_search = QLineEdit()
        self.log_search_prev_btn = QPushButton()
        self.log_search_next_btn = QPushButton()
        toolbar.addWidget(self.log_search, 1)
        toolbar.addWidget(self.log_search_prev_btn)
        toolbar.addWidget(self.log_search_next_btn)
        self.log_export_btn = QPushButton()
        self.log_copy_btn = QPushButton()
        self.log_notepad_btn = QPushButton()
        self.log_folder_btn = QPushButton()
        self.log_clear_btn = QPushButton()
        for button in (self.log_copy_btn, self.log_notepad_btn, self.log_folder_btn, self.log_export_btn, self.log_clear_btn):
            toolbar.addWidget(button)
        self.log_search.textChanged.connect(lambda: self.find_viewer_text(restart=True))
        self.log_search.returnPressed.connect(self.find_viewer_text)
        self.log_search_next_btn.clicked.connect(lambda: self.find_viewer_text())
        self.log_search_prev_btn.clicked.connect(lambda: self.find_viewer_text(backward=True))
        self.log_export_btn.clicked.connect(self.export_log)
        self.log_copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.log_area.toPlainText()))
        self.log_folder_btn.clicked.connect(self.open_reports_folder)
        self.log_notepad_btn.clicked.connect(self.open_viewer_in_notepad)
        self.log_clear_btn.clicked.connect(self.clear_live_log)
        viewer_layout.addLayout(toolbar)
        viewer_layout.addWidget(self.log_area, 1)
        self.history_splitter.addWidget(history_panel)
        self.history_splitter.addWidget(viewer)
        self.history_splitter.setStretchFactor(0, 0)
        self.history_splitter.setStretchFactor(1, 1)
        self.history_splitter.setSizes([280, 800])
        self.main_splitter.addWidget(self.history_splitter)
        self.main_splitter.setSizes([280, 360])
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

    def table_headers(self):
        return [
            tr("task_run_header", self.language),
            self._text("Order", "순서", "Kolejność"),
            self._text("Type", "유형", "Typ"),
            self._text("Name", "이름", "Nazwa"),
            self._text("Summary", "폴더 및 규칙 요약", "Podsumowanie"),
            tr("task_readiness_header", self.language),
            tr("task_status_header", self.language),
            tr("task_last_result_header", self.language),
        ]

    def _runtime_error_text(self, value):
        return localize_runtime_error(value, self.language)

    def selected_steps(self):
        return list(dict.fromkeys(row["step"] for row in self.rows if self.item_checks[row["key"]].isChecked()))

    def save_enabled_steps(self, _checked=False):
        selection = dict(self.config_manager.get("task_enabled_items", {}) or {})
        selection.update({key: check.isChecked() for key, check in self.item_checks.items()})
        self._selection_save_failed = self._update_config({
            "task_enabled_items": selection,
            "task_enabled_steps": [step.value for step in self.selected_steps()],
        }) is False
        if self._selection_save_failed:
            self.log(tr("collect_save_error", self.language))
        if not self.is_running:
            for row_index, row in enumerate(self.rows):
                selected = self.item_checks[row["key"]].isChecked()
                self._set_status_item(self.status_table.item(row_index, self.COL_STATUS), "pending" if selected else "skipped")
        self.refresh_readiness()

    def _update_backup_consent_visibility(self):
        bypass_check = getattr(self, "step_checks", {}).get(TaskStep.BYPASS)
        bypass_selected = bool(bypass_check and bypass_check.isChecked())
        separate_output = self.config_manager.get("bypass_output_mode", "inplace") == "custom"
        backup_enabled = separate_output and (
            self.config_manager.get("bypass_source_disposition", SourceDisposition.KEEP.value)
            == SourceDisposition.BACKUP.value
        )
        relevant = self.check_schedule.isChecked() and bypass_selected and backup_enabled
        self.check_allow_source_backup.setVisible(relevant)
        self.check_allow_source_backup.setEnabled(relevant and not self.is_running)

    def showEvent(self, event):
        super().showEvent(event)
        self.rebuild_status_table()
        self.refresh_readiness()
        self.refresh_run_list()
        self._update_backup_consent_visibility()

    def refresh_language(self):
        language = self.language
        self.title_label.setText(tr("task_title", language))
        self.check_schedule.setText(tr("task_schedule", language))
        self.check_auto_email.setText(tr("task_auto_email", language))
        self.check_allow_source_backup.setText(tr("task_schedule_allow_source_backup", language))
        self.check_allow_source_backup.setToolTip(tr("task_schedule_allow_source_backup_help", language))
        self.check_chain_outputs.setText(
            self._text(
                "Pipeline Output Chaining (Pass EML/PDF converted images directly to OCR)",
                "파이프라인 출력 연계 (EML/PDF 변환 이미지 결과를 OCR 입력으로 자동 연결)",
                "Łączenie potoku (przekaż obrazy EML/PDF bezpośrednio do OCR)",
            )
        )
        self.check_chain_outputs.setToolTip(
            self._text(
                "When enabled, converted image outputs from EML or PDF steps are automatically fed into OCR processing.",
                "활성화 시 EML 또는 PDF 변환 단계에서 생성된 이미지들이 OCR 단계의 대상 파일로 자동 전달됩니다.",
                "Po włączeniu obrazy wyjściowe z etapów EML lub PDF są automatycznie przekazywane do przetwarzania OCR.",
            )
        )
        self.start_btn.setText(tr("task_start", language))
        self.stop_btn.setText(tr("task_stop", language))
        self.history_btn.setText(tr("run_history_button", language))
        self.readiness_btn.setText(tr("task_check_readiness", language))
        self.diagnostics_btn.setText(tr("diagnostics_open", language))
        self.export_preset_btn.setText(self._text("Export Preset", "프리셋 내보내기", "Eksportuj profil"))
        self.import_preset_btn.setText(self._text("Import Preset", "프리셋 가져오기", "Importuj profil"))
        self.selection_hint.setText(tr("task_selection_hint", language))
        self.status_table.setHorizontalHeaderLabels(self.table_headers())
        for index, row in enumerate(self.rows):
            self.status_table.item(index, self.COL_FEATURE).setText(row["name"] if row.get("group") else self.step_label(row["step"]))
            self.status_table.item(index, self.COL_TYPE).setText(self.row_type_label(row["step"]))
            status_item = self.status_table.item(index, self.COL_STATUS)
            self._set_status_item(status_item, status_item.data(Qt.ItemDataRole.UserRole) or "pending")
            readiness = self.status_table.item(index, self.COL_READINESS)
            self.set_row_readiness(index, readiness.data(Qt.ItemDataRole.UserRole) or "not_checked",
                                   readiness.data(Qt.ItemDataRole.UserRole.value + 1) or "")
        self.refresh_history_language()
        self.progress_bar.setFormat(tr("task_progress_format", language))
        self.detail_label.setText(tr("task_waiting", language))
        if not self.is_running:
            self.run_health_label.setText(tr("run_health_idle", language))
        self.log_label.setText(tr("task_log_title", language))
        self.refresh_history_display()
        self.refresh_schedule_summary()

    def _set_status_item(self, item, status_key):
        item.setData(Qt.ItemDataRole.UserRole, status_key)
        item.setText(tr(f"task_status_{status_key}", self.language))

    def _set_readiness_item(self, step, readiness_key, detail=""):
        for index, row in enumerate(self.rows):
            if row["step"] == step:
                self.set_row_readiness(index, readiness_key, detail)
        self._refresh_start_button_state()

    def set_row_readiness(self, index, key, detail=""):
        item = self.status_table.item(index, self.COL_READINESS)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setData(Qt.ItemDataRole.UserRole.value + 1, detail)
        item.setText(tr(f"task_readiness_{key}", self.language))
        item.setToolTip(detail)
        item.setForeground(QColor({"ready": "#4ade80", "blocked": "#f87171", "warning": "#fbbf24"}.get(key, "#94a3b8")))

    def _refresh_start_button_state(self):
        if hasattr(self, "item_checks") and not self.is_running:
            selected = bool(self.selected_steps())
            self.start_btn.setEnabled(selected and not getattr(self, "_selection_save_failed", False))
            self.start_btn.setToolTip(tr("task_start_ready" if selected else "task_start_prereq_none", self.language))

    def refresh_history_display(self):
        feature_history = normalize_step_history(self.config_manager.get("task_step_last_results", {}))
        item_history = self.config_manager.get("task_item_last_results", {}) or {}
        for index, row in enumerate(self.rows):
            entry = item_history.get(row["key"]) or (feature_history.get(row["step"].value) if not row.get("group") else None)
            item = self.status_table.item(index, self.COL_LAST_RESULT)
            if entry:
                item.setText(f"{tr('task_status_' + entry['status'], self.language)} · {entry['success_count']}/{entry['total_count']}")
                item.setToolTip("\n".join(filter(None, [entry.get("timestamp", ""), entry.get("detail", "")])))
            else:
                item.setText(tr("task_history_none", self.language))
                item.setToolTip("")

    def capture_run_report(self, report):
        items = dict(self.config_manager.get("task_item_last_results", {}) or {})
        timestamp = datetime.now().isoformat(timespec="seconds")
        for key, result in report.item_results.items():
            items[key] = dict(status=result.status.name.lower(), timestamp=timestamp,
                              success_count=result.success_count, total_count=result.total_count,
                              detail=result.error_message or "\n".join(result.details[-3:]))
        self.config_manager.set("task_item_last_results", items)
        history = merge_run_report_history(
            self.config_manager.get("task_step_last_results", {}),
            report,
        )
        self._update_config({"task_step_last_results": history})
        self.refresh_history_display()
        self._finish_run_journal(report)
        self.refresh_run_list()

    def open_run_history(self):
        if not self.run_journal:
            return
        dialog = RunHistoryDialog(self.run_journal, self.language, self)
        dialog.exec()

    def _begin_run_journal(self, run_plan, scheduled):
        self.current_run_id = ""
        if not self.run_journal:
            return
        try:
            self.current_run_id = self.run_journal.start_run(
                run_plan.active_steps,
                scheduled=scheduled,
                language=self.language,
            )
        except Exception:
            logger.exception("Could not start the run journal")

    def _record_activity(self, *, current_step=None, detail=None, current=None, total=None):
        if not self.is_running:
            return
        self.last_activity_monotonic = time.monotonic()
        self.stall_warning_shown = False
        self._show_active_health()
        if not self.run_journal or not self.current_run_id:
            return
        try:
            self.run_journal.touch(
                self.current_run_id,
                current_step=current_step,
                detail=detail,
                current=current,
                total=total,
            )
        except Exception:
            logger.exception("Could not update the run journal heartbeat")

    def _show_active_health(self):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.run_health_label.setText(tr("run_health_active", self.language, timestamp=timestamp))
        self.run_health_label.setStyleSheet("font-size: 10px; color: #4ade80;")

    def _check_run_health(self):
        if not self.is_running or not self.last_activity_monotonic:
            return
        elapsed = time.monotonic() - self.last_activity_monotonic
        if elapsed < self.STALL_WARNING_SECONDS:
            return
        minutes = max(1, int(elapsed // 60))
        self.run_health_label.setText(
            tr("run_health_stalled", self.language, minutes=minutes)
        )
        self.run_health_label.setStyleSheet(
            "font-size: 10px; color: #fbbf24; font-weight: bold;"
        )
        if not self.stall_warning_shown:
            self.stall_warning_shown = True
            self.log(tr("run_health_stalled", self.language, minutes=minutes))
            if self.run_journal and self.current_run_id:
                try:
                    self.run_journal.mark_possibly_stalled(self.current_run_id)
                except Exception:
                    logger.exception("Could not mark the run as possibly stalled")

    def _finish_run_journal(self, report):
        self._finalize_journal(
            lambda run_id: self.run_journal.finish_run(run_id, report),
            "Could not save the completed run report",
        )

    def _finish_failed_journal(self, message, report_body):
        self._finalize_journal(
            lambda run_id: self.run_journal.finish_failed(run_id, str(message), str(report_body or "")),
            "Could not save the failed run report",
        )

    def _finalize_journal(self, finish, failure_log):
        if self.current_run_finalized or not self.run_journal or not self.current_run_id:
            return
        try:
            self.current_report_path = finish(self.current_run_id)
            self.current_run_finalized = True
            self.log(tr("run_report_saved", self.language, path=self.current_report_path))
        except Exception as exc:
            logger.exception(failure_log)
            self.log(tr("run_report_save_failed", self.language, detail=str(exc)))

    def _feature_tabs(self, main_win=None):
        """Map each task step to its feature tab on the main window (None when absent)."""
        main_win = self.window() if main_win is None else main_win
        return {
            TaskStep.SYNC: getattr(main_win, "sync_tab", None),
            TaskStep.COLLECT_SYNC: getattr(main_win, "collect_sync_tab", None),
            TaskStep.EML: getattr(main_win, "eml_tab", None),
            TaskStep.PDF: getattr(main_win, "pdf_tab", None),
            TaskStep.OCR: getattr(main_win, "ocr_tab", None),
            TaskStep.BYPASS: getattr(main_win, "bypass_tab", None),
        }

    def _chained_ocr_config(self):
        """OCR config for a run whose OCR input comes from earlier EML/PDF outputs."""
        return OcrRunConfig(
            image_paths=[],
            rule_mode=str(self.config_manager.get("ocr_rule_mode", "promotion") or "promotion"),
            custom_pattern=str(self.config_manager.get("ocr_custom_pattern", "") or ""),
            rename_template=str(self.config_manager.get("ocr_rename_template", "{match}") or "{match}"),
            export_txt=bool(self.config_manager.get("ocr_export_txt", False)),
        )

    def _build_step_config(self, step, tabs, selected_steps):
        """Build one step's run config, raising TaskValidationError when it cannot run."""
        tab_obj = tabs.get(step)
        if tab_obj is None or not hasattr(tab_obj, "build_run_config"):
            raise TaskValidationError(
                tr("task_readiness_tab_unavailable", self.language),
                message_key="task_readiness_tab_unavailable",
            )
        config = tab_obj.build_run_config()
        if config is None:
            if (
                step == TaskStep.OCR
                and self.check_chain_outputs.isChecked()
                and (TaskStep.EML in selected_steps or TaskStep.PDF in selected_steps)
            ):
                return self._chained_ocr_config()
            raise TaskValidationError(
                tr("task_no_config", self.language),
                message_key="task_no_config",
            )
        return config

    def _collect_step_configs(self, selected_steps, main_win=None):
        """Build configs for the selected steps.

        Returns (configs, errors), both keyed by TaskStep in selection order; errors
        holds the exception raised while building that step's config.
        """
        tabs = self._feature_tabs(main_win)
        configs = {}
        errors = {}
        for step in selected_steps:
            try:
                if step in (TaskStep.SYNC, TaskStep.COLLECT_SYNC):
                    values = [self.build_row_config(row) for row in self.rows
                              if row["step"] == step and self.item_checks[row["key"]].isChecked()]
                    if step == TaskStep.SYNC:
                        configs[step] = SyncRunConfig([group for value in values if value for group in value.sync_groups])
                    elif values:
                        configs[step] = replace(values[0], groups=tuple(group for value in values for group in value.groups))
                else:
                    configs[step] = self._build_step_config(step, tabs, selected_steps)
            except Exception as exc:
                errors[step] = exc
        return configs, errors

    def _validation_detail(self, exc):
        if isinstance(exc, TaskValidationError):
            return tr(exc.message_key, self.language, **exc.values) if exc.message_key else exc.user_message
        return str(exc)

    def refresh_readiness(self):
        if self.is_running:
            return
        self.rebuild_status_table()
        for index, row in enumerate(self.rows):
            if not self.item_checks[row["key"]].isChecked():
                self.set_row_readiness(index, "not_selected")
                continue
            try:
                config = self.build_row_config(row)
                if config is None:
                    raise TaskValidationError(tr("task_no_config", self.language))
                report = check_run_plan(RunPlan({row["step"]: config}), self.config_manager, auto_email=False, check_office=False)
                issues = report.blockers or report.warnings
                self.set_row_readiness(index, "blocked" if report.blockers else "warning" if issues else "ready",
                                       "\n".join(issue.message for issue in issues))
            except Exception as exc:
                self.set_row_readiness(index, "blocked", self._validation_detail(exc))
        self._refresh_start_button_state()

    def open_diagnostics(self):
        selected_steps = self.selected_steps()
        if not selected_steps:
            QMessageBox.warning(
                self,
                tr("task_no_selection_title", self.language),
                tr("task_no_selection_body", self.language),
            )
            return

        configs, errors = self._collect_step_configs(selected_steps)
        validation_items = [
            DiagnosticItem(
                f"{step.value}_config",
                tr("diagnostics_feature_config", self.language, feature=self.step_label(step)),
                DiagnosticStatus.FAIL,
                self._validation_detail(exc),
                step.value,
            )
            for step, exc in errors.items()
        ]

        self.diagnostics_dialog = DiagnosticsDialog(
            self.config_manager,
            RunPlan(
                configs=configs,
                step_order=selected_steps,
                chain_outputs=bool(self.check_chain_outputs.isChecked()),
            ),
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
            if hasattr(main_win, "select_feature_tab"):
                main_win.select_feature_tab(self)
            elif hasattr(main_win, "tab_widget"):
                main_win.tab_widget.setCurrentWidget(self)
            return
        try:
            step = TaskStep(target)
        except ValueError:
            return
        widget = self._feature_tabs(main_win).get(step)
        if widget is not None:
            if hasattr(main_win, "select_feature_tab"):
                main_win.select_feature_tab(widget)
            elif hasattr(main_win, "tab_widget"):
                main_win.tab_widget.setCurrentWidget(widget)
        
    def log(self, message):
        self.live_log.append(str(message))
        if self.history_list.currentRow() == 0:
            self.log_area.appendPlainText(str(message))
            sb = self.log_area.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _collect_sync_busy(self):
        """Collection shares target folders, so it must not overlap a unified run."""
        return bool(getattr(getattr(self.window(), "collect_sync_tab", None), "is_busy", False))

    def _start_rejected(self, reason):
        self.start_failure_reason = str(reason or "").strip()
        return False

    def _warn_start_rejected(self, reason, scheduled):
        self.log(reason)
        if not scheduled:
            QMessageBox.warning(self, tr("run_error", self.language), reason)
        return self._start_rejected(reason)

    def _reject_unrunnable_items(self, items, scheduled):
        reason = self._text(
            "No runnable tasks remain. Check the selected tasks and resolve the following issues before trying again.",
            "실행 가능한 작업이 없습니다. 선택한 작업과 다음 문제를 확인한 후 다시 실행해 주세요.",
            "Brak zadań do uruchomienia. Sprawdź wybrane zadania i rozwiąż poniższe problemy przed ponowną próbą.",
        )
        details = [f"{item.name}: {item.error}" for item in items if item.error]
        if details:
            reason += "\n" + "\n".join(details)
        return self._warn_start_rejected(reason, scheduled)

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
        mode = self.config_manager.get("task_schedule_mode", "daily")
        interval_minutes = int(self.config_manager.get("task_schedule_interval_minutes", 60) or 60)
        weekdays = self.config_manager.get("task_schedule_weekdays", None)
        return evaluate_flexible_schedule(
            now=now,
            schedule_time=self.schedule_time_edit.time().toString("HH:mm"),
            schedule_mode=mode,
            interval_minutes=interval_minutes,
            weekdays=weekdays,
            last_started_at=self.config_manager.get("task_schedule_last_started_at", ""),
            legacy_last_run_date=self.config_manager.get("task_schedule_last_run_date", ""),
            attempt_date=self.config_manager.get("task_schedule_attempt_date", ""),
            attempt_count=self.config_manager.get("task_schedule_attempt_count", 0),
            last_attempt_at=self.config_manager.get("task_schedule_last_attempt_at", ""),
            retry_minutes=self.SCHEDULE_RETRY_MINUTES,
            max_start_attempts=self.SCHEDULE_MAX_START_ATTEMPTS,
        )

    def _init_folder_watcher(self):
        if bool(self.config_manager.get("task_folder_watch_enabled", False)):
            self.start_folder_watcher()

    def start_folder_watcher(self, watch_folders=None):
        self.stop_folder_watcher()
        folders = list(watch_folders or self.config_manager.get("task_watch_folders", []) or [])
        if not folders:
            sync_groups = self.config_manager.get("sync_groups", []) or []
            for g in sync_groups:
                if isinstance(g, dict):
                    folders.extend(g.get("folders", []))
        if not folders:
            return False
        debounce = float(self.config_manager.get("task_watch_debounce_seconds", 3.0) or 3.0)
        patterns = self.config_manager.get("task_watch_patterns", None)
        self.folder_watcher = FolderWatcher(
            watch_folders=folders,
            callback=lambda files: self.folder_files_detected.emit(files),
            debounce_seconds=debounce,
            patterns=patterns,
        )
        self.folder_watcher.start()
        return True

    def stop_folder_watcher(self):
        if self.folder_watcher:
            try:
                self.folder_watcher.stop()
            except Exception:
                pass
            self.folder_watcher = None

    def _handle_folder_watcher_files(self, changed_files: list):
        prefix = tr("task_scheduled_prefix", self.language)
        self.log(f"[{prefix}] FolderWatcher detected {len(changed_files)} changed file(s)")
        if not self.is_running and not self.is_preflighting:
            self.start_all_tasks(scheduled=True)

    def _last_schedule_outcome_text(self):
        started_at = parse_timestamp(self.config_manager.get("task_schedule_last_started_at", ""))
        finished_at = parse_timestamp(self.config_manager.get("task_schedule_last_finished_at", ""))
        success_at = parse_timestamp(self.config_manager.get("task_schedule_last_success_at", ""))
        failure_at = parse_timestamp(self.config_manager.get("task_schedule_last_failure_at", ""))
        reason = str(self.config_manager.get("task_schedule_last_failure_reason", "")).strip()
        if len(reason) > 140:
            reason = reason[:137] + "..."
        if started_at and finished_at and finished_at >= started_at:
            succeeded = bool(success_at and success_at == finished_at and (not failure_at or success_at >= failure_at))
            result = (
                tr("task_schedule_result_success", self.language)
                if succeeded
                else tr(
                    "task_schedule_result_failure",
                    self.language,
                    reason=reason or tr("task_schedule_unknown_failure", self.language),
                )
            )
            return tr(
                "task_schedule_run_window",
                self.language,
                started=started_at.strftime("%Y-%m-%d %H:%M:%S"),
                finished=finished_at.strftime("%Y-%m-%d %H:%M:%S"),
                duration=self._format_schedule_duration(started_at, finished_at),
                result=result,
            )
        if started_at and (not finished_at or finished_at < started_at):
            return tr(
                "task_schedule_run_unfinished",
                self.language,
                started=started_at.strftime("%Y-%m-%d %H:%M:%S"),
            )
        if success_at and (not failure_at or success_at >= failure_at):
            return tr(
                "task_schedule_last_success",
                self.language,
                timestamp=success_at.strftime("%Y-%m-%d %H:%M"),
            )
        if failure_at:
            return tr(
                "task_schedule_last_failure",
                self.language,
                timestamp=failure_at.strftime("%Y-%m-%d %H:%M"),
                reason=reason or tr("task_schedule_unknown_failure", self.language),
            )
        return tr("task_schedule_no_history", self.language)

    @staticmethod
    def _format_schedule_duration(started_at, finished_at):
        total_seconds = max(0, int((finished_at - started_at).total_seconds()))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def refresh_schedule_summary(self, now=None):
        now = now or datetime.now()
        next_at = self._schedule_decision(now).next_at.strftime("%m/%d %H:%M")
        self.next_run_label.setText(
            "(" + tr("task_schedule_next_run", self.language, timestamp=next_at) + ")"
            if self.check_schedule.isChecked() else ""
        )
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
            "task_chain_outputs": self.check_chain_outputs.isChecked(),
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
        if self._collect_sync_busy():
            # Wait for the next tick; the daily slot is not consumed while collection runs.
            return False
        if (not self.check_schedule.isChecked() or self.is_running or self.is_preflighting
                or getattr(self.window(), "_run_confirmation_active", False)):
            return False

        now = now or datetime.now()
        decision = self._schedule_decision(now)
        if not decision.should_start:
            return False

        attempt_count = decision.attempt_count + 1
        timestamp = now.isoformat(timespec="seconds")
        saved = self._update_config({
            "task_schedule_attempt_date": now.date().isoformat(),
            "task_schedule_attempt_count": attempt_count,
            "task_schedule_last_attempt_at": timestamp,
        })
        if saved is False:
            return self._start_rejected(tr("collect_save_error", self.language))
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
                "task_schedule_last_finished_at": "",
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
        if getattr(self, "_selection_save_failed", False):
            return self._start_rejected(tr("collect_save_error", self.language))
        if self._collect_sync_busy():
            return self._start_rejected(tr("collect_busy", self.language))
        if self.is_preflighting or getattr(self.window(), "_run_confirmation_active", False):
            return self._start_rejected(self._text(
                "Another run is being reviewed. Finish or cancel it first.",
                "다른 실행을 확인 중입니다. 먼저 확인을 마치거나 취소해 주세요.",
                "Trwa sprawdzanie innego uruchomienia. Zakończ je lub anuluj.",
            ))
        if self.is_running:
            return self._start_rejected(tr("task_schedule_already_running", self.language))
        for tab in self._feature_tabs().values():
            if tab and (getattr(tab, "is_running", False) is True or getattr(tab, "is_converting", False) is True):
                return self._start_rejected(tr("task_schedule_already_running", self.language))
        self.rebuild_status_table()
            
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
            
        items = []
        configs = {}
        for row in self.rows:
            if not self.item_checks[row["key"]].isChecked():
                continue
            try:
                config = self.build_row_config(row)
                if config is None:
                    raise TaskValidationError(tr("task_no_config", self.language))
                items.append(ExecutionItem(row["key"], row["step"], row["name"], config))
                if row["step"] == TaskStep.SYNC and TaskStep.SYNC in configs:
                    config = SyncRunConfig(configs[TaskStep.SYNC].sync_groups + config.sync_groups)
                elif row["step"] == TaskStep.COLLECT_SYNC and TaskStep.COLLECT_SYNC in configs:
                    config = replace(config, groups=configs[TaskStep.COLLECT_SYNC].groups + config.groups)
                configs[row["step"]] = config
            except Exception as exc:
                items.append(ExecutionItem(row["key"], row["step"], row["name"], error=self._validation_detail(exc)))
        if not any(item.config is not None and not item.error for item in items):
            return self._reject_unrunnable_items(items, scheduled)
        run_plan = RunPlan(configs=configs, step_order=selected_steps,
                           chain_outputs=self.check_chain_outputs.isChecked(), items=items)

        bypass_config = run_plan.get(TaskStep.BYPASS)
        replace_requested = (
            isinstance(bypass_config, BypassRunConfig)
            and bypass_config.source_disposition == SourceDisposition.REPLACE
        )
        if replace_requested:
            reason = tr("task_source_replace_direct_only", self.language)
            self.log(f"[{tr('task_scheduled_prefix', self.language)}] {reason}" if scheduled else reason)
            self._set_readiness_item(TaskStep.BYPASS, "blocked", reason)
            if not scheduled:
                QMessageBox.warning(self, tr("run_error", self.language), reason)
            return self._start_rejected(reason)

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
        self.is_preflighting = True
        try:
            preflight, preflight_error, preflight_cancelled = run_bounded_preflight(
                self,
                run_plan,
                self.config_manager,
                auto_email=self.check_auto_email.isChecked(),
                visible=not scheduled,
            )
        finally:
            self.is_preflighting = False
        if preflight is None:
            if preflight_cancelled:
                reason = self._text(
                    "Preflight was cancelled. No task was started.",
                    "실행 전 점검을 취소했습니다. 작업은 시작되지 않았습니다.",
                    "Anulowano kontrolę. Zadanie nie zostało uruchomione.",
                )
            else:
                reason = self._text(
                    f"Preflight could not be completed: {preflight_error}",
                    f"실행 전 점검을 완료하지 못했습니다: {preflight_error}",
                    f"Nie można ukończyć kontroli: {preflight_error}",
                )
            if scheduled:
                self.log(f"[{tr('task_scheduled_prefix', self.language)}] {reason}")
            else:
                QMessageBox.warning(self, self._text("Preflight Check", "실행 전 점검", "Kontrola przed uruchomieniem"), reason)
            return self._start_rejected(reason)
        if preflight.has_blockers:
            blocked = {issue.step for issue in preflight.blockers}
            if None in blocked:
                return self._warn_start_rejected(preflight.format(include_warnings=False, language=self.language), scheduled)
            items = [replace(item, error="\n".join(issue.message for issue in preflight.blockers if issue.step == item.step))
                     if item.step in blocked else item for item in items]
            configs = {step: config for step, config in configs.items() if step not in blocked}
            run_plan = replace(run_plan, items=items, configs=configs)

        if not any(item.config is not None and not item.error for item in items):
            return self._reject_unrunnable_items(items, scheduled)

        warning_text = preflight.format(include_warnings=True, language=self.language) if preflight.warnings else ""
        item_errors = [f"{item.name}: {item.error}" for item in items if item.error]
        if item_errors:
            warning_text += "\n" + "\n".join(item_errors)
        if scheduled and warning_text:
            self.log(self._text("[Scheduled run] Preflight warning:\n", "[예약 실행] 사전 점검 경고:\n", "[Harmonogram] Ostrzeżenie kontroli wstępnej:\n") + warning_text)
        if not confirm_run_summary(self, replace(run_plan, items=[], step_order=list(configs)), self.config_manager, scheduled=scheduled, warnings=warning_text):
            return self._start_rejected(self._text(
                "The change review was not completed. No task was started.",
                "변경 내용 확인을 완료하지 않아 작업을 시작하지 않았습니다.",
                "Nie ukończono przeglądu zmian. Nie uruchomiono zadania.",
            ))
                    
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
        self.check_chain_outputs.setEnabled(False)
        self.import_preset_btn.setEnabled(False)
        for check in self.item_checks.values():
            check.setEnabled(False)
        
        for index, row in enumerate(self.rows):
            self._set_status_item(self.status_table.item(index, self.COL_STATUS),
                                  "pending" if self.item_checks[row["key"]].isChecked() else "skipped")
        self.progress_bar.setValue(0)
        self.detail_label.setText(tr("task_status_running", self.language))
        self.current_step = None
        self.last_activity_monotonic = time.monotonic()
        self.stall_warning_shown = False
        self.current_report_path = ""
        self.current_run_finalized = False
        self._begin_run_journal(run_plan, scheduled)
        self._show_active_health()
        self.clear_live_log()
        self.history_list.setCurrentRow(0)
        
        # 다른 탭들 UI 잠금 걸기
        if hasattr(main_win, "set_all_tabs_locked"):
            main_win.set_all_tabs_locked(True)
            
        # 3. TaskWorker (QThread) 생성 및 실행
        try:
            self.worker = TaskWorker(self.config_manager, run_plan)
            self.worker.log_signal.connect(self.handle_worker_log)
            self.worker.step_progress.connect(self.update_step_progress)
            self.worker.total_progress.connect(self.update_total_progress)
            self.worker.item_status_changed.connect(self.update_item_status)
            self.worker.report_ready.connect(self.capture_run_report)
            self.worker.finished.connect(lambda worker=self.worker: self._worker_stopped(worker))
            self.worker.start()
        except Exception as exc:
            worker = self.worker
            self.worker = None
            if worker:
                worker.deleteLater()
            self.on_tasks_finished(False, str(exc), "")
            return self._start_rejected(str(exc))
        return True

    def _worker_stopped(self, worker):
        if self.worker is not worker or worker.isRunning():
            return
        self.worker = None
        self.on_tasks_finished(*worker.outcome)
        worker.deleteLater()

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
        for worker in list(self.notification_workers):
            worker.wait()

    def update_step_progress(self, current, total, detail_msg):
        self.detail_label.setText(detail_msg)
        self._record_activity(current=current, total=total, detail=detail_msg)

    def update_total_progress(self, percent):
        self.progress_bar.setValue(percent)
        self._record_activity()

    def handle_worker_log(self, message):
        self.log(message)
        self._record_activity()
        
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
            self.current_step = TaskStep(key)
            self._record_activity(current_step=self.current_step)
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
        self._finish_failed_journal(message, report_body)
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
        self.check_chain_outputs.setEnabled(True)
        self.import_preset_btn.setEnabled(True)
        for check in self.item_checks.values():
            check.setEnabled(True)
        self._refresh_start_button_state()

        if not success and not report_body:
            for index, _row in enumerate(self.rows):
                status_item = self.status_table.item(index, self.COL_STATUS)
                if status_item.data(Qt.ItemDataRole.UserRole) in {"pending", "running"}:
                    self._set_status_item(status_item, "failed")
        
        main_win = self.window()
        if hasattr(main_win, "set_all_tabs_locked"):
            main_win.set_all_tabs_locked(False)
            
        self.detail_label.setText(message)
        self.run_health_label.setText(tr("run_health_idle", self.language))
        self.run_health_label.setStyleSheet("font-size: 10px; color: #64748b;")

        if scheduled_run:
            finished_time = datetime.now()
            finished_at = finished_time.isoformat(timespec="seconds")
            started_time = parse_timestamp(self.config_manager.get("task_schedule_last_started_at", ""))
            duration = self._format_schedule_duration(started_time, finished_time) if started_time else "--:--:--"
            if success:
                self._update_config({
                    "task_schedule_last_finished_at": finished_at,
                    "task_schedule_last_success_at": finished_at,
                    "task_schedule_last_failure_reason": "",
                })
                result_text = tr("task_schedule_result_success", self.language)
            else:
                self._update_config({
                    "task_schedule_last_finished_at": finished_at,
                    "task_schedule_last_failure_at": finished_at,
                    "task_schedule_last_failure_reason": str(message),
                })
                result_text = tr(
                    "task_schedule_result_failure",
                    self.language,
                    reason=str(message),
                )
            self.log(
                f"[{tr('task_scheduled_prefix', self.language)}] "
                + tr(
                    "task_schedule_finished_log",
                    self.language,
                    timestamp=finished_time.strftime("%Y-%m-%d %H:%M:%S"),
                    duration=duration,
                    result=result_text,
                )
            )
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

        self.refresh_run_list()
        QTimer.singleShot(0, self.refresh_readiness)
        self.current_run_id = ""

    def send_report_email(self, report_body):
        """결과 리포트 이메일/웹훅 전송 및 실패 시 로컬 Fallback (백그라운드 스레드)"""
        notification = ReportNotification.from_config(
            self.config_manager,
            self.language,
            has_saved_report=bool(self.current_report_path),
        )
        worker = NotificationWorker(notification, report_body, self)
        worker.log_signal.connect(self.log)
        worker.finished.connect(lambda: self._on_notification_finished(worker))
        self.notification_workers.append(worker)
        worker.start()
        return worker

    def _on_notification_finished(self, worker):
        if worker in self.notification_workers:
            self.notification_workers.remove(worker)
        worker.deleteLater()

    def save_fallback_report(self, content):
        """이메일 발송 실패 또는 무설정 시 로컬 Fallback 텍스트 파일 저장 (Atomic Write)"""
        return save_fallback_report(content, log=self.log, text=self._text)

    def export_preset(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self._text("Export Workflow Preset", "워크플로우 프리셋 내보내기", "Eksportuj profil przepływu pracy"),
            os.path.join(os.getcwd(), "workflow_preset.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return
        try:
            config_dict = getattr(self.config_manager, "config", {}) or {}
            export_workflow_preset(config_dict, file_path)
            self.log(self._text(f"✓ Preset exported to: {file_path}", f"✓ 프리셋이 내보내졌습니다: {file_path}", f"✓ Profil wyeksportowany do: {file_path}"))
            QMessageBox.information(
                self,
                self._text("Preset Exported", "프리셋 내보내기 완료", "Eksport zakończony"),
                self._text(f"Workflow preset exported successfully.\n(Sensitive credentials excluded)\n{file_path}", f"워크플로우 프리셋이 안전하게 내보내졌습니다.\n(민감 인증정보 자동 제외)\n{file_path}", f"Profil wyeksportowany pomyślnie.\n(Dane uwierzytelniające wykluczone)\n{file_path}"),
            )
        except Exception as e:
            logger.exception("Failed to export preset")
            QMessageBox.critical(
                self,
                self._text("Export Error", "내보내기 오류", "Błąd eksportu"),
                str(e),
            )

    def import_preset(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self._text("Import Workflow Preset", "워크플로우 프리셋 가져오기", "Importuj profil przepływu pracy"),
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return
        try:
            settings = load_workflow_preset(file_path)
            count = apply_workflow_preset(self.config_manager, settings)
            self.log(self._text(f"✓ Preset loaded ({count} settings applied): {file_path}", f"✓ 프리셋 로드 완료 ({count}개 설정 적용됨): {file_path}", f"✓ Załadowano profil ({count} ustawień): {file_path}"))
            self.refresh_readiness()
            self.refresh_schedule_summary()
            main_win = self.window()
            if main_win and hasattr(main_win, "load_all_settings"):
                main_win.load_all_settings()
            QMessageBox.information(
                self,
                self._text("Preset Imported", "프리셋 가져오기 완료", "Import zakończony"),
                self._text(f"Successfully applied {count} settings from preset.\n{file_path}", f"프리셋에서 {count}개 설정을 성공적으로 불러왔습니다.\n{file_path}", f"Pomyślnie załadowano {count} ustawień z profilu.\n{file_path}"),
            )
        except Exception as e:
            logger.exception("Failed to import preset")
            QMessageBox.critical(
                self,
                self._text("Import Error", "가져오기 오류", "Błąd importu"),
                str(e),
            )
