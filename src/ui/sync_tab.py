import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QProgressBar,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QGroupBox, QHeaderView,
    QComboBox, QInputDialog
)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont

from src.core.sync_manager import SyncManager
from src.core.task_contracts import SyncGroupConfig, SyncRunConfig, TaskValidationError
from src.ui.i18n import choose, get_app_language, tr
from src.ui.toast_notification import show_toast
from src.utils.logger import get_logger

logger = get_logger()

DEFAULT_SYNC_GROUP_NAMES = {
    "Default Sync Group",
    "기본 동기화 그룹",
    "Domyślna grupa synchronizacji",
}

class SyncWorker(QThread):
    progress = pyqtSignal(int, int, str) # current, total, status_msg
    finished = pyqtSignal(bool, int, int, list) # success, success_count, fail_count, errors
    dry_run_finished = pyqtSignal(list) # actions
    
    def __init__(self, sync_groups, config_manager, is_dry_run=True):
        super().__init__()
        self.sync_groups = sync_groups
        self.config_manager = config_manager
        self.is_dry_run = is_dry_run
        self.is_cancelled = False
        self.current_manager = None
        self.language = get_app_language(config_manager)

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)
        
    def stop(self):
        self.is_cancelled = True
        if self.current_manager:
            self.current_manager.cancel()
            
    def run(self):
        try:
            all_actions = []
            move_to_deleted = self.config_manager.get("sync_move_to_deleted", True)
            
            if self.is_dry_run:
                self.progress.emit(0, len(self.sync_groups), self._t("Analyzing all synchronization folders and files...", "동기화 대상 폴더 및 파일 전체 분석 중...", "Analizowanie wszystkich folderów i plików synchronizacji..."))
                for i, group in enumerate(self.sync_groups):
                    if self.is_cancelled:
                        break
                    folders = group.get("folders", [])
                    if len(folders) < 2:
                        continue # 최소 2개 미만 폴더 그룹은 동기화할 수 없으므로 건너뜀
                        
                    self.progress.emit(i, len(self.sync_groups), self._t(f"Analyzing: {group['name']}...", f"분석 중: {group['name']} ...", f"Analizowanie: {group['name']}..."))
                    self.current_manager = SyncManager(folders=folders, move_to_deleted=move_to_deleted)
                    actions = self.current_manager.analyze_sync()
                    
                    # 액션 정보에 그룹명 추가 (테이블 표시용)
                    for act in actions:
                        act["group_name"] = group["name"]
                    
                    all_actions.extend(actions)
                    
                self.progress.emit(len(self.sync_groups), len(self.sync_groups), self._t("Analysis completed.", "전체 분석 완료.", "Analiza zakończona."))
                self.dry_run_finished.emit(all_actions)
            else:
                total_success = 0
                total_fail = 0
                all_errors = []
                
                # 전체 일괄 동기화 (분석과 실행을 연달아 수행)
                for i, group in enumerate(self.sync_groups):
                    if self.is_cancelled:
                        all_errors.append(self._t("The operation was stopped by the user.", "사용자에 의해 전체 작업이 중단되었습니다.", "Operacja została zatrzymana przez użytkownika."))
                        break
                        
                    folders = group.get("folders", [])
                    if len(folders) < 2:
                        logger.info(f"Skipping group '{group['name']}' (less than 2 folders).")
                        continue
                        
                    self.progress.emit(i, len(self.sync_groups), self._t(f"[{group['name']}] Preparing analysis and synchronization...", f"[{group['name']}] 분석 및 동기화 준비 중...", f"[{group['name']}] Przygotowywanie analizy i synchronizacji..."))
                    
                    self.current_manager = SyncManager(folders=folders, move_to_deleted=move_to_deleted)
                    actions = self.current_manager.analyze_sync()
                    
                    if not actions:
                        continue # 이 그룹은 동기화할 파일이 없음
                        
                    if self.is_cancelled:
                        break
                        
                    group_index = i
                    group_name = group["name"]

                    def callback(
                        current, total, msg,
                        group_index=group_index,
                        group_name=group_name
                    ):
                        # 파일 단위의 진행률 메시지를 그룹 단위 프로그레스와 함께 전달
                        self.progress.emit(
                            group_index,
                            len(self.sync_groups),
                            f"[{group_name}] {msg}"
                        )
                        
                    s_count, f_count, errs = self.current_manager.execute_sync(actions, progress_callback=callback)
                    total_success += s_count
                    total_fail += f_count
                    if errs:
                        all_errors.extend([f"[{group['name']}] {e}" for e in errs])
                        
                # 마지막 진행도 100%
                if not self.is_cancelled:
                    self.progress.emit(len(self.sync_groups), len(self.sync_groups), self._t("All synchronization groups completed.", "전체 동기화 완료.", "Zakończono wszystkie grupy synchronizacji."))
                    
                self.finished.emit(
                    not self.is_cancelled and total_fail == 0,
                    total_success,
                    total_fail,
                    all_errors
                )
        except Exception as e:
            logger.error(f"Error in SyncWorker thread: {e}")
            self.finished.emit(False, 0, 1, [str(e)])

class SyncTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        
        self.sync_groups = [] # [{"name": str, "folders": list}]
        self.current_group_idx = -1
        self.is_running = False
        self.worker = None
        
        self.init_ui()
        self.load_saved_data()
        self.setAcceptDrops(True)

    @property
    def language(self):
        return get_app_language(self.config_manager)

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def _msg(self, key, **values):
        return tr(key, self.language, **values)

    def _sync_text(self, value):
        if self.language == "ko" or not isinstance(value, str):
            return value
        replacements = {
            "신규 복사": self._t("New copy", "신규 복사", "Nowa kopia"),
            "최신 업데이트": self._t("Update to latest", "최신 업데이트", "Aktualizacja do najnowszej wersji"),
            "구버전 정리": self._t("Archive older version", "구버전 정리", "Archiwizacja starszej wersji"),
            "동시 수정 충돌": self._t("Concurrent modification conflict", "동시 수정 충돌", "Konflikt równoczesnych zmian"),
            "충돌 보존 백업": self._t("Preserve conflict backup", "충돌 보존 백업", "Kopia zapasowa konfliktu"),
            "충돌 백업 후 최신 업데이트": self._t("Back up conflict, then update", "충돌 백업 후 최신 업데이트", "Kopia konfliktu, następnie aktualizacja"),
            "to_be_deleted이동": self._t("Move to 'to be deleted'", "to_be_deleted이동", "Przenieś do 'to be deleted'"),
            "복사": self._t("Copy", "복사", "Kopiowanie"),
            "사용자에 의해 작업이 중단되었습니다.": self._t("The operation was stopped by the user.", "사용자에 의해 작업이 중단되었습니다.", "Operacja została zatrzymana przez użytkownika."),
            "동기화 완료": self._t("Synchronization completed", "동기화 완료", "Synchronizacja zakończona"),
            "처리 중": self._t("Processing", "처리 중", "Przetwarzanie"),
        }
        translated = value
        for korean, english in replacements.items():
            translated = translated.replace(korean, english)
        return translated

    def _display_group_name(self, stored_name):
        if stored_name in DEFAULT_SYNC_GROUP_NAMES:
            return self._t("Default Sync Group", "기본 동기화 그룹", "Domyślna grupa synchronizacji")
        return stored_name

    def refresh_language(self):
        for index, group in enumerate(self.sync_groups):
            self.group_combo.setItemText(index, self._display_group_name(group.get("name", "")))
        self.refresh_folder_list()
        if not self.is_running:
            count = self.table_widget.rowCount()
            self.plan_summary_label.setText(
                self._t(f"Analysis ready: {count} actions", f"분석 결과: {count}건", f"Analiza gotowa: {count} operacji")
                if count
                else self._t("Not analyzed", "분석 전", "Nie przeanalizowano")
            )
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 2)
            if item:
                item.setText(self._sync_text(item.text()))
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 1. 동기화 그룹 설정 영역
        group_groupbox = QGroupBox("Sync Groups (동기화 그룹 관리)")
        group_layout = QVBoxLayout()
        group_groupbox.setLayout(group_layout)
        
        group_h_layout = QHBoxLayout()
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self.on_group_changed)
        
        add_group_btn = QPushButton("새 그룹 추가")
        add_group_btn.clicked.connect(self.add_group)
        rename_group_btn = QPushButton("이름 변경")
        rename_group_btn.clicked.connect(self.rename_group)
        del_group_btn = QPushButton("그룹 삭제")
        del_group_btn.clicked.connect(self.delete_group)
        
        group_h_layout.addWidget(QLabel("선택된 그룹:"))
        group_h_layout.addWidget(self.group_combo, 1)
        group_h_layout.addWidget(add_group_btn)
        group_h_layout.addWidget(rename_group_btn)
        group_h_layout.addWidget(del_group_btn)
        
        group_layout.addLayout(group_h_layout)
        layout.addWidget(group_groupbox)
        
        # 2. 동기화 폴더 설정 영역
        folder_group = QGroupBox("Synchronizing Directories (선택된 그룹의 폴더)")
        folder_layout = QVBoxLayout()
        folder_group.setLayout(folder_layout)
        
        self.folder_list_widget = QListWidget()
        folder_layout.addWidget(self.folder_list_widget)
        self.folder_summary_label = QLabel("등록 폴더: 0개")
        folder_layout.addWidget(self.folder_summary_label)
        
        btn_layout = QHBoxLayout()
        add_folder_btn = QPushButton("폴더 추가")
        add_folder_btn.clicked.connect(self.add_folder)
        remove_folder_btn = QPushButton("폴더 제거")
        remove_folder_btn.clicked.connect(self.remove_folder)
        clear_folders_btn = QPushButton("현재 그룹 초기화")
        clear_folders_btn.clicked.connect(self.clear_folders)
        
        btn_layout.addWidget(add_folder_btn)
        btn_layout.addWidget(remove_folder_btn)
        btn_layout.addWidget(clear_folders_btn)
        folder_layout.addLayout(btn_layout)
        
        layout.addWidget(folder_group, 2)
        
        # 3. 분석 및 실행 제어 영역
        control_group = QGroupBox("Sync Control Panel")
        control_layout = QVBoxLayout()
        control_group.setLayout(control_layout)
        
        btn_h_layout = QHBoxLayout()
        self.analyze_btn = QPushButton("1. 전체 동기화 분석 (Dry Run)")
        self.analyze_btn.setProperty("variant", "primary")
        self.analyze_btn.clicked.connect(self.start_dry_run)
        
        self.sync_btn = QPushButton("2. 전체 일괄 동기화 (Sync ALL)")
        self.sync_btn.setProperty("variant", "success")
        self.sync_btn.clicked.connect(self.start_sync_execution)
        
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_sync)
        
        btn_h_layout.addWidget(self.analyze_btn)
        btn_h_layout.addWidget(self.sync_btn)
        btn_h_layout.addWidget(self.stop_btn)
        control_layout.addLayout(btn_h_layout)
        
        self.progress_bar = QProgressBar()
        control_layout.addWidget(self.progress_bar)
        self.plan_summary_label = QLabel("분석 전")
        control_layout.addWidget(self.plan_summary_label)
        
        layout.addWidget(control_group, 1)
        
        # 4. Dry Run 시각화 테이블
        table_group = QGroupBox("Dry Run Sync Plan (전체 작업 계획 리스트)")
        table_layout = QVBoxLayout()
        table_group.setLayout(table_layout)
        
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(6)
        self.table_widget.setHorizontalHeaderLabels(["그룹명", "파일명", "동기화 액션", "원본 폴더", "대상 폴더", "비고"])
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        table_layout.addWidget(self.table_widget)
        layout.addWidget(table_group, 3)

    def set_ui_enabled(self, enabled):
        """실행 중 UI 잠금을 위한 유틸리티"""
        self.group_combo.setEnabled(enabled)
        for btn in self.findChildren(QPushButton):
            if btn not in (self.stop_btn,):
                btn.setEnabled(enabled)

    # --- 데이터 & 설정 마이그레이션 ---
    def load_saved_data(self):
        # 마이그레이션 로직: sync_folders가 있고 sync_groups가 없으면 이전
        old_folders = self.config_manager.get("sync_folders", None)
        saved_groups = self.config_manager.get("sync_groups", None)
        
        if saved_groups is not None:
            self.sync_groups = saved_groups
        elif old_folders is not None:
            # 하위 호환성 마이그레이션
            self.sync_groups = [{"name": "Default Sync Group", "folders": old_folders}]
            self.config_manager.set("sync_groups", self.sync_groups)
        else:
            self.sync_groups = [{"name": "Default Sync Group", "folders": []}]
            
        if not self.sync_groups: # 만약 비어있다면 최소 1개 보장
            self.sync_groups = [{"name": "Default Sync Group", "folders": []}]
            
        # 콤보박스 채우기
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        for group in self.sync_groups:
            self.group_combo.addItem(self._display_group_name(group["name"]))
        self.group_combo.blockSignals(False)
        
        # 마지막 선택 인덱스 복원
        last_idx = self.config_manager.get("sync_last_group_index", 0)
        if 0 <= last_idx < len(self.sync_groups):
            self.group_combo.setCurrentIndex(last_idx)
        else:
            self.group_combo.setCurrentIndex(0)
            
        self.on_group_changed(self.group_combo.currentIndex())

    def save_data(self):
        self.config_manager.set("sync_groups", self.sync_groups)
        self.config_manager.set("sync_last_group_index", self.current_group_idx)

    # --- 그룹 관리 로직 ---
    def on_group_changed(self, idx):
        if idx < 0 or idx >= len(self.sync_groups):
            return
        self.current_group_idx = idx
        self.refresh_folder_list()
        self.save_data()
        
    def add_group(self):
        text, ok = QInputDialog.getText(self, self._msg("sync_add_group_title"), self._msg("sync_add_group_prompt"))
        if ok and text:
            text = text.strip()
            if not text:
                return
            if any(g["name"] == text for g in self.sync_groups):
                QMessageBox.warning(self, self._msg("common_warning"), self._msg("sync_duplicate_group"))
                return
                
            self.sync_groups.append({"name": text, "folders": []})
            self.group_combo.addItem(text)
            self.group_combo.setCurrentIndex(len(self.sync_groups) - 1)
            self.save_data()
            
    def rename_group(self):
        if self.current_group_idx < 0:
            return
            
        old_name = self.sync_groups[self.current_group_idx]["name"]
        text, ok = QInputDialog.getText(self, self._msg("sync_rename_group_title"), self._msg("sync_rename_group_prompt"), text=old_name)
        if ok and text:
            text = text.strip()
            if not text or text == old_name:
                return
            if any(g["name"] == text for g in self.sync_groups):
                QMessageBox.warning(self, self._msg("common_warning"), self._msg("sync_duplicate_group"))
                return
                
            self.sync_groups[self.current_group_idx]["name"] = text
            self.group_combo.setItemText(self.current_group_idx, text)
            self.save_data()
            
    def delete_group(self):
        if self.current_group_idx < 0:
            return
            
        group_name = self.sync_groups[self.current_group_idx]["name"]
        reply = QMessageBox.question(self, self._msg("sync_delete_group_title"), self._msg("sync_delete_group_prompt", name=group_name), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            del self.sync_groups[self.current_group_idx]
            self.group_combo.removeItem(self.current_group_idx)
            
            if not self.sync_groups:
                # 마지막 그룹이 지워지면 기본 그룹 1개 강제 생성
                default_name = "Default Sync Group"
                self.sync_groups.append({"name": default_name, "folders": []})
                self.group_combo.addItem(self._display_group_name(default_name))
                
            self.save_data()
            self.group_combo.setCurrentIndex(0) # 첫번째로 이동

    # --- 폴더 관리 로직 ---
    def dragEnterEvent(self, event):
        if not self.is_running and event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = os.path.normpath(url.toLocalFile())
            if os.path.isdir(path):
                self.add_folder_to_current_group(path)
                
    def refresh_folder_list(self):
        self.folder_list_widget.clear()
        if self.current_group_idx >= 0:
            folders = self.sync_groups[self.current_group_idx].get("folders", [])
            for folder in folders:
                self.folder_list_widget.addItem(folder)
            folder_count = len(folders)
            self.folder_summary_label.setText(self._t(f"Folders: {folder_count}", f"등록 폴더: {folder_count}개", f"Foldery: {folder_count}"))
            
    def add_folder_to_current_group(self, folder_path):
        if self.current_group_idx < 0:
            return
            
        normalized = os.path.normpath(folder_path)
        folders = self.sync_groups[self.current_group_idx].setdefault("folders", [])
        
        if normalized not in folders and os.path.isdir(normalized):
            folders.append(normalized)
            self.save_data()
            self.refresh_folder_list()
            self.table_widget.setRowCount(0) # 플랜 초기화
            self.plan_summary_label.setText(self._t("Not analyzed (folders changed)", "분석 전 (폴더 변경됨)", "Nie przeanalizowano (zmieniono foldery)"))
            
    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self._msg("sync_add_folder_title"))
        if folder:
            self.add_folder_to_current_group(folder)
            
    def remove_folder(self):
        if self.current_group_idx < 0:
            return
            
        selected_items = self.folder_list_widget.selectedItems()
        if not selected_items:
            return
            
        folders = self.sync_groups[self.current_group_idx].get("folders", [])
        for item in selected_items:
            path = item.text()
            if path in folders:
                folders.remove(path)
                
        self.save_data()
        self.refresh_folder_list()
        self.table_widget.setRowCount(0)
        self.plan_summary_label.setText(self._t("Not analyzed (folders changed)", "분석 전 (폴더 변경됨)", "Nie przeanalizowano (zmieniono foldery)"))
        
    def clear_folders(self):
        if self.current_group_idx < 0:
            return
            
        self.sync_groups[self.current_group_idx]["folders"] = []
        self.save_data()
        self.refresh_folder_list()
        self.table_widget.setRowCount(0)
        self.plan_summary_label.setText(self._t("Not analyzed", "분석 전", "Nie przeanalizowano"))

    # --- 분석 및 실행 로직 ---
    def start_dry_run(self):
        # 폴더가 2개 이상인 그룹이 하나라도 있는지 확인
        valid_groups = [g for g in self.sync_groups if len(g.get("folders", [])) >= 2]
        if not valid_groups:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("No group contains at least two folders.\nAdd folders before analyzing.", "최소 2개 이상의 폴더가 등록된 그룹이 하나도 없습니다.\n폴더를 추가해주세요.", "Żadna grupa nie zawiera co najmniej dwóch folderów.\nDodaj foldery przed analizą."))
            return
            
        self.is_running = True
        self.set_ui_enabled(False)
        self.stop_btn.setEnabled(True)
        self.table_widget.setRowCount(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.plan_summary_label.setText(self._t("Analyzing all groups...", "전체 그룹 분석 중...", "Analizowanie wszystkich grup..."))
        
        self.worker = SyncWorker(self.sync_groups, self.config_manager, is_dry_run=True)
        self.worker.progress.connect(self.update_progress)
        self.worker.dry_run_finished.connect(self.on_dry_run_finished)
        self.worker.start()
        
    def on_dry_run_finished(self, actions):
        self.is_running = False
        self.set_ui_enabled(True)
        self.stop_btn.setEnabled(False)
        
        self.table_widget.setRowCount(len(actions))
        
        for row_idx, act in enumerate(actions):
            group_item = QTableWidgetItem(act.get("group_name", ""))
            filename_item = QTableWidgetItem(act["filename"])
            action_item = QTableWidgetItem(self._sync_text(act["action"]))
            src_item = QTableWidgetItem(os.path.basename(act["source_folder"]))
            src_item.setToolTip(act["source_folder"])
            tgt_item = QTableWidgetItem(os.path.basename(act["target_folder"]))
            tgt_item.setToolTip(act["target_folder"])
            
            if act.get("mtime"):
                mtime_str = datetime.fromtimestamp(act["mtime"]).strftime("%Y-%m-%d %H:%M")
            else:
                mtime_str = self._sync_text(act.get("details", ""))
            details_item = QTableWidgetItem(mtime_str)
            
            bold_font = QFont()
            bold_font.setBold(True)
            action_item.setFont(bold_font)
            
            # Action styling (Dark Mode 고대비 조합)
            if act["action"] == "복사":
                action_item.setForeground(QBrush(QColor("#90caf9")))
                action_item.setBackground(QBrush(QColor("#172554")))
            elif act["action"] == "to_be_deleted이동":
                action_item.setForeground(QBrush(QColor("#ef9a9a")))
                action_item.setBackground(QBrush(QColor("#450a0a")))
            elif act["action"] == "충돌 보존 백업":
                action_item.setForeground(QBrush(QColor("#ffcc80")))
                action_item.setBackground(QBrush(QColor("#7c2d12")))
                
            self.table_widget.setItem(row_idx, 0, group_item)
            self.table_widget.setItem(row_idx, 1, filename_item)
            self.table_widget.setItem(row_idx, 2, action_item)
            self.table_widget.setItem(row_idx, 3, src_item)
            self.table_widget.setItem(row_idx, 4, tgt_item)
            self.table_widget.setItem(row_idx, 5, details_item)
            
        if actions:
            action_count = len(actions)
            self.plan_summary_label.setText(self._t(f"Analysis result: {action_count} actions planned", f"분석 결과: 전체 실행 예정 {action_count}건", f"Wynik analizy: zaplanowano {action_count} operacji"))
            show_toast(self, self._t(f"Analysis complete: {action_count} actions planned", f"분석 완료! 총 {action_count}건 예정", f"Analiza zakończona: zaplanowano {action_count} operacji"), "info")
        else:
            self.plan_summary_label.setText(self._t("Analysis result: nothing to do", "분석 결과: 실행할 작업 없음", "Wynik analizy: brak operacji"))
            show_toast(self, self._t("Analysis complete: folders are already synchronized.", "분석 완료: 동기화할 내역이 없습니다.", "Analiza zakończona: foldery są już zsynchronizowane."), "success")
            QMessageBox.information(self, self._t("Information", "정보", "Informacja"), self._t("All group folders are already synchronized.", "모든 그룹의 파일들이 이미 최신 동기화 상태입니다.", "Wszystkie foldery grup są już zsynchronizowane."))
            
    def start_sync_execution(self):
        valid_groups = [g for g in self.sync_groups if len(g.get("folders", [])) >= 2]
        if not valid_groups:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("No group contains at least two folders.", "최소 2개 이상의 폴더가 등록된 그룹이 하나도 없습니다.", "Żadna grupa nie zawiera co najmniej dwóch folderów."))
            return
            
        reply = QMessageBox.question(
            self,
            self._msg("sync_run_title"),
            self._msg("sync_run_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        self.is_running = True
        self.set_ui_enabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.plan_summary_label.setText(self._msg("sync_running"))
        
        self.worker = SyncWorker(self.sync_groups, self.config_manager, is_dry_run=False)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_sync_finished)
        self.worker.start()
        
    def stop_sync(self):
        if self.worker:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self.plan_summary_label.setText(self._msg("sync_stopping"))
            logger.info("전체 동기화 중지 요청 전달됨")
            
    def stop_all(self):
        """MainWindow 종료 시 연동될 안전 취소 헬퍼"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            
    def update_progress(self, current, total, status_msg):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}% ({current}/{total})")
        if parent_win := self.window():
            if hasattr(parent_win, 'status_bar'):
                parent_win.status_bar.showMessage(self._sync_text(status_msg))

    def on_sync_finished(self, success, success_count, fail_count, errors):
        self.is_running = False
        self.set_ui_enabled(True)
        self.stop_btn.setEnabled(False)
        self.table_widget.setRowCount(0) # 작업이 끝났으므로 비움
        
        if success:
            if fail_count == 0:
                self.plan_summary_label.setText(self._msg("sync_completed_summary", success=success_count))
                show_toast(self, self._msg("sync_completed_toast"), "success")
                QMessageBox.information(self, self._msg("common_completed"), self._msg("sync_completed_dialog", success=success_count))
            else:
                self.plan_summary_label.setText(self._msg("sync_partial_summary", success=success_count, failed=fail_count))
                show_toast(self, self._msg("sync_partial_toast", success=success_count, failed=fail_count), "warning")
                err_text = "\n".join(self._sync_text(error) for error in errors[:10])
                if len(errors) > 10:
                    err_text += self._msg("sync_more_errors")
                QMessageBox.warning(self, self._msg("common_warning"), self._msg("sync_partial_dialog", success=success_count, failed=fail_count, errors=err_text))
        else:
            self.plan_summary_label.setText(self._msg("sync_error_summary"))
            show_toast(self, self._msg("sync_error_toast"), "error")
            QMessageBox.critical(self, self._msg("common_error"), self._msg("sync_fatal_error", errors="\n".join(self._sync_text(error) for error in errors)))

    def build_run_config(self):
        valid_groups = [g for g in self.sync_groups if len(g.get("folders", [])) >= 2]
        if not valid_groups:
            return None
            
        for group in self.sync_groups:
            folders = group.get("folders", [])
            if 0 < len(folders) < 2:
                raise TaskValidationError(
                    f"동기화 그룹 '{group['name']}'에 등록된 폴더가 2개 미만입니다. 최소 2개의 폴더를 등록해야 합니다.",
                    message_key="sync_group_needs_two_folders",
                    values={"name": group["name"]},
                )

        for group in valid_groups:
            name = group.get("name", "이름 없는 그룹")
            folders = [str(folder).strip() for folder in group.get("folders", [])]
            normalized_folders = [os.path.normcase(os.path.abspath(folder)) for folder in folders]
            if len(set(normalized_folders)) != len(normalized_folders):
                raise TaskValidationError(
                    f"동기화 그룹 '{name}'에 동일한 폴더가 중복 등록되어 있습니다.",
                    message_key="sync_group_duplicate_folder",
                    values={"name": name},
                )
            for folder in folders:
                if not os.path.isdir(folder):
                    raise TaskValidationError(
                        f"동기화 그룹 '{name}'의 폴더가 존재하지 않거나 폴더가 아닙니다: {folder}",
                        message_key="sync_group_folder_missing",
                        values={"name": name, "path": folder},
                    )
                
        move_to_deleted = bool(self.config_manager.get("sync_move_to_deleted", True))
        return SyncRunConfig(
            sync_groups=[
                SyncGroupConfig(
                    name=group.get("name", f"그룹 {idx + 1}"),
                    folders=list(group.get("folders", [])),
                    move_to_deleted=bool(group.get("move_to_deleted", move_to_deleted)),
                )
                for idx, group in enumerate(valid_groups)
            ]
        )

    def get_task_info(self):
        config = self.build_run_config()
        return config.to_legacy_dict() if config else None
        
    def set_ui_locked(self, locked):
        self.set_ui_enabled(not locked)
