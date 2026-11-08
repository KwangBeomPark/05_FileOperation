import copy
import os
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
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

from src.core.sync_manager import SyncManager
from src.core.task_contracts import (
    RunPlan,
    SyncGroupConfig,
    SyncRunConfig,
    TaskStep,
    TaskValidationError,
)
from src.core.task_items import ensure_sync_ids
from src.ui.i18n import (
    choose,
    format_task_schedule_description,
    get_app_language,
    replace_phrases,
    tr,
)
from src.ui.run_summary_dialog import confirm_run_summary
from src.ui.toast_notification import show_toast
from src.ui.version_cleanup_dialog import VersionCleanupDialog
from src.ui.workflow_widget import WorkflowWidget
from src.utils.logger import get_logger

logger = get_logger()

DEFAULT_SYNC_GROUP_NAMES = {
    "Default Sync Group",
    "기본 동기화 그룹",
    "Domyślna grupa synchronizacji",
}

def date_preview_rows(actions):
    """Project a date-family operation into visible copy and archive rows."""
    rows = []
    for action in actions:
        if action["action"] != "날짜 동기화":
            rows.append(action)
            continue
        if not action["existing"]:
            rows.append({**action, "action": "복사"})
        for old in action["old"]:
            if action.get("date_archive_mode") == "trash":
                rows.append({**action, "action": "휴지통이동", "filename": old["filename"], "source_folder": action["target_folder"], "target_folder": "Recycle Bin"})
                continue
            archive_dir = os.path.join(action["target_folder"], action.get("archive_folder_name", "to be deleted"), os.path.dirname(old["filename"]))
            rows.append({**action, "action": "to_be_deleted이동", "filename": old["filename"], "source_folder": action["target_folder"], "target_folder": archive_dir})
    return rows


