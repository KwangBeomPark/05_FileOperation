import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QProgressBar, QMessageBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QBrush

from src.core.eml_converter import EMLConverter
from src.core.task_contracts import EmlRunConfig, EmlTaskConfig, TaskValidationError
from src.ui.eml_task_dialog import EMLTaskDialog
from src.ui.toast_notification import show_toast
from src.ui.i18n import choose, get_app_language, tr
from src.ui.workflow_widget import WorkflowWidget
from src.utils.logger import get_logger

logger = get_logger()

class EMLWorker(QThread):
    progress = pyqtSignal(int, int)  # current, total files in current task
    log_signal = pyqtSignal(str)
    task_status_changed = pyqtSignal(int, str)  # task_index, status_text
    finished = pyqtSignal(bool, str)
    
    def __init__(self, tasks, eml_converter, width=1024, language="en"):
        super().__init__()
        self.tasks = tasks  # list of dict [{"name": "", "source_folder": "", "target_folder": ""}]
        self.eml_converter = eml_converter
        self.width = width
        self.is_running = True
        self.language = language

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def _msg(self, key, **values):
        return tr(key, self.language, **values)
        
    def stop(self):
        self.is_running = False
        self.eml_converter.cancel()
        
    def run(self):
        self.eml_converter.is_cancelled = False
        success_tasks = 0
        total_tasks = len(self.tasks)
        
        if total_tasks == 0:
            self.finished.emit(False, self._msg("eml_no_tasks"))
            return
            
        self.log_signal.emit(self._msg("eml_worker_starting", tasks=total_tasks, width=self.width))
        
        for task_idx, task in enumerate(self.tasks):
            if not self.is_running:
                self.task_status_changed.emit(task_idx, self._msg("eml_cancelled"))
                self.log_signal.emit(self._msg("eml_task_cancelled_log", name=task["name"]))
                continue
                
            self.task_status_changed.emit(task_idx, self._msg("eml_running"))
            self.log_signal.emit(self._msg("eml_task_starting_log", current=task_idx + 1, total=total_tasks, name=task["name"]))
            
            src = task.get("source_folder", "")
            tgt = task.get("target_folder", "")
            
            if not src or not os.path.exists(src):
                self.task_status_changed.emit(task_idx, self._msg("eml_failed_source_missing"))
                self.log_signal.emit(self._msg("eml_source_missing_log", path=src))
                continue
                
            try:
                eml_files = [
                    os.path.join(src, f)
                    for f in os.listdir(src)
                    if f.lower().endswith('.eml')
                ]
            except Exception as e:
                self.task_status_changed.emit(task_idx, self._msg("eml_failed_folder_read"))
                self.log_signal.emit(self._msg("eml_folder_read_log", detail=e))
                continue
                
            total_files = len(eml_files)
            if total_files == 0:
                self.task_status_changed.emit(task_idx, self._msg("eml_failed_no_files"))
                self.log_signal.emit(self._msg("eml_no_files_log"))
                continue
                
            self.log_signal.emit(self._msg("eml_files_to_convert_log", count=total_files))
            
            # 저장 대상 폴더 자동 생성 시도
            try:
                os.makedirs(tgt, exist_ok=True)
            except Exception as e:
                self.task_status_changed.emit(task_idx, self._msg("eml_failed_output_folder"))
                self.log_signal.emit(self._msg("eml_output_folder_log", path=tgt, detail=e))
                continue
                
            task_success_count = 0
            
            for file_idx, eml_path in enumerate(eml_files):
                if not self.is_running:
                    break
                    
                filename = os.path.basename(eml_path)
                self.log_signal.emit(self._msg("eml_converting_file_log", current=file_idx + 1, total=total_files, filename=filename))
                self.progress.emit(file_idx, total_files)
                
                out_png_name = os.path.splitext(filename)[0] + ".png"
                out_png_path = os.path.join(tgt, out_png_name)
                
                try:
                    success = self.eml_converter.convert_eml_to_image(eml_path, out_png_path, width=self.width)
                    if success:
                        task_success_count += 1
                        self.log_signal.emit(self._msg("eml_saved_log", filename=out_png_name))
                    else:
                        self.log_signal.emit(self._msg("eml_conversion_failed_log", filename=filename))
                except Exception as file_err:
                    self.log_signal.emit(self._msg("eml_file_error_log", filename=filename, detail=file_err))
                    
            if not self.is_running:
                self.task_status_changed.emit(task_idx, self._msg("eml_cancelled"))
                break
                
            self.progress.emit(total_files, total_files)
            
            if task_success_count == total_files:
                self.task_status_changed.emit(task_idx, self._msg("common_completed"))
                self.log_signal.emit(self._msg("eml_task_completed_log", success=task_success_count, total=total_files))
                success_tasks += 1
            else:
                status_msg = self._msg("eml_partially_completed", success=task_success_count, total=total_files)
                self.task_status_changed.emit(task_idx, status_msg)
                self.log_signal.emit(self._msg("eml_partial_log", success=task_success_count, total=total_files))
                
        if not self.is_running:
            self.finished.emit(False, self._msg("eml_stopped_by_user"))
        else:
            all_succeeded = success_tasks == total_tasks
            self.finished.emit(
                all_succeeded,
                self._msg("eml_all_finished", success=success_tasks, total=total_tasks)
            )


class EMLTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.eml_converter = EMLConverter(self.config_manager)
        
        self.is_converting = False
        self._ui_locked = False
        self.worker = None
        self.tasks = []
        
        self.init_ui()
        self.load_saved_tasks()
        self.setAcceptDrops(True)

    @property
    def language(self):
        return get_app_language(self.config_manager)

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def _msg(self, key, **values):
        return tr(key, self.language, **values)

    def refresh_language(self):
        self.workflow_widget.set_step_texts([
            self._t("1. Add Tasks", "1. 작업 등록", "1. Dodaj zadania"),
            self._t("2. Run Conversion", "2. 변환 실행", "2. Uruchom konwersję"),
            self._t("3. Review Results", "3. 결과 확인", "3. Sprawdź wyniki"),
        ])
        self._refresh_action_state()
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.workflow_widget = WorkflowWidget(steps=["1. Add Tasks", "2. Run Conversion", "3. Review Results"])
        layout.addWidget(self.workflow_widget)
        
        # 1. EML 배치 태스크 관리 테이블 그룹
        tasks_group = QGroupBox("EML 변환 배치 태스크 관리")
        tasks_layout = QVBoxLayout()
        tasks_group.setLayout(tasks_layout)
        
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(4)
        self.table_widget.setHorizontalHeaderLabels(["태스크명", "EML 소스 폴더", "이미지 저장 폴더", "진행 상태"])
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_widget.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.doubleClicked.connect(self.edit_selected_task)
        self.table_widget.itemSelectionChanged.connect(self._refresh_action_state)
        
        # 안내 문구 (드래그 앤 드롭 지원 안내)
        help_label = QLabel("※ 폴더를 테이블 위로 드래그 앤 드롭하면 소스 경로가 입력된 채로 태스크를 즉시 추가할 수 있습니다.")
        help_label.setStyleSheet("color: #8a949e; font-size: 8.5pt; margin-bottom: 2px;")
        
        tasks_layout.addWidget(help_label)
        tasks_layout.addWidget(self.table_widget)
        
        # 태스크 편집 버튼 레이아웃
        edit_btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("태스크 추가")
        self.add_btn.clicked.connect(self.add_task)
        
        self.edit_btn = QPushButton("태스크 수정")
        self.edit_btn.clicked.connect(self.edit_selected_task)
        
        self.delete_btn = QPushButton("태스크 삭제")
        self.delete_btn.clicked.connect(self.delete_selected_task)
        
        edit_btn_layout.addWidget(self.add_btn)
        edit_btn_layout.addWidget(self.edit_btn)
        edit_btn_layout.addWidget(self.delete_btn)
        tasks_layout.addLayout(edit_btn_layout)
        
        layout.addWidget(tasks_group)
        
        # 2. 실행 제어 버튼 그룹
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("일괄 변환 시작")
        self.start_btn.setProperty("variant", "success")
        self.start_btn.clicked.connect(self.start_conversion)
        
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_conversion)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)
        
        # 3. 진행 정보 표시 영역
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("대기 중")
        layout.addWidget(self.status_label)
        
        # 4. 상세 로그 출력창
        log_group = QGroupBox("상세 진행 로그")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("font-family: Consolas, monospace; font-size: 9pt; background-color: #1e1e1e; color: #e2e8f0; border: 1px solid #3e3e3e;")
        log_layout.addWidget(self.log_area)
        layout.addWidget(log_group)
        self._refresh_action_state()
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            folder_path = os.path.normpath(url.toLocalFile())
            if os.path.isdir(folder_path):
                self.log(self._msg("eml_folder_dropped", path=folder_path))
                # 소스 폴더가 입력된 추가 다이얼로그 팝업
                existing_names = [t["name"] for t in self.tasks]
                folder_name = os.path.basename(folder_path)
                default_name = self._msg("eml_generated_task_name", folder=folder_name)
                
                dialog = EMLTaskDialog(
                    self, 
                    task_name=default_name, 
                    source_folder=folder_path, 
                    target_folder=folder_path,
                    existing_names=existing_names,
                    language=self.language,
                )
                if dialog.exec():
                    task_data = dialog.get_data()
                    self.tasks.append(task_data)
                    self.save_tasks()
                    self.update_table_view()
                    show_toast(self, self._msg("eml_task_added_success"), "success")
                break
                
    def load_saved_tasks(self):
        saved = self.config_manager.get("eml_tasks", [])
        if saved:
            self.tasks = saved
        else:
            # 하위 호환 마이그레이션 로직
            old_dir = self.config_manager.get("last_eml_directory", "")
            if old_dir and os.path.isdir(old_dir):
                self.tasks = [{
                    "name": self._msg("eml_default_task"),
                    "source_folder": old_dir,
                    "target_folder": old_dir
                }]
                self.config_manager.set("eml_tasks", self.tasks)
                self.log(self._msg("eml_migrated_setting"))
        self.update_table_view()
        
    def save_tasks(self):
        self.config_manager.set("eml_tasks", self.tasks)
        
    def update_table_view(self):
        self.table_widget.setRowCount(0)
        for idx, task in enumerate(self.tasks):
            self.table_widget.insertRow(idx)
            self.table_widget.setItem(idx, 0, QTableWidgetItem(task.get("name", "")))
            self.table_widget.setItem(idx, 1, QTableWidgetItem(task.get("source_folder", "")))
            self.table_widget.setItem(idx, 2, QTableWidgetItem(task.get("target_folder", "")))
            
            status_item = QTableWidgetItem(self._msg("common_waiting"))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_widget.setItem(idx, 3, status_item)
        self._refresh_action_state()

    def _refresh_action_state(self):
        has_tasks = bool(self.tasks)
        has_selection = self.table_widget.currentRow() >= 0
        available = not self.is_converting and not self._ui_locked
        self.add_btn.setEnabled(available)
        self.edit_btn.setEnabled(available and has_selection)
        self.delete_btn.setEnabled(available and has_selection)
        self.start_btn.setEnabled(available and has_tasks)
        if has_tasks:
            self.start_btn.setToolTip(self._t("Ready to convert the registered tasks.", "등록된 작업을 변환할 준비가 되었습니다.", "Gotowe do konwersji zarejestrowanych zadań."))
            if not self.is_converting:
                self.workflow_widget.set_active_step(1)
        else:
            self.start_btn.setToolTip(self._t("Step 1: add at least one EML task.", "1단계: EML 작업을 하나 이상 등록하세요.", "Krok 1: dodaj co najmniej jedno zadanie EML."))
            self.workflow_widget.reset()
            
    def get_task_names(self):
        return [t["name"] for t in self.tasks]
        
    def add_task(self):
        dialog = EMLTaskDialog(self, existing_names=self.get_task_names(), language=self.language)
        if dialog.exec():
            task_data = dialog.get_data()
            self.tasks.append(task_data)
            self.save_tasks()
            self.update_table_view()
            show_toast(self, self._msg("eml_task_added"), "success")
            
    def edit_selected_task(self):
        selected_row = self.table_widget.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, self._msg("common_warning"), self._msg("eml_select_task_edit"))
            return
            
        task = self.tasks[selected_row]
        dialog = EMLTaskDialog(
            self, 
            task_name=task.get("name", ""),
            source_folder=task.get("source_folder", ""),
            target_folder=task.get("target_folder", ""),
            existing_names=self.get_task_names(),
            language=self.language,
        )
        if dialog.exec():
            updated_data = dialog.get_data()
            self.tasks[selected_row] = updated_data
            self.save_tasks()
            self.update_table_view()
            show_toast(self, self._msg("eml_task_updated"), "success")
            
    def delete_selected_task(self):
        selected_row = self.table_widget.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, self._msg("common_warning"), self._msg("eml_select_task_delete"))
            return
            
        task_name = self.tasks[selected_row].get("name", self._msg("eml_unknown_task"))
        reply = QMessageBox.question(
            self, 
            self._msg("eml_delete_task_title"),
            self._msg("eml_delete_task_prompt", name=task_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tasks.pop(selected_row)
            self.save_tasks()
            self.update_table_view()
            show_toast(self, self._msg("eml_task_deleted"), "success")
            
    def start_conversion(self):
        if not self.tasks:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("No batch tasks are configured. Add a task first.", "등록된 배치 태스크가 없습니다. 태스크를 추가해 주세요.", "Nie skonfigurowano zadań wsadowych. Najpierw dodaj zadanie."))
            return
            
        width = int(self.config_manager.get("eml_output_width", 1024))
        
        self.is_converting = True
        self.set_ui_locked(True)
        self.workflow_widget.set_active_step(1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.status_label.setText(self._msg("eml_preparing", width=width))
        self.log_area.clear()
        
        # 테이블 내 모든 상태를 '대기 중' 및 흰색으로 초기화
        for r in range(self.table_widget.rowCount()):
            item = self.table_widget.item(r, 3)
            if item:
                item.setText(self._msg("common_waiting"))
            for c in range(self.table_widget.columnCount()):
                cell = self.table_widget.item(r, c)
                if cell:
                    cell.setBackground(QBrush(QColor("#1e1e1e")))
                    cell.setForeground(QBrush(QColor("#e2e8f0")))
                    
        self.worker = EMLWorker(self.tasks, self.eml_converter, width=width, language=self.language)
        self.worker.progress.connect(self.update_progress)
        self.worker.log_signal.connect(self.log)
        self.worker.task_status_changed.connect(self.on_task_status_changed)
        self.worker.finished.connect(self.on_conversion_finished)
        self.worker.start()
        
    def stop_conversion(self):
        if self.worker:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self.status_label.setText(self._msg("eml_requesting_stop"))
            self.log(self._msg("eml_stop_log"))
            
    def stop_all(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            
    def update_progress(self, current, total):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(self._msg("eml_progress_format", percent=percent, current=current, total=total))
        
    def on_task_status_changed(self, task_idx, status):
        # 테이블 상태 열 변경 및 색상 하이라이트
        status_item = self.table_widget.item(task_idx, 3)
        if not status_item:
            status_item = QTableWidgetItem(status)
            self.table_widget.setItem(task_idx, 3, status_item)
        else:
            status_item.setText(status)
            
        # 상태에 따른 로우 색상 매핑 (Dark Mode 고대비 조합)
        bg_color = QColor("#1e1e1e")
        text_color = QColor("#e2e8f0")
        if status == self._msg("eml_running"):
            bg_color = QColor("#4d3e00")  # 어두운 금색
            text_color = QColor("#fef08a")  # 밝은 노랑
            self.status_label.setText(self._msg("eml_running_task", name=self.tasks[task_idx]["name"]))
        elif status == self._msg("common_completed"):
            bg_color = QColor("#14532d")  # 어두운 초록
            text_color = QColor("#bbf7d0")  # 밝은 초록
        elif status.startswith(("실패", "Failed", "Niepowodzenie")):
            bg_color = QColor("#7f1d1d")  # 어두운 빨강
            text_color = QColor("#fecaca")  # 밝은 빨강
        elif status == self._msg("eml_cancelled"):
            bg_color = QColor("#27272a")  # 어두운 회색
            text_color = QColor("#d4d4d8")  # 밝은 회색
            
        for c in range(self.table_widget.columnCount()):
            cell = self.table_widget.item(task_idx, c)
            if cell:
                cell.setBackground(QBrush(bg_color))
                cell.setForeground(QBrush(text_color))
                
    def on_conversion_finished(self, success, message):
        self.is_converting = False
        self.set_ui_locked(False)
        self.status_label.setText(message)
        
        if success:
            self.workflow_widget.complete_all()
            show_toast(self, self._msg("eml_completed_toast"), "success")
            QMessageBox.information(self, self._msg("common_completed"), message)
        else:
            stopped = message == self._msg("eml_stopped_by_user")
            show_toast(self, self._msg("eml_failed_toast", detail=message), "warning" if stopped else "error")
            QMessageBox.warning(self, self._msg("common_notice"), message)
            
    def set_ui_locked(self, locked):
        self._ui_locked = locked
        self.stop_btn.setEnabled(locked)
        if locked:
            self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        else:
            self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._refresh_action_state()
            
    def log(self, message):
        self.log_area.append(message)
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def build_run_config(self):
        if not self.tasks:
            return None
            
        run_tasks = []
        for idx, task in enumerate(self.tasks):
            src = task.get("source_folder", "").strip()
            tgt = task.get("target_folder", "").strip()
            name = task.get("name", f"태스크 {idx+1}")
            
            if not src:
                raise TaskValidationError(
                    f"EML 태스크 '{name}'의 소스 폴더 경로가 입력되지 않았습니다.",
                    message_key="eml_source_folder_empty",
                    values={"name": name},
                )
            if not os.path.exists(src):
                raise TaskValidationError(
                    f"EML 태스크 '{name}'의 소스 폴더가 존재하지 않습니다: {src}",
                    message_key="eml_source_folder_missing",
                    values={"name": name, "path": src},
                )
            if not tgt:
                raise TaskValidationError(
                    f"EML 태스크 '{name}'의 저장 폴더 경로가 입력되지 않았습니다.",
                    message_key="eml_target_folder_empty",
                    values={"name": name},
                )
            run_tasks.append(EmlTaskConfig(name=name, source_folder=src, target_folder=tgt))
                
        width = int(self.config_manager.get("eml_output_width", 1024))
        return EmlRunConfig(tasks=run_tasks, width=width)

    def get_task_info(self):
        config = self.build_run_config()
        return config.to_legacy_dict() if config else None
