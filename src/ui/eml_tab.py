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
from src.ui.i18n import choose, get_app_language
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

    def refresh_language(self):
        if not self.is_converting:
            self.update_table_view()
            self.status_label.setText(self._t("Waiting", "대기 중"))
        
    def stop(self):
        self.is_running = False
        self.eml_converter.cancel()
        
    def run(self):
        self.eml_converter.is_cancelled = False
        success_tasks = 0
        total_tasks = len(self.tasks)
        
        if total_tasks == 0:
            self.finished.emit(False, self._t("There are no EML tasks to convert.", "변환할 EML 태스크가 존재하지 않습니다."))
            return
            
        self.log_signal.emit(self._t(f"Starting {total_tasks} EML conversion tasks. (width: {self.width}px)", f"총 {total_tasks}개의 EML 태스크 변환 작업을 시작합니다. (폭: {self.width}px)"))
        
        for task_idx, task in enumerate(self.tasks):
            if not self.is_running:
                self.task_status_changed.emit(task_idx, self._t("Cancelled", "취소됨"))
                self.log_signal.emit(self._t(f"\nTask [{task['name']}] cancelled", f"\n태스크 [{task['name']}] 취소됨"))
                continue
                
            self.task_status_changed.emit(task_idx, self._t("Running", "진행 중"))
            self.log_signal.emit(self._t(f"\n>>> Starting task [{task_idx+1}/{total_tasks}]: {task['name']}", f"\n>>> 태스크 [{task_idx+1}/{total_tasks}] 시작: {task['name']}"))
            
            src = task.get("source_folder", "")
            tgt = task.get("target_folder", "")
            
            if not src or not os.path.exists(src):
                self.task_status_changed.emit(task_idx, self._t("Failed (source missing)", "실패 (소스 없음)"))
                self.log_signal.emit(self._t(f"   ✗ Error: the source folder is missing or invalid. ({src})", f"   ✗ 오류: 소스 폴더가 존재하지 않거나 유효하지 않습니다. ({src})"))
                continue
                
            try:
                eml_files = [
                    os.path.join(src, f)
                    for f in os.listdir(src)
                    if f.lower().endswith('.eml')
                ]
            except Exception as e:
                self.task_status_changed.emit(task_idx, self._t("Failed (folder read error)", "실패 (폴더 읽기 오류)"))
                self.log_signal.emit(self._t(f"   ✗ Error: could not read the source folder. ({e})", f"   ✗ 오류: 소스 폴더를 읽는 데 실패했습니다. ({e})"))
                continue
                
            total_files = len(eml_files)
            if total_files == 0:
                self.task_status_changed.emit(task_idx, self._t("Failed (no EML files)", "실패 (EML 없음)"))
                self.log_signal.emit(self._t("   ✗ Warning: the source folder contains no EML files.", "   ✗ 경고: 소스 폴더 내에 EML 파일이 없습니다."))
                continue
                
            self.log_signal.emit(self._t(f"   -> Converting {total_files} EML files.", f"   -> {total_files}개의 EML 파일 변환을 진행합니다."))
            
            # 저장 대상 폴더 자동 생성 시도
            try:
                os.makedirs(tgt, exist_ok=True)
            except Exception as e:
                self.task_status_changed.emit(task_idx, self._t("Failed (output folder error)", "실패 (저장폴더 오류)"))
                self.log_signal.emit(self._t(f"   ✗ Error: could not create the output folder. ({tgt}): {e}", f"   ✗ 오류: 저장 대상 폴더를 생성할 수 없습니다. ({tgt}): {e}"))
                continue
                
            task_success_count = 0
            
            for file_idx, eml_path in enumerate(eml_files):
                if not self.is_running:
                    break
                    
                filename = os.path.basename(eml_path)
                self.log_signal.emit(self._t(f"   [{file_idx+1}/{total_files}] Converting: {filename}", f"   [{file_idx+1}/{total_files}] 변환 중: {filename}"))
                self.progress.emit(file_idx, total_files)
                
                out_png_name = os.path.splitext(filename)[0] + ".png"
                out_png_path = os.path.join(tgt, out_png_name)
                
                try:
                    success = self.eml_converter.convert_eml_to_image(eml_path, out_png_path, width=self.width)
                    if success:
                        task_success_count += 1
                        self.log_signal.emit(self._t(f"      ✓ Saved: {out_png_name}", f"      ✓ 저장 완료: {out_png_name}"))
                    else:
                        self.log_signal.emit(self._t(f"      ✗ Conversion failed: {filename}", f"      ✗ 변환 실패: {filename}"))
                except Exception as file_err:
                    self.log_signal.emit(self._t(f"      ✗ Error ({filename}): {file_err}", f"      ✗ 오류 발생 ({filename}): {file_err}"))
                    
            if not self.is_running:
                self.task_status_changed.emit(task_idx, self._t("Cancelled", "취소됨"))
                break
                
            self.progress.emit(total_files, total_files)
            
            if task_success_count == total_files:
                self.task_status_changed.emit(task_idx, self._t("Completed", "완료"))
                self.log_signal.emit(self._t(f"   ✓ Task completed ({task_success_count}/{total_files} successful)", f"   ✓ 태스크 완료 (성공: {task_success_count}/{total_files})"))
                success_tasks += 1
            else:
                status_msg = self._t(f"Partially completed ({task_success_count}/{total_files})", f"부분 완료 ({task_success_count}/{total_files})")
                self.task_status_changed.emit(task_idx, status_msg)
                self.log_signal.emit(self._t(f"   ⚠ Task partially completed ({task_success_count}/{total_files} successful)", f"   ⚠ 태스크 부분 완료 (성공: {task_success_count}/{total_files})"))
                
        if not self.is_running:
            self.finished.emit(False, self._t("The operation was stopped by the user.", "사용자에 의해 전체 작업이 중지되었습니다."))
        else:
            all_succeeded = success_tasks == total_tasks
            self.finished.emit(
                all_succeeded,
                self._t(f"All tasks finished. ({success_tasks}/{total_tasks} successful)", f"전체 태스크 완료! (성공: {success_tasks}/{total_tasks}개 태스크)")
            )


class EMLTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.eml_converter = EMLConverter(self.config_manager)
        
        self.is_converting = False
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
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
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
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            folder_path = os.path.normpath(url.toLocalFile())
            if os.path.isdir(folder_path):
                self.log(self._t(f"Folder dropped: {folder_path}", f"폴더 드롭 감지: {folder_path}"))
                # 소스 폴더가 입력된 추가 다이얼로그 팝업
                existing_names = [t["name"] for t in self.tasks]
                folder_name = os.path.basename(folder_path)
                default_name = self._t(f"{folder_name} EML Conversion", f"{folder_name} EML 변환")
                
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
                    show_toast(self, self._t("Task added successfully.", "태스크가 성공적으로 추가되었습니다."), "success")
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
                    "name": self._t("Default EML Task", "기본 EML 태스크"),
                    "source_folder": old_dir,
                    "target_folder": old_dir
                }]
                self.config_manager.set("eml_tasks", self.tasks)
                self.log(self._t("Migrated the previous EML folder setting to a batch task.", "기존 단일 EML 폴더 설정을 배치 태스크로 마이그레이션했습니다."))
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
            
            status_item = QTableWidgetItem(self._t("Waiting", "대기 중"))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_widget.setItem(idx, 3, status_item)
            
    def get_task_names(self):
        return [t["name"] for t in self.tasks]
        
    def add_task(self):
        dialog = EMLTaskDialog(self, existing_names=self.get_task_names(), language=self.language)
        if dialog.exec():
            task_data = dialog.get_data()
            self.tasks.append(task_data)
            self.save_tasks()
            self.update_table_view()
            show_toast(self, self._t("Task added.", "태스크 추가 완료"), "success")
            
    def edit_selected_task(self):
        selected_row = self.table_widget.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, self._t("Warning", "경고"), self._t("Select a task to edit.", "수정할 태스크를 목록에서 먼저 선택해 주세요."))
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
            show_toast(self, self._t("Task updated.", "태스크 수정 완료"), "success")
            
    def delete_selected_task(self):
        selected_row = self.table_widget.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, self._t("Warning", "경고"), self._t("Select a task to delete.", "삭제할 태스크를 목록에서 먼저 선택해 주세요."))
            return
            
        task_name = self.tasks[selected_row].get("name", self._t("Unknown Task", "알 수 없는 태스크"))
        reply = QMessageBox.question(
            self, 
            self._t("Delete Task", "태스크 삭제"),
            self._t(f"Delete the '{task_name}' task?", f"정말로 '{task_name}' 태스크를 삭제하시겠습니까?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tasks.pop(selected_row)
            self.save_tasks()
            self.update_table_view()
            show_toast(self, self._t("Task deleted.", "태스크 삭제 완료"), "success")
            
    def start_conversion(self):
        if not self.tasks:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("No batch tasks are configured. Add a task first.", "등록된 배치 태스크가 없습니다. 태스크를 추가해 주세요.", "Nie skonfigurowano zadań wsadowych. Najpierw dodaj zadanie."))
            return
            
        width = int(self.config_manager.get("eml_output_width", 1024))
        
        self.is_converting = True
        self.set_ui_locked(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.status_label.setText(self._t(f"Preparing batch conversion... (width: {width}px)", f"배치 변환 실행 준비 중... (DPI 폭: {width}px)"))
        self.log_area.clear()
        
        # 테이블 내 모든 상태를 '대기 중' 및 흰색으로 초기화
        for r in range(self.table_widget.rowCount()):
            item = self.table_widget.item(r, 3)
            if item:
                item.setText(self._t("Waiting", "대기 중"))
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
            self.status_label.setText(self._t("Requesting stop...", "중지 요청 처리 중..."))
            self.log(self._t("\nStop requested. Finishing safely...", "\n사용자에 의해 작업 중지가 요청되었습니다. 안전하게 종료하는 중..."))
            
    def stop_all(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            
    def update_progress(self, current, total):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(self._t(f"{percent}% ({current}/{total} files)", f"{percent}% ({current}/{total} 파일)"))
        
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
        if status in ("진행 중", "Running"):
            bg_color = QColor("#4d3e00")  # 어두운 금색
            text_color = QColor("#fef08a")  # 밝은 노랑
            self.status_label.setText(self._t(f"Running task: {self.tasks[task_idx]['name']}", f"태스크 진행 중: {self.tasks[task_idx]['name']}"))
        elif status in ("완료", "Completed"):
            bg_color = QColor("#14532d")  # 어두운 초록
            text_color = QColor("#bbf7d0")  # 밝은 초록
        elif status.startswith("실패") or status.startswith("Failed"):
            bg_color = QColor("#7f1d1d")  # 어두운 빨강
            text_color = QColor("#fecaca")  # 밝은 빨강
        elif status in ("취소됨", "Cancelled"):
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
            show_toast(self, self._t("EML batch conversion completed.", "EML 배치 변환 성공!"), "success")
            QMessageBox.information(self, self._t("Completed", "완료"), message)
        else:
            stopped = "중지" in message or "stopped" in message.lower()
            show_toast(self, self._t(f"EML conversion stopped/failed: {message}", f"EML 배치 변환 중지/실패: {message}"), "warning" if stopped else "error")
            QMessageBox.warning(self, self._t("Notice", "알림"), message)
            
    def set_ui_locked(self, locked):
        self.add_btn.setEnabled(not locked)
        self.edit_btn.setEnabled(not locked)
        self.delete_btn.setEnabled(not locked)
        self.start_btn.setEnabled(not locked)
        self.stop_btn.setEnabled(locked)
        if locked:
            self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        else:
            self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
            
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