class SyncWorker(QThread):
    progress = pyqtSignal(int, int, str) # current, total, status_msg
    finished = pyqtSignal(bool, int, int, list) # success, success_count, fail_count, errors
    dry_run_finished = pyqtSignal(list) # actions
    
    def __init__(self, sync_groups, config_manager, is_dry_run=True, approved_actions=None):
        super().__init__()
        self.sync_groups = sync_groups
        self.config_manager = config_manager
        self.is_dry_run = is_dry_run
        self.is_cancelled = False
        self.current_manager = None
        self.language = get_app_language(config_manager)
        self.approved_actions = approved_actions

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)
        
    def stop(self):
        self.is_cancelled = True
        if self.current_manager:
            self.current_manager.cancel()

    def _create_manager(self, group, default_move_to_deleted):
        folders = group.get("folders", [])
        return SyncManager(
            folders=folders,
            move_to_deleted=bool(group.get("move_to_deleted", default_move_to_deleted)),
            archive_folder_name=str(group.get("archive_folder_name", "to be deleted") or "to be deleted"),
            exclude_patterns=list(group.get("exclude_patterns", [])),
            include_subfolders=bool(group.get("include_subfolders", False)),
            sync_mode=str(group.get("sync_mode", "two_way") or "two_way"),
            date_latest_only=bool(group.get("date_latest_only", False)),
            date_archive_mode=str(group.get("date_archive_mode", "folder") or "folder"),
            approved_actions=self.approved_actions,
            group_name=group.get("name", ""),
        )
            
    def run(self):
        try:
            all_actions = []
            move_to_deleted = self.config_manager.get("sync_move_to_deleted", True)
            
            if self.is_dry_run:
                self.progress.emit(0, len(self.sync_groups), self._t("Analyzing all synchronization folders and files...", "동기화 대상 폴더 및 파일 전체 분석 중...", "Analizowanie wszystkich folderów i plików synchronizacji..."))
                for i, group in enumerate(self.sync_groups):
                    if self.is_cancelled:
                        self.finished.emit(False, 0, 1, [self._t("Preview cancelled.", "미리보기가 취소되었습니다.", "Anulowano podgląd.")])
                        return
                    folders = group.get("folders", [])
                    if len(folders) < 2:
                        continue # 최소 2개 미만 폴더 그룹은 동기화할 수 없으므로 건너뜀
                        
                    self.progress.emit(i, len(self.sync_groups), self._t(f"Analyzing: {group['name']}...", f"분석 중: {group['name']} ...", f"Analizowanie: {group['name']}..."))
                    self.current_manager = self._create_manager(group, move_to_deleted)
                    actions = self.current_manager.analyze_sync()
                    if self.is_cancelled:
                        self.finished.emit(False, 0, 1, [self._t("Preview cancelled.", "미리보기가 취소되었습니다.", "Anulowano podgląd.")])
                        return
                    scan_errors = getattr(self.current_manager, "scan_errors", [])
                    if scan_errors:
                        self.finished.emit(False, 0, len(scan_errors), [str(error) for error in scan_errors])
                        return
                    
                    # 액션 정보에 그룹명 추가 (테이블 표시용)
                    for act in actions:
                        act["group_name"] = group["name"]
                        act["archive_folder_name"] = self.current_manager.archive_folder_name
                        act["date_archive_mode"] = getattr(self.current_manager, "date_archive_mode", "folder")
                    
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
                        total_fail += 1
                        break
                        
                    folders = group.get("folders", [])
                    if len(folders) < 2:
                        logger.info(f"Skipping group '{group['name']}' (less than 2 folders).")
                        continue
                        
                    self.progress.emit(i, len(self.sync_groups), self._t(f"[{group['name']}] Preparing analysis and synchronization...", f"[{group['name']}] 분석 및 동기화 준비 중...", f"[{group['name']}] Przygotowywanie analizy i synchronizacji..."))
                    
                    self.current_manager = self._create_manager(group, move_to_deleted)
                    actions = self.current_manager.analyze_sync()
                    
                    scan_errs = getattr(self.current_manager, "scan_errors", [])
                    if scan_errs:
                        for se in scan_errs:
                            all_errors.append(f"[{group['name']}] {se}")
                            total_fail += 1
                        continue

                    if not actions:
                        continue # 이 그룹은 동기화할 파일이 없음
                        
                    if self.is_cancelled:
                        all_errors.append(self._t("The operation was stopped by the user.", "사용자에 의해 전체 작업이 중단되었습니다.", "Operacja została zatrzymana przez użytkownika."))
                        total_fail += 1
                        break
                        
                    group_index = i
                    group_name = group["name"]

                    def callback(
                        current, total, filename,
                        group_index=group_index,
                        group_name=group_name
                    ):
                        # 파일 단위의 진행률 메시지를 그룹 단위 프로그레스와 함께 전달
                        self.progress.emit(
                            group_index,
                            len(self.sync_groups),
                            self._t(
                                f"[{group_name}] Synchronizing file: {filename}",
                                f"[{group_name}] 파일 동기화 중: {filename}",
                                f"[{group_name}] Synchronizowanie pliku: {filename}",
                            )
                        )
                        
                    sync_res = self.current_manager.execute_sync(actions, progress_callback=callback)
                    s_count = sync_res[0]
                    f_count = sync_res[1]
                    errs = list(sync_res[2])
                    held_items = list(getattr(sync_res, "held", []))

                    total_success += s_count
                    total_fail += f_count
                    if errs:
                        all_errors.extend([f"[{group['name']}] {e}" for e in errs])
                    if held_items:
                        total_fail += len(held_items)
                        all_errors.extend([f"[{group['name']}] [HELD] {h}" for h in held_items])
                        
                # 마지막 진행도 100%
                if not self.is_cancelled:
                    self.progress.emit(len(self.sync_groups), len(self.sync_groups), self._t("All synchronization groups completed.", "전체 동기화 완료.", "Zakończono wszystkie grupy synchronizacji."))
                    
                overall_success = (not self.is_cancelled) and (total_fail == 0) and (len(all_errors) == 0)
                self.finished.emit(
                    overall_success,
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
        self._ui_locked = False
        self._analysis_is_current = False
        self._analysis_has_actions = False
        self._analysis_has_holds = False
        self.worker = None
        
        self.init_ui()
        self.load_saved_data()
        self.refresh_language()
        self.setAcceptDrops(True)

    @property
    def language(self):
        return get_app_language(self.config_manager)

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def _msg(self, key, **values):
        return tr(key, self.language, **values)

    def _sync_text(self, value):
        reasons = {
            "Conflicting content for the same date": self._t("Different contents share the same date", "같은 날짜 파일의 내용이 달라 보류", "Różne treści mają tę samą datę"),
            "Target has a newer date": self._t("Target has a newer date", "대상에 더 최신 날짜 파일이 있어 보류", "Folder docelowy ma nowszą datę"),
            "대상에 원본보다 높은 버전이 있어 보류": self._t("Target version is higher; held, no changes", "대상 버전이 더 높아 보류, 변경 안함", "Wersja docelowa jest wyższa; wstrzymano, bez zmian"),
            "Target has a newer version": self._t("Target version is higher; held, no changes", "대상 버전이 더 높아 보류, 변경 안함", "Wersja docelowa jest wyższa; wstrzymano, bez zmian"),
            "Target has an equivalent version with a different filename": self._t("Target has an equivalent version with a different filename; held, no changes", "대상에 버전은 같지만 파일명이 달라 보류, 변경 안함", "Cel ma równoważną wersję pod inną nazwą; wstrzymano, bez zmian"),
            "Same version files differ with equal modification times": self._t("Same-version files differ but have the same modification time; held", "같은 버전의 내용이 다르지만 수정 시각이 같아 보류", "Pliki tej samej wersji różnią się, lecz mają ten sam czas modyfikacji; wstrzymano"),
            "Different contents with identical modification times": self._t("Contents differ but modification times are identical; held", "파일 내용이 다르지만 수정 시각이 같아 보류", "Treść plików jest różna, ale czas modyfikacji jest taki sam; wstrzymano"),
            "Filename case differs": self._t("Filename capitalization differs; held", "파일 이름의 대소문자가 달라 보류", "Nazwy plików różnią się wielkością liter; wstrzymano"),
        }
        if isinstance(value, str) and value in reasons:
            return reasons[value]
        if isinstance(value, str):
            value = value.replace("대상에 원본보다 높은 버전이 있어 보류", reasons["대상에 원본보다 높은 버전이 있어 보류"])
            value = value.replace("Target has a newer version", reasons["Target has a newer version"])
            value = value.replace("Target has an equivalent version with a different filename", reasons["Target has an equivalent version with a different filename"])
            value = value.replace("Same version files differ with equal modification times", reasons["Same version files differ with equal modification times"])
            value = value.replace("Different contents with identical modification times", reasons["Different contents with identical modification times"])
            value = value.replace("Filename case differs", reasons["Filename case differs"])
            value = value.replace("Target has a newer date", reasons["Target has a newer date"])
            value = value.replace("Conflicting content for the same date", reasons["Conflicting content for the same date"])
        if self.language == "ko" or not isinstance(value, str):
            return value
        replacements = {
            "신규 복사": self._t("New copy", "신규 복사", "Nowa kopia"),
            "최신 업데이트": self._t("Update to latest", "최신 업데이트", "Aktualizacja do najnowszej wersji"),
            "구버전 정리": self._t("Archive older version", "구버전 정리", "Archiwizacja starszej wersji"),
            "동시 수정 충돌": self._t("Concurrent modification conflict", "동시 수정 충돌", "Konflikt równoczesnych zmian"),
            "충돌 보존 백업": self._t("Preserve conflict backup", "충돌 보존 백업", "Kopia zapasowa konfliktu"),
            "날짜 동기화": self._t("Sync date versions", "날짜 동기화", "Synchronizuj wersje datowane"),
            "날짜 보류": self._t("Date family held", "날짜 보류", "Wersja datowana wstrzymana"),
            "보류": self._t("Held", "보류", "Wstrzymane"),
            "대상에 원본보다 높은 버전이 있어 보류": self._t("Target version is higher; held, no changes", "대상 버전이 더 높아 보류, 변경 안함", "Wersja docelowa jest wyższa; wstrzymano, bez zmian"),
            "휴지통이동": self._t("Move to Recycle Bin", "휴지통으로 이동", "Przenieś do kosza"),
            "충돌 백업 후 최신 업데이트": self._t("Back up conflict, then update", "충돌 백업 후 최신 업데이트", "Kopia konfliktu, następnie aktualizacja"),
            "to_be_deleted이동": self._t("Move to 'to be deleted'", "to_be_deleted이동", "Przenieś do 'to be deleted'"),
            "복사": self._t("Copy", "복사", "Kopiowanie"),
            "사용자에 의해 작업이 중단되었습니다.": self._t("The operation was stopped by the user.", "사용자에 의해 작업이 중단되었습니다.", "Operacja została zatrzymana przez użytkownika."),
            "동기화 완료": self._t("Synchronization completed", "동기화 완료", "Synchronizacja zakończona"),
            "처리 중": self._t("Processing", "처리 중", "Przetwarzanie"),
            "오류": self._t("Error", "오류", "Błąd"),
        }
        return replace_phrases(value, replacements)

    def _display_group_name(self, stored_name):
        if stored_name in DEFAULT_SYNC_GROUP_NAMES:
            return self._t("Default Sync Group", "기본 동기화 그룹", "Domyślna grupa synchronizacji")
        return stored_name

    def refresh_language(self):
        self.workflow_widget.set_step_texts([
            self._t("1. Configure Folders", "1. 폴더 구성", "1. Skonfiguruj foldery"),
            self._t("2. Preview Changes", "2. 변경 미리보기", "2. Podejrzyj zmiany"),
            self._t("3. Synchronize", "3. 동기화 실행", "3. Synchronizuj"),
            self._t("4. Review Results", "4. 결과 확인", "4. Sprawdź wyniki"),
        ])
        self.analyze_btn.setText(self._t("Preview Sync", "동기화 미리보기", "Podgląd synchronizacji"))
        self.cleanup_btn.setText(self._t("Clean up old versions", "구버전 정리", "Usuń stare wersje"))
        self.sync_btn.setText(self._t("Synchronize All", "전체 동기화", "Synchronizuj wszystko"))
        self.sync_mode_label.setText(self._t("Mode:", "동기화 방식:", "Tryb:"))
        self.sync_mode_combo.setItemText(0, self._t("Two-way (Latest Wins)", "양방향 (최신 파일 기준)", "Dwukierunkowo (najnowszy)"))
        self.sync_mode_combo.setItemText(1, self._t("One-way (1st Folder -> Others)", "단방향 (첫 번째 폴더 -> 나머지 배포)", "Jednokierunkowo (1. folder -> reszta)"))
        self.subfolders_check.setText(self._t("Include Subfolders", "하위 폴더 포함(재귀)", "Uwzględnij podfoldery"))
        self.date_latest_check.setText(self._t("Only filename date versions (vYYYYMMDD)", "파일명 날짜 버전만 동기화 (vYYYYMMDD)", "Tylko wersje z datą w nazwie (vYYYYMMDD)"))
        self.date_archive_label.setText(self._t("Old date files:", "날짜 구버전 처리:", "Stare pliki datowane:"))
        self.date_archive_combo.setItemText(0, self._t("Legacy Recycle Bin setting blocked: select folder", "기존 휴지통 설정 차단됨: 폴더 방식을 선택하세요", "Stare ustawienie kosza zablokowane: wybierz folder"))
        self.date_archive_combo.setItemText(1, self._t("'to be deleted' folder (or configured name)", "'to be deleted' 폴더로 이동 (이름 변경 가능)", "Folder 'to be deleted' (nazwa zmienna)"))
        self.date_archive_combo.setToolTip(self._t(
            "The legacy Recycle Bin setting is blocked in normal sync. Explicitly select the folder option to change it.",
            "기존 휴지통 설정은 일반 동기화에서 차단됩니다. 변경하려면 폴더 방식을 직접 선택하세요.",
            "Stare ustawienie kosza jest blokowane w zwykłej synchronizacji. Aby je zmienić, wybierz folder."
        ))
        self.exclude_label.setText(self._t("Exclude:", "제외 패턴:", "Wyklucz:"))
        self.archive_label.setText(self._t("Archive Dir:", "백업 폴더명:", "Folder archiwum:"))
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
        self._refresh_action_state()
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.workflow_widget = WorkflowWidget(
            steps=["1. Configure Folders", "2. Preview Changes", "3. Synchronize", "4. Review Results"]
        )
        layout.addWidget(self.workflow_widget)
        
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

        bridge_layout = QHBoxLayout()
        self.task_bridge_label = QLabel()
        self.task_bridge_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.task_bridge_btn = QPushButton()
        self.task_bridge_btn.setFixedHeight(22)
        self.task_bridge_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.task_bridge_btn.clicked.connect(self._navigate_to_task_tab)
        bridge_layout.addWidget(self.task_bridge_label)
        bridge_layout.addWidget(self.task_bridge_btn)
        bridge_layout.addStretch()
        group_layout.addLayout(bridge_layout)

        # 그룹별 범용 동기화 옵션 (모드, 하위 폴더 재귀, 제외 패턴, 백업 폴더명)
        options_h_layout = QHBoxLayout()
        self.sync_mode_label = QLabel(self._t("Mode:", "동기화 방식:", "Tryb:"))
        self.sync_mode_combo = QComboBox()
        self.sync_mode_combo.addItem(self._t("Two-way (Latest Wins)", "양방향 (최신 파일 기준)", "Dwukierunkowo (najnowszy)"), "two_way")
        self.sync_mode_combo.addItem(self._t("One-way (1st Folder -> Others)", "단방향 (첫 번째 폴더 -> 나머지 배포)", "Jednokierunkowo (1. folder -> reszta)"), "one_way")
        self.sync_mode_combo.currentIndexChanged.connect(self.on_group_options_changed)

        self.subfolders_check = QCheckBox(self._t("Include Subfolders", "하위 폴더 포함(재귀)", "Uwzględnij podfoldery"))
        self.subfolders_check.stateChanged.connect(self.on_group_options_changed)
        self.date_latest_check = QCheckBox(self._t("Only filename date versions (vYYYYMMDD)", "파일명 날짜 버전만 동기화 (vYYYYMMDD)", "Tylko wersje z datą w nazwie (vYYYYMMDD)"))
        self.date_latest_check.stateChanged.connect(self.on_group_options_changed)

        date_options_h_layout = QHBoxLayout()
        self.date_archive_label = QLabel(self._t("Old date files:", "날짜 구버전 처리:", "Stare pliki datowane:"))
        self.date_archive_combo = QComboBox()
        self.date_archive_combo.addItem("", None)
        self.date_archive_combo.addItem("", "folder")
        self.date_archive_combo.model().item(0).setEnabled(False)
        self.date_archive_combo.currentIndexChanged.connect(self.on_archive_mode_changed)
        date_options_h_layout.addWidget(self.date_latest_check)
        date_options_h_layout.addWidget(self.date_archive_label)
        date_options_h_layout.addWidget(self.date_archive_combo)
        date_options_h_layout.addStretch()

        self.exclude_label = QLabel(self._t("Exclude:", "제외 패턴:", "Wyklucz:"))
        self.exclude_input = QLineEdit()
        self.exclude_input.setPlaceholderText("*.tmp, *.bak, ~$*")
        self.exclude_input.editingFinished.connect(self.on_group_options_changed)

        self.archive_label = QLabel(self._t("Archive Dir:", "백업 폴더명:", "Folder archiwum:"))
        self.archive_input = QLineEdit()
        self.archive_input.setPlaceholderText("to be deleted")
        self.archive_input.setFixedWidth(120)
        self.archive_input.editingFinished.connect(self.on_group_options_changed)

        options_h_layout.addWidget(self.sync_mode_label)
        options_h_layout.addWidget(self.sync_mode_combo)
        options_h_layout.addWidget(self.subfolders_check)
        group_layout.addLayout(date_options_h_layout)
        options_h_layout.addWidget(self.exclude_label)
        options_h_layout.addWidget(self.exclude_input, 1)
        options_h_layout.addWidget(self.archive_label)
        options_h_layout.addWidget(self.archive_input)
        group_layout.addLayout(options_h_layout)

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
        self.cleanup_btn = QPushButton()
        self.cleanup_btn.clicked.connect(self.open_version_cleanup)
        btn_h_layout.addWidget(self.cleanup_btn)
        btn_h_layout.addWidget(self.stop_btn)
        control_layout.addLayout(btn_h_layout)
        
        self.progress_bar = QProgressBar()
        control_layout.addWidget(self.progress_bar)
        self.plan_summary_label = QLabel("분석 전")
        control_layout.addWidget(self.plan_summary_label)
        self.action_hint_label = QLabel()
        self.action_hint_label.setWordWrap(True)
        self.action_hint_label.setStyleSheet("color: #94a3b8; font-size: 11px; margin-top: 2px;")
        control_layout.addWidget(self.action_hint_label)
        
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
        self._refresh_action_state()

    def set_ui_enabled(self, enabled):
        """실행 중 UI 잠금을 위한 유틸리티"""
        self._ui_locked = not enabled
        self.group_combo.setEnabled(enabled)
        for widget in (self.sync_mode_combo, self.subfolders_check, self.date_latest_check,
                       self.date_archive_combo, self.exclude_input, self.archive_input):
            widget.setEnabled(enabled)
        for btn in self.findChildren(QPushButton):
            if btn not in (self.stop_btn,):
                btn.setEnabled(enabled)
        self._refresh_action_state()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_task_bridge()

    def _navigate_to_task_tab(self):
        main_win = self.window()
        tab_widget = getattr(main_win, "tab_widget", None)
        task_tab = getattr(main_win, "task_tab", None)
        if tab_widget and task_tab:
            idx = tab_widget.indexOf(task_tab)
            if idx >= 0:
                tab_widget.setCurrentIndex(idx)

    def refresh_task_bridge(self):
        try:
            self._refresh_task_bridge_impl()
        except Exception:
            logger.exception("Failed to refresh sync task bridge")

    def _refresh_task_bridge_impl(self):
        if not hasattr(self, "task_bridge_label"):
            return
        if self.current_group_idx < 0 or not self.sync_groups:
            self.task_bridge_label.clear()
            self.task_bridge_btn.hide()
            return
        group = self.sync_groups[self.current_group_idx] if 0 <= self.current_group_idx < len(self.sync_groups) else None
        if not group:
            self.task_bridge_label.clear()
            self.task_bridge_btn.hide()
            return

        group_key = f"sync:{group['id']}" if group.get("id") else "sync"
        enabled_items = self.config_manager.get("task_enabled_items", None)
        if enabled_items is not None and isinstance(enabled_items, dict):
            included = bool(enabled_items.get(group_key, False))
        else:
            enabled_steps = self.config_manager.get("task_enabled_steps", []) or []
            included = "sync" in enabled_steps

        schedule_enabled = bool(self.config_manager.get("task_schedule_enabled", False))
        sched_desc = format_task_schedule_description(self.config_manager, self.language)

        if included and schedule_enabled:
            text = self._t(
                f"🔗 Run Tasks: Included ({sched_desc})",
                f"🔗 작업 실행: 포함됨 ({sched_desc})",
                f"🔗 Uruchom zadania: Uwzględnione ({sched_desc})",
            )
        elif included:
            text = self._t(
                "🔗 Run Tasks: Included (Schedule off)",
                "🔗 작업 실행: 포함됨 (예약 꺼짐)",
                "🔗 Uruchom zadania: Uwzględnione (harmonogram wył.)",
            )
        else:
            text = self._t(
                "○ Run Tasks: Not included",
                "○ 작업 실행: 미포함",
                "○ Uruchom zadania: Nie uwzględnione",
            )

        btn_text = self._t("Open Run Tasks", "작업 실행 열기", "Otwórz Uruchom zadania")
        self.task_bridge_label.setText(text)
        self.task_bridge_btn.setText(btn_text)
        self.task_bridge_btn.show()

    def _valid_groups(self):
        return [group for group in self.sync_groups if len(group.get("folders", [])) >= 2]

    def _invalidate_analysis(self, folders_changed=False):
        self._analysis_is_current = False
        self._analysis_has_actions = False
        self._analysis_has_holds = False
        self.table_widget.setRowCount(0)
        if folders_changed:
            self.plan_summary_label.setText(
                self._t("Not analyzed (folders changed)", "분석 전 (폴더 변경됨)", "Nie przeanalizowano (zmieniono foldery)")
            )
        self._refresh_action_state()

    def _refresh_action_state(self):
        configured = bool(self._valid_groups())
        available = not self.is_running and not self._ui_locked
        self.analyze_btn.setEnabled(available and configured)
        self.sync_btn.setEnabled(
            available and configured and self._analysis_is_current and self._analysis_has_actions
        )
        if not configured:
            analyze_reason = self._t(
                "Step 1: add at least two folders to one group.",
                "1단계: 한 그룹에 폴더를 두 개 이상 등록하세요.",
                "Krok 1: dodaj co najmniej dwa foldery do jednej grupy.",
            )
            sync_reason = analyze_reason
            self.workflow_widget.reset()
        elif not self._analysis_is_current:
            analyze_reason = self._t("Ready to preview changes.", "변경 내용을 미리 볼 준비가 되었습니다.", "Gotowe do podglądu zmian.")
            sync_reason = self._t(
                "Step 2: preview the current changes first.",
                "2단계: 현재 변경 내용을 먼저 미리보세요.",
                "Krok 2: najpierw wyświetl podgląd bieżących zmian.",
            )
            if available:
                self.workflow_widget.set_active_step(1)
        elif not self._analysis_has_actions:
            analyze_reason = self._t("Run the preview again.", "미리보기를 다시 실행할 수 있습니다.", "Możesz ponownie uruchomić podgląd.")
            sync_reason = (self._t("Only held items remain; review the list.", "보류 항목만 있습니다. 목록을 확인해 주세요.", "Pozostały tylko wstrzymane pozycje; sprawdź listę.")
                           if self._analysis_has_holds else
                           self._t("No changes need synchronization.", "동기화할 변경 사항이 없습니다.", "Brak zmian wymagających synchronizacji."))
            self.workflow_widget.set_active_step(3)
        else:
            analyze_reason = self._t("Refresh the preview.", "미리보기를 새로 확인합니다.", "Odśwież podgląd.")
            sync_reason = self._t("Preview complete. Ready to synchronize.", "미리보기 완료. 동기화를 실행할 수 있습니다.", "Podgląd zakończony. Można synchronizować.")
            if available:
                self.workflow_widget.set_active_step(2)
        self.analyze_btn.setToolTip(analyze_reason)
        self.sync_btn.setToolTip(sync_reason)
        if hasattr(self, "action_hint_label"):
            if not configured:
                hint_text = f"💡 {analyze_reason}"
            elif not self._analysis_is_current:
                safe_note = self._t(
                    "(Analysis never changes your files.)",
                    "(분석은 파일을 변경하지 않는 안전한 단계입니다.)",
                    "(Analiza nie modyfikuje Twoich plików.)",
                )
                hint_text = f"💡 {analyze_reason} {safe_note}"
            elif not self._analysis_has_actions:
                hint_text = f"{'⚠️' if self._analysis_has_holds else '✅'} {sync_reason}"
            else:
                hint_text = f"💡 {sync_reason}"
            self.action_hint_label.setText(hint_text)
        self.refresh_task_bridge()

    # --- 데이터 & 설정 마이그레이션 ---
    def load_saved_data(self):
        # 마이그레이션 로직: sync_folders가 있고 sync_groups가 없으면 이전
        old_folders = self.config_manager.get("sync_folders", None)
        saved_groups = self.config_manager.get("sync_groups", None)
        
        if saved_groups is not None:
            self.sync_groups = copy.deepcopy(saved_groups)
        elif old_folders is not None:
            # 하위 호환성 마이그레이션
            self.sync_groups = [{"name": "Default Sync Group", "folders": old_folders}]
        else:
            self.sync_groups = [{"name": "Default Sync Group", "folders": [], "date_archive_mode": "folder"}]
            
        if not self.sync_groups: # 만약 비어있다면 최소 1개 보장
            self.sync_groups = [{"name": "Default Sync Group", "folders": [], "date_archive_mode": "folder"}]

        ensure_sync_ids(self.sync_groups)
        if self.sync_groups != saved_groups:
            try:
                if self.config_manager.set("sync_groups", self.sync_groups) is False:
                    raise OSError("Could not persist synchronization group identities.")
            except OSError as exc:
                logger.warning("Could not save synchronization group identities: %s", exc)
            
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
        ensure_sync_ids(self.sync_groups)
        try:
            if self.config_manager.get("task_selection_migrated", False):
                selected = dict(self.config_manager.get("task_enabled_items", {}) or {})
                for group in self.sync_groups:
                    selected.setdefault(f"sync:{group['id']}", False)
                if self.config_manager.set("task_enabled_items", selected) is False:
                    raise OSError("Could not save synchronization task selection.")
            if self.config_manager.set("sync_groups", self.sync_groups) is False:
                raise OSError("Could not save synchronization groups.")
            if self.config_manager.set("sync_last_group_index", self.current_group_idx) is False:
                raise OSError("Could not save synchronization group index.")
        except OSError as exc:
            logger.warning("Could not save synchronization settings: %s", exc)
            self.refresh_task_bridge()
            return False
        self.refresh_task_bridge()
        return True

    # --- 그룹 관리 로직 ---
    def on_group_changed(self, idx):
        if idx < 0 or idx >= len(self.sync_groups):
            return
        self.current_group_idx = idx
        group = self.sync_groups[idx]
        self.sync_mode_combo.blockSignals(True)
        self.subfolders_check.blockSignals(True)
        self.date_latest_check.blockSignals(True)
        self.date_archive_combo.blockSignals(True)
        self.exclude_input.blockSignals(True)
        self.archive_input.blockSignals(True)

        mode_val = str(group.get("sync_mode", "two_way") or "two_way")
        mode_idx = self.sync_mode_combo.findData(mode_val)
        self.sync_mode_combo.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        self.subfolders_check.setChecked(bool(group.get("include_subfolders", False)))
        self.date_latest_check.setChecked(bool(group.get("date_latest_only", False)))
        archive_mode = group.get("date_archive_mode", "folder")
        archive_mode_index = self.date_archive_combo.findData(archive_mode) if archive_mode == "folder" else 0
        self.date_archive_combo.setCurrentIndex(archive_mode_index if archive_mode_index >= 0 else self.date_archive_combo.findData("folder"))
        patterns = group.get("exclude_patterns", [])
        if isinstance(patterns, list):
            self.exclude_input.setText(", ".join(str(p) for p in patterns if str(p).strip()))
        else:
            self.exclude_input.setText(str(patterns or ""))
        self.archive_input.setText(str(group.get("archive_folder_name", "to be deleted") or "to be deleted"))

        self.sync_mode_combo.blockSignals(False)
        self.subfolders_check.blockSignals(False)
        self.date_latest_check.blockSignals(False)
        self.date_archive_combo.blockSignals(False)
        self.exclude_input.blockSignals(False)
        self.archive_input.blockSignals(False)

        self.refresh_folder_list()
        self.save_data()
        self._refresh_action_state()

    def on_group_options_changed(self):
        if self.current_group_idx < 0 or self.current_group_idx >= len(self.sync_groups):
            return
        group = self.sync_groups[self.current_group_idx]
        group["sync_mode"] = self.sync_mode_combo.currentData() or "two_way"
        group["include_subfolders"] = bool(self.subfolders_check.isChecked())
        group["date_latest_only"] = bool(self.date_latest_check.isChecked())
        raw_exclude = self.exclude_input.text()
        group["exclude_patterns"] = [p.strip() for p in raw_exclude.split(",") if p.strip()]
        archive_dir = self.archive_input.text().strip() or "to be deleted"
        group["archive_folder_name"] = archive_dir
        self.save_data()
        self._invalidate_analysis()

    def on_archive_mode_changed(self):
        if self.current_group_idx < 0 or self.date_archive_combo.currentData() != "folder":
            return
        self.sync_groups[self.current_group_idx]["date_archive_mode"] = "folder"
        self.save_data()
        self._invalidate_analysis()

    def open_version_cleanup(self):
        if self.is_running or self.current_group_idx < 0:
            return
        task_tab = getattr(self.window(), "task_tab", None)
        if task_tab and (getattr(task_tab, "is_running", False) or getattr(task_tab, "is_preflighting", False)):
            QMessageBox.warning(self, self._msg("common_warning"), self._t(
                "Finish or cancel the task run before opening old-version cleanup.",
                "통합 작업을 완료하거나 취소한 후 구버전 정리를 여세요.",
                "Zakończ lub anuluj zadanie przed otwarciem czyszczenia starych wersji."))
            return
        group = self.sync_groups[self.current_group_idx]
        dialog = VersionCleanupDialog(list(group.get("folders", [])), self.language, self,
                                      archive_folder_name=group.get("archive_folder_name", "to be deleted") or "to be deleted")
        self.cleanup_dialog = dialog
        try:
            dialog.exec()
        finally:
            self.cleanup_dialog = None
        
    def add_group(self):
        text, ok = QInputDialog.getText(self, self._msg("sync_add_group_title"), self._msg("sync_add_group_prompt"))
        if ok and text:
            text = text.strip()
            if not text:
                return
            if any(g["name"] == text for g in self.sync_groups):
                QMessageBox.warning(self, self._msg("common_warning"), self._msg("sync_duplicate_group"))
                return
                
            self.sync_groups.append({"name": text, "folders": [], "date_archive_mode": "folder"})
            self.group_combo.addItem(text)
            self.group_combo.setCurrentIndex(len(self.sync_groups) - 1)
            self.save_data()
            self._invalidate_analysis()
            
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
            self._invalidate_analysis()
            
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
                self.sync_groups.append({"name": default_name, "folders": [], "date_archive_mode": "folder"})
                self.group_combo.addItem(self._display_group_name(default_name))
                
            self.save_data()
            self.group_combo.setCurrentIndex(0) # 첫번째로 이동
            self._invalidate_analysis()

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
            self._invalidate_analysis(folders_changed=True)
            
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
        self._invalidate_analysis(folders_changed=True)
        
    def clear_folders(self):
        if self.current_group_idx < 0:
            return
            
        self.sync_groups[self.current_group_idx]["folders"] = []
        self.save_data()
        self.refresh_folder_list()
        self._invalidate_analysis(folders_changed=True)

    # --- 분석 및 실행 로직 ---
    def start_dry_run(self):
        # 폴더가 2개 이상인 그룹이 하나라도 있는지 확인
        valid_groups = self._valid_groups()
        if not valid_groups:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("No group contains at least two folders.\nAdd folders before analyzing.", "최소 2개 이상의 폴더가 등록된 그룹이 하나도 없습니다.\n폴더를 추가해주세요.", "Żadna grupa nie zawiera co najmniej dwóch folderów.\nDodaj foldery przed analizą."))
            return
            
        self.is_running = True
        self._analysis_is_current = False
        self._analysis_has_actions = False
        self._analysis_has_holds = False
        self.set_ui_enabled(False)
        self.stop_btn.setEnabled(True)
        self.table_widget.setRowCount(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.plan_summary_label.setText(self._t("Analyzing all groups...", "전체 그룹 분석 중...", "Analizowanie wszystkich grup..."))
        
        self.worker = SyncWorker(copy.deepcopy(self.sync_groups), self.config_manager, is_dry_run=True)
        self.worker.progress.connect(self.update_progress)
        self.worker.dry_run_finished.connect(self.on_dry_run_finished)
        self.worker.finished.connect(self.on_sync_finished)
        self.worker.start()
        
    def on_dry_run_finished(self, actions):
        if self.worker and self.worker.is_cancelled:
            self.on_sync_finished(False, 0, 1, [self._t("Preview cancelled.", "미리보기가 취소되었습니다.", "Anulowano podgląd.")])
            return
        display_actions = date_preview_rows(actions)
        self.is_running = False
        self._analysis_is_current = True
        self._analysis_has_holds = any(a.get("action") in ("보류", "날짜 보류") for a in actions)
        self._analysis_has_actions = any(a.get("action") not in ("보류", "날짜 보류", "오류") for a in actions)
        self.set_ui_enabled(True)
        self.stop_btn.setEnabled(False)
        
        self.table_widget.setRowCount(len(display_actions))
        
        for row_idx, act in enumerate(display_actions):
            group_item = QTableWidgetItem(act.get("group_name", ""))
            filename_item = QTableWidgetItem(act["filename"])
            action_item = QTableWidgetItem(self._sync_text(act["action"]))
            src_item = QTableWidgetItem(os.path.basename(act["source_folder"]))
            src_item.setToolTip(act["source_folder"])
            tgt_item = QTableWidgetItem(os.path.basename(act["target_folder"]))
            tgt_item.setToolTip(act["target_folder"])
            
            if act["action"] in ("보류", "날짜 보류"):
                mtime_str = self._sync_text(act.get("reason") or act.get("status", ""))
            elif act.get("mtime"):
                mtime_str = datetime.fromtimestamp(act["mtime"]).strftime("%Y-%m-%d %H:%M")
            else:
                mtime_str = self._sync_text(act.get("details", act.get("reason", "")))
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
            elif act["action"] == "오류":
                action_item.setForeground(QBrush(QColor("#ef5350")))
                action_item.setBackground(QBrush(QColor("#450a0a")))
                
            self.table_widget.setItem(row_idx, 0, group_item)
            self.table_widget.setItem(row_idx, 1, filename_item)
            self.table_widget.setItem(row_idx, 2, action_item)
            self.table_widget.setItem(row_idx, 3, src_item)
            self.table_widget.setItem(row_idx, 4, tgt_item)
            self.table_widget.setItem(row_idx, 5, details_item)
            
        if actions:
            action_count = sum(a.get("action") not in ("보류", "날짜 보류", "오류") for a in display_actions)
            held_count = sum(a.get("action") in ("보류", "날짜 보류") for a in display_actions)
            self.plan_summary_label.setText(self._t(f"Analysis result: {action_count} planned, {held_count} held", f"분석 결과: 실행 예정 {action_count}건, 보류 {held_count}건", f"Wynik analizy: {action_count} zaplanowanych, {held_count} wstrzymanych"))
            show_toast(self, self._t(f"Analysis complete: {action_count} planned, {held_count} held", f"분석 완료: 실행 예정 {action_count}건, 보류 {held_count}건", f"Analiza zakończona: {action_count} zaplanowanych, {held_count} wstrzymanych"), "info")
        else:
            self.plan_summary_label.setText(self._t("Analysis result: nothing to do", "분석 결과: 실행할 작업 없음", "Wynik analizy: brak operacji"))
            show_toast(self, self._t("Analysis complete: folders are already synchronized.", "분석 완료: 동기화할 내역이 없습니다.", "Analiza zakończona: foldery są już zsynchronizowane."), "success")
            QMessageBox.information(self, self._t("Information", "정보", "Informacja"), self._t("All group folders are already synchronized.", "모든 그룹의 파일들이 이미 최신 동기화 상태입니다.", "Wszystkie foldery grup są już zsynchronizowane."))
            
    def start_sync_execution(self):
        if self.is_running:
            return
        valid_groups = self._valid_groups()
        if not valid_groups:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("No group contains at least two folders.", "최소 2개 이상의 폴더가 등록된 그룹이 하나도 없습니다.", "Żadna grupa nie zawiera co najmniej dwóch folderów."))
            return
        if not self._analysis_is_current or not self._analysis_has_actions:
            QMessageBox.information(
                self,
                self._t("Preview required", "미리보기 필요", "Wymagany podgląd"),
                self._t("Preview the current changes before synchronizing.", "동기화 전에 현재 변경 내용을 먼저 미리보세요.", "Przed synchronizacją wyświetl podgląd bieżących zmian."),
            )
            return
            
        try:
            run_config = self.build_run_config()
        except TaskValidationError as exc:
            problem = tr(exc.message_key, self.language, **exc.values) if exc.message_key else exc.user_message
            QMessageBox.warning(self, self._msg("common_warning"), problem)
            return
        if run_config is None:
            return
        plan = RunPlan({TaskStep.SYNC: run_config})
        if not confirm_run_summary(self, plan, self.config_manager):
            return
            
        self.is_running = True
        self.set_ui_enabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.plan_summary_label.setText(self._msg("sync_running"))
        
        self.worker = SyncWorker(
            run_config.to_legacy_dict()["sync_groups"],
            self.config_manager,
            is_dry_run=False,
            approved_actions=plan.approved_manifest,
        )
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
        if getattr(self, "cleanup_dialog", None):
            self.cleanup_dialog.stop_and_wait()

    def cleanup_running(self):
        dialog = getattr(self, "cleanup_dialog", None)
        return bool(dialog and dialog.worker and dialog.worker.isRunning())
            
    def update_progress(self, current, total, status_msg):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}% ({current}/{total})")
        if parent_win := self.window():
            if hasattr(parent_win, 'status_bar'):
                parent_win.status_bar.showMessage(self._sync_text(status_msg))

    def on_sync_finished(self, success, success_count, fail_count, errors):
        self.is_running = False
        self._analysis_is_current = False
        self._analysis_has_actions = False
        self._analysis_has_holds = False
        self.set_ui_enabled(True)
        self.stop_btn.setEnabled(False)
        self.table_widget.setRowCount(0) # 작업이 끝났으므로 비움
        
        held_errors = [error for error in errors if "[HELD]" in error]
        if held_errors and len(held_errors) == len(errors) and fail_count == len(held_errors):
            heading = self._t("Synchronization has held items", "동기화 보류 항목 있음", "Synchronizacja zawiera wstrzymane pozycje")
            details = "\n".join(self._sync_text(error.replace("[HELD]", self._t("[Held]", "[보류]", "[Wstrzymane]"))) for error in held_errors)
            self.plan_summary_label.setText(heading)
            show_toast(self, heading, "warning")
            QMessageBox.warning(self, heading, details)
        elif success:
            if fail_count == 0:
                self.plan_summary_label.setText(self._msg("sync_completed_summary", success=success_count))
                show_toast(self, self._msg("sync_completed_toast"), "success")
                QMessageBox.information(self, self._msg("common_completed"), self._msg("sync_completed_dialog", success=success_count))
                self.workflow_widget.complete_all()
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

    def build_run_config(self, group_ids=None):
        groups = self.sync_groups if group_ids is None else [g for g in self.sync_groups if g.get("id") in group_ids]
        valid_groups = [g for g in groups if len(g.get("folders", [])) >= 2]
        if not valid_groups:
            return None
            
        for group in groups:
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
                    archive_folder_name=str(group.get("archive_folder_name", "to be deleted") or "to be deleted"),
                    exclude_patterns=list(group.get("exclude_patterns", [])),
                    include_subfolders=bool(group.get("include_subfolders", False)),
                    sync_mode=str(group.get("sync_mode", "two_way") or "two_way"),
                    date_latest_only=bool(group.get("date_latest_only", False)),
                    date_archive_mode=str(group.get("date_archive_mode", "folder") or "folder"),
                )
                for idx, group in enumerate(valid_groups)
            ]
        )

    def get_task_info(self):
        config = self.build_run_config()
        return config.to_legacy_dict() if config else None
        
    def set_ui_locked(self, locked):
        self.set_ui_enabled(not locked)
