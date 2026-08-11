import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QProgressBar,
    QFileDialog, QMessageBox, QGroupBox, QTextEdit, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.ui.workflow_widget import WorkflowWidget
from src.ui.toast_notification import show_toast
from src.ui.i18n import choose, get_app_language, tr
from src.ui.backup_recovery_dialog import BackupRecoveryDialog
from src.ui.preflight_dialog import run_bounded_preflight
from src.core.bypass_converter import BypassConverter
from src.core.task_contracts import (
    BypassFileConfig,
    BypassRunConfig,
    RunPlan,
    SourceDisposition,
    TaskStep,
    TaskValidationError,
)
from src.utils.logger import get_logger

logger = get_logger()

class BypassConvertWorker(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, status_msg
    file_completed = pyqtSignal(str, str, bool, str)  # src, tgt, success, message
    finished = pyqtSignal(bool, str)      # success, message
    
    def __init__(self, tasks, converter, language="en"):
        super().__init__()
        self.tasks = tasks
        self.converter = converter
        self.is_running = True
        self.language = language

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def _msg(self, key, **values):
        return tr(key, self.language, **values)
        
    def stop(self):
        self.is_running = False
        
    def run(self):
        total = len(self.tasks)
        success_count = 0
        
        try:
            for idx, task in enumerate(self.tasks):
                if not self.is_running:
                    self.finished.emit(False, self._msg("bypass_stopped_by_user"))
                    return
                    
                src = task["src"]
                tgt = task["tgt"]
                ext = task["ext"]
                preserve_meta = task["preserve_meta"]
                source_disposition = task.get("source_disposition", SourceDisposition.KEEP.value)
                
                filename = os.path.basename(src)
                self.progress.emit(idx, total, self._msg("bypass_converting_file", filename=filename))
                
                # 변환 수행
                success, msg = self.converter.convert_file(
                    src_path=src,
                    tgt_path=tgt,
                    target_ext=ext,
                    preserve_meta=preserve_meta,
                    source_disposition=source_disposition,
                )
                
                if success:
                    success_count += 1
                    self.file_completed.emit(src, tgt, True, msg)
                else:
                    self.file_completed.emit(src, tgt, False, msg)
                    
            self.progress.emit(total, total, self._msg("bypass_progress_complete", success=success_count, total=total))
            self.finished.emit(
                success_count == total,
                self._msg("bypass_result_complete", success=success_count, total=total)
            )
            
        except Exception as e:
            logger.error(f"Error in BypassConvertWorker: {e}")
            self.finished.emit(False, self._msg("bypass_worker_error", detail=str(e)))


class BypassTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.converter = BypassConverter()
        
        self.scanned_files = []      # 스캔된 원본 파일 리스트
        self.worker = None
        self.is_running = False
        self._ui_locked = False
        
        self.init_ui()
        self.setAcceptDrops(True)

    @property
    def language(self):
        return get_app_language(self.config_manager)

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def _msg(self, key, **values):
        return tr(key, self.language, **values)

    def _error_text(self, message):
        if self.language == "ko" or not isinstance(message, str):
            return message
        keys = (
            "bypass_detail_source_missing",
            "bypass_detail_file_in_use",
            "bypass_detail_unsupported_type",
            "bypass_detail_unknown_failure",
            "bypass_detail_source_delete_failed",
            "bypass_detail_com_unavailable",
            "bypass_detail_conversion_error",
            "bypass_detail_compression_error",
            "bypass_detail_copy_error",
            "bypass_detail_success",
        )
        translated = message
        for key in keys:
            translated = translated.replace(tr(key, "ko"), self._msg(key))
        return translated

    def _converter_message(self, message):
        if not isinstance(message, str):
            return str(message)
        marker, _separator, detail = message.partition("|")
        if marker == "SOURCE_KEPT":
            return self._t("Source kept in place.", "원본을 그대로 보존했습니다.", "Plik źródłowy pozostawiono na miejscu.")
        if marker == "SOURCE_BACKED_UP":
            return self._t(
                f"Source moved to backup: {detail}",
                f"원본을 백업 폴더로 이동했습니다: {detail}",
                f"Plik źródłowy przeniesiono do kopii zapasowej: {detail}",
            )
        if marker == "SOURCE_BACKED_UP_MANIFEST_WARNING":
            backup_path, _separator, error = detail.partition("|")
            return self._t(
                f"Source moved to backup, but recovery history could not be recorded: {backup_path} ({error})",
                f"원본은 백업으로 이동했지만 복구 이력을 기록하지 못했습니다: {backup_path} ({error})",
                f"Źródło przeniesiono do kopii, ale nie zapisano historii odzyskiwania: {backup_path} ({error})",
            )
        if marker == "SOURCE_BACKUP_FAILED":
            return self._t(
                f"Conversion succeeded, but the source could not be moved to backup: {detail}",
                f"변환은 성공했지만 원본을 백업 폴더로 이동하지 못했습니다: {detail}",
                f"Konwersja zakończyła się, ale nie udało się przenieść źródła do kopii: {detail}",
            )
        if marker == "SOURCE_RECYCLED":
            return self._t(
                f"Verified output replaced the source; the old source was moved to the Recycle Bin: {detail}",
                f"출력 파일을 검증한 뒤 원본을 교체하고 기존 원본은 휴지통으로 이동했습니다: {detail}",
                f"Zweryfikowany wynik zastąpił źródło, a stare źródło przeniesiono do Kosza: {detail}",
            )
        if marker == "SOURCE_RECYCLED_WARNING":
            output_path, _separator, error = detail.partition("|")
            return self._t(
                f"The source left its original location, but Windows reported a Recycle Bin warning: {output_path} ({error})",
                f"원본은 기존 위치에서 이동했지만 Windows가 휴지통 경고를 보고했습니다: {output_path} ({error})",
                f"Źródło opuściło pierwotne miejsce, ale Windows zgłosił ostrzeżenie Kosza: {output_path} ({error})",
            )
        if marker == "SOURCE_DELETED_FALLBACK":
            output_path, _separator, error = detail.partition("|")
            return self._t(
                f"Verified output replaced the source. Recycle Bin was unavailable, so the old source was permanently deleted: {output_path} ({error})",
                f"출력 파일을 검증한 뒤 원본을 교체했습니다. 휴지통을 사용할 수 없어 기존 원본을 영구 삭제했습니다: {output_path} ({error})",
                f"Zweryfikowany wynik zastąpił źródło. Kosz był niedostępny, więc stare źródło trwale usunięto: {output_path} ({error})",
            )
        if marker == "SOURCE_REPLACE_FAILED":
            source, _separator, error = detail.partition("|")
            return self._t(
                f"Conversion succeeded, but the source could not be removed. Both files were kept: {source} ({error})",
                f"변환은 성공했지만 원본을 삭제하지 못해 두 파일을 모두 보존했습니다: {source} ({error})",
                f"Konwersja powiodła się, ale nie usunięto źródła. Zachowano oba pliki: {source} ({error})",
            )
        if marker == "SOURCE_CHANGED_DURING_CONVERSION":
            return self._t(
                f"The source changed during conversion, so it was not removed: {detail}",
                f"변환 중 원본이 변경되어 삭제하지 않았습니다: {detail}",
                f"Źródło zmieniło się podczas konwersji, więc nie zostało usunięte: {detail}",
            )
        if marker in {"SOURCE_MISSING_BEFORE_REPLACE", "SOURCE_REPLACE_CHECK_FAILED"}:
            return self._t(
                f"The source could not be safely verified before replacement: {detail}",
                f"원본 교체 직전 안전 상태를 확인하지 못했습니다: {detail}",
                f"Nie można było bezpiecznie sprawdzić źródła przed zastąpieniem: {detail}",
            )
        if marker == "OUTPUT_NOT_CREATED":
            return self._t(
                f"The converter reported success, but no output file was created: {detail}",
                f"변환기가 성공을 보고했지만 출력 파일이 생성되지 않았습니다: {detail}",
                f"Konwerter zgłosił sukces, ale plik wyjściowy nie powstał: {detail}",
            )
        if marker == "SOURCE_TARGET_SAME":
            return self._t(
                f"Source and output paths are identical: {detail}",
                f"원본과 출력 경로가 같습니다: {detail}",
                f"Ścieżki źródłowa i wyjściowa są identyczne: {detail}",
            )
        if marker == "TARGET_ALREADY_EXISTS":
            return self._t(
                f"An output file already exists at this path: {detail}",
                f"출력 경로에 파일이 이미 있습니다: {detail}",
                f"Plik wyjściowy już istnieje: {detail}",
            )
        if marker == "OUTPUT_EMPTY":
            return self._t(
                f"The generated output file is empty: {detail}",
                f"생성된 출력 파일이 비어 있습니다: {detail}",
                f"Wygenerowany plik wyjściowy jest pusty: {detail}",
            )
        if marker in {"OUTPUT_FORMAT_INVALID", "OUTPUT_VALIDATION_FAILED"}:
            output_path, _separator, error = detail.partition("|")
            return self._t(
                f"The output could not be verified, so the source was kept: {output_path} ({error})",
                f"출력 파일을 검증하지 못해 원본을 보존했습니다: {output_path} ({error})",
                f"Nie zweryfikowano wyniku, dlatego zachowano źródło: {output_path} ({error})",
            )
        if marker == "TARGET_EXTENSION_MISMATCH":
            output_path, _separator, expected = detail.partition("|")
            return self._t(
                f"The output extension does not match the selected format: {output_path} (expected {expected})",
                f"출력 파일 확장자가 선택한 형식과 다릅니다: {output_path} (예상 {expected})",
                f"Rozszerzenie wyniku nie pasuje do wybranego formatu: {output_path} (oczekiwano {expected})",
            )
        if marker == "INVALID_SOURCE_DISPOSITION":
            return self._t(
                f"Unknown source-file action: {detail}",
                f"알 수 없는 원본 파일 처리 방식입니다: {detail}",
                f"Nieznana akcja dla pliku źródłowego: {detail}",
            )
        if marker in {"INVALID_PATH", "INVALID_TARGET_EXTENSION"}:
            return self._t(
                f"Invalid conversion path or target format: {detail}",
                f"변환 경로 또는 대상 형식이 올바르지 않습니다: {detail}",
                f"Nieprawidłowa ścieżka konwersji lub format docelowy: {detail}",
            )
        return self._error_text(message)

    @staticmethod
    def _format_size(byte_count):
        size = float(byte_count)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}"
            size /= 1024

    def _backup_confirmation_text(self, run_config):
        total_size = sum(os.path.getsize(task.src) for task in run_config.tasks if os.path.exists(task.src))
        source_folders = sorted({os.path.dirname(task.src) for task in run_config.tasks})
        target_folders = sorted({os.path.dirname(task.tgt) for task in run_config.tasks})
        backup_folders = sorted({os.path.join(folder, "Original Backup") for folder in source_folders})
        lines = [
            self._t(
                "After each output is successfully created and verified, its source file will be moved to a recoverable backup folder.",
                "각 출력 파일이 정상 생성되었는지 확인한 뒤 원본을 복구 가능한 백업 폴더로 이동합니다.",
                "Po utworzeniu i sprawdzeniu każdego wyniku plik źródłowy zostanie przeniesiony do folderu kopii zapasowej.",
            ),
            "",
            self._t(f"Files: {len(run_config.tasks)}", f"파일 수: {len(run_config.tasks)}개", f"Pliki: {len(run_config.tasks)}"),
            self._t(f"Total size: {self._format_size(total_size)}", f"전체 크기: {self._format_size(total_size)}", f"Łączny rozmiar: {self._format_size(total_size)}"),
            "",
            self._t("Source folders:", "원본 폴더:", "Foldery źródłowe:"),
            *[f"- {path}" for path in source_folders],
            self._t("Output folders:", "출력 폴더:", "Foldery wyjściowe:"),
            *[f"- {path}" for path in target_folders],
            self._t("Backup folders:", "백업 폴더:", "Foldery kopii zapasowej:"),
            *[f"- {path}" for path in backup_folders],
            "",
            self._t("Continue?", "계속할까요?", "Kontynuować?"),
        ]
        return "\n".join(lines)

    def _confirm_backup_move(self, run_config):
        if run_config.source_disposition != SourceDisposition.BACKUP:
            return True
        answer = QMessageBox.question(
            self,
            self._t("Confirm source backup", "원본 백업 이동 확인", "Potwierdź kopię źródeł"),
            self._backup_confirmation_text(run_config),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _replacement_confirmation_text(self, run_config):
        total_size = sum(os.path.getsize(task.src) for task in run_config.tasks if os.path.exists(task.src))
        mappings = [f"- {task.src}  →  {task.tgt}" for task in run_config.tasks[:8]]
        if len(run_config.tasks) > len(mappings):
            mappings.append(self._t(
                f"- ... and {len(run_config.tasks) - len(mappings)} more",
                f"- ... 외 {len(run_config.tasks) - len(mappings)}개",
                f"- ... i jeszcze {len(run_config.tasks) - len(mappings)}",
            ))
        lines = [
            self._t(
                "The app will create and structurally verify each output, then move its old source to the Windows Recycle Bin.",
                "각 출력 파일을 생성하고 구조를 검증한 뒤 기존 원본 파일을 Windows 휴지통으로 이동합니다.",
                "Aplikacja utworzy i sprawdzi strukturę każdego wyniku, a następnie przeniesie stare źródło do Kosza Windows.",
            ),
            self._t(
                "If the Recycle Bin is unavailable, permanent deletion is used. If both actions fail, the source is kept. Original Backup is not used.",
                "휴지통을 사용할 수 없으면 영구 삭제합니다. 두 방법이 모두 실패하면 원본을 보존하며, Original Backup은 사용하지 않습니다.",
                "Jeśli Kosz jest niedostępny, używane jest trwałe usunięcie. Jeśli obie akcje zawiodą, źródło zostaje zachowane. Original Backup nie jest używany.",
            ),
            "",
            self._t(f"Files: {len(run_config.tasks)}", f"파일 수: {len(run_config.tasks)}개", f"Pliki: {len(run_config.tasks)}"),
            self._t(f"Total size: {self._format_size(total_size)}", f"전체 크기: {self._format_size(total_size)}", f"Łączny rozmiar: {self._format_size(total_size)}"),
            "",
            self._t("Replacement preview:", "교체 미리보기:", "Podgląd zastąpienia:"),
            *mappings,
            "",
            self._t("Replace these source files?", "이 원본 파일들을 교체할까요?", "Zastąpić te pliki źródłowe?"),
        ]
        return "\n".join(lines)

    def _confirm_source_action(self, run_config):
        if run_config.source_disposition == SourceDisposition.BACKUP:
            return self._confirm_backup_move(run_config)
        if run_config.source_disposition != SourceDisposition.REPLACE:
            return True
        answer = QMessageBox.warning(
            self,
            self._t("Confirm source replacement", "원본 교체 확인", "Potwierdź zastąpienie źródeł"),
            self._replacement_confirmation_text(run_config),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def refresh_language(self):
        file_count = len(self.scanned_files)
        self.workflow_widget.set_step_texts([
            self._t("1. Scan Files", "1. 파일 스캔", "1. Skanuj pliki"),
            self._t("2. Run Conversion", "2. 변환 실행", "2. Uruchom konwersję"),
            self._t("3. Complete", "3. 완료", "3. Zakończ"),
        ])
        self.file_table.setHorizontalHeaderLabels([
            self._t("File Name", "파일명", "Nazwa pliku"),
            self._t("Original Size", "원본 크기", "Rozmiar oryginału"),
            self._t("Target Format", "대상 형식", "Format docelowy"),
            self._t("Status", "상태", "Stan"),
        ])
        self.summary_label.setText(self._t(f"Files found: {file_count}", f"검색된 대상 파일: {file_count}개", f"Znalezione pliki: {file_count}"))
        self.backup_recovery_btn.setText(
            self._t(
                "Review / Restore Original Backup",
                "Original Backup 확인 / 복구",
                "Przejrzyj / przywróć Original Backup",
            )
        )
        self._update_source_action_ui()
        if not self.scanned_files:
            source_prompts = ("드래그 앤 드롭", "Drag a folder", "Przeciągnij folder")
            if self.src_entry.text().startswith(source_prompts):
                self.src_entry.setText(self._t(
                    "Drag a folder here or choose one with the button.",
                    "드래그 앤 드롭 또는 우측 버튼으로 폴더를 선택하세요.",
                    "Przeciągnij folder tutaj lub wybierz go przyciskiem.",
                ))
            target_prompts = ("저장할 우회", "Choose the folder", "Wybierz folder zapisu")
            if self.tgt_entry.text().startswith(target_prompts):
                self.tgt_entry.setText(self._t(
                    "Choose the folder where converted files are saved.",
                    "저장할 우회 폴더를 선택하세요.",
                    "Wybierz folder zapisu przekonwertowanych plików.",
                ))
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 1. 워크플로우 인디케이터
        self.workflow_widget = WorkflowWidget(steps=["1. Scan Files", "2. Run Conversion", "3. Complete"])
        layout.addWidget(self.workflow_widget)
        
        # 2. 소스 및 대상 폴더 선택 패널
        folder_group = QGroupBox("Directory Configuration")
        folder_layout = QVBoxLayout()
        folder_group.setLayout(folder_layout)
        
        # 소스 폴더
        src_layout = QHBoxLayout()
        src_label = QLabel("Source Folder:")
        src_label.setMinimumWidth(100)
        self.src_entry = QLabel("드래그 앤 드롭 또는 우측 버튼으로 폴더를 선택하세요.")
        self.src_entry.setStyleSheet(
            "background-color: #1e1e1e; color: #94a3b8; border: 1px dashed #475569; "
            "padding: 8px; border-radius: 4px; font-style: italic;"
        )
        src_btn = QPushButton("폴더 선택")
        src_btn.clicked.connect(self.select_source_folder)
        src_layout.addWidget(src_label)
        src_layout.addWidget(self.src_entry, 1)
        src_layout.addWidget(src_btn)
        folder_layout.addLayout(src_layout)
        
        # 대상 폴더 옵션
        tgt_option_layout = QHBoxLayout()
        self.radio_inplace = QRadioButton("원본 교체: 변환 성공 후 기존 원본을 휴지통으로 이동 (In-place)")
        
        self.radio_custom = QRadioButton("특정 저장용 폴더에 우회 보관 (Target)")
        
        self.bg_group = QButtonGroup()
        self.bg_group.addButton(self.radio_inplace)
        self.bg_group.addButton(self.radio_custom)

        output_mode = self.config_manager.get("bypass_output_mode", "inplace")
        self.radio_custom.setChecked(output_mode == "custom")
        self.radio_inplace.setChecked(output_mode != "custom")
        self.radio_inplace.toggled.connect(self.toggle_target_mode)
        self.radio_custom.toggled.connect(self.toggle_target_mode)
        
        tgt_option_layout.addWidget(self.radio_inplace)
        tgt_option_layout.addWidget(self.radio_custom)
        tgt_option_layout.addStretch()
        folder_layout.addLayout(tgt_option_layout)

        self.source_action_hint = QLabel()
        self.source_action_hint.setWordWrap(True)
        folder_layout.addWidget(self.source_action_hint)
        
        # 대상 폴더 경로 선택기
        self.tgt_layout_widget = QWidget()
        tgt_layout = QHBoxLayout()
        self.tgt_layout_widget.setLayout(tgt_layout)
        self.tgt_layout_widget.setContentsMargins(0, 0, 0, 0)
        
        tgt_label = QLabel("Target Folder:")
        tgt_label.setMinimumWidth(100)
        self.tgt_entry = QLabel("저장할 우회 폴더를 선택하세요.")
        self.tgt_entry.setStyleSheet(
            "background-color: #1e1e1e; color: #94a3b8; border: 1px dashed #475569; "
            "padding: 8px; border-radius: 4px; font-style: italic;"
        )
        tgt_btn = QPushButton("폴더 선택")
        tgt_btn.clicked.connect(self.select_target_folder)
        tgt_layout.addWidget(tgt_label)
        tgt_layout.addWidget(self.tgt_entry, 1)
        tgt_layout.addWidget(tgt_btn)
        folder_layout.addWidget(self.tgt_layout_widget)
        self.tgt_layout_widget.setVisible(self.radio_custom.isChecked())
        
        layout.addWidget(folder_group)
        
        # 3. 우회 포맷 및 규칙 매핑 패널
        rules_group = QGroupBox("Bypass Rules Mapping & Options")
        rules_layout = QHBoxLayout()
        rules_group.setLayout(rules_layout)
        
        # 콤보박스들 구성
        excel_label = QLabel("Excel (.xlsx/.xls):")
        self.excel_combo = QComboBox()
        self.excel_combo.addItems([".xlsb", ".xlsm", ".xlsx"])
        
        ppt_label = QLabel("PowerPoint (.pptx/.ppt):")
        self.ppt_combo = QComboBox()
        self.ppt_combo.addItems([".pptm", ".pptx"])
        
        word_label = QLabel("Word (.docx/.doc):")
        self.word_combo = QComboBox()
        self.word_combo.addItems([".docm", ".docx"])
        
        pdf_label = QLabel("PDF (.pdf):")
        self.pdf_combo = QComboBox()
        self.pdf_combo.addItems([".zip", ".pdf"])
        
        # 옵션 체크박스
        self.check_backup_orig = QCheckBox("변환 완료 후 원본을 'Original Backup' 폴더로 이동")
        self.check_preserve_meta = QCheckBox("파일 메타정보(생성/수정/액세스 날짜) 보존 (Preserve Meta)")
        
        # 설정값 반영
        self.excel_combo.setCurrentText(self.config_manager.get("bypass_excel_target", ".xlsb"))
        self.ppt_combo.setCurrentText(self.config_manager.get("bypass_ppt_target", ".pptm"))
        self.word_combo.setCurrentText(self.config_manager.get("bypass_word_target", ".docm"))
        self.pdf_combo.setCurrentText(self.config_manager.get("bypass_pdf_target", ".zip"))
        disposition = self.config_manager.get("bypass_source_disposition", SourceDisposition.KEEP.value)
        self.check_backup_orig.setChecked(disposition == SourceDisposition.BACKUP.value)
        self.check_backup_orig.toggled.connect(self._save_source_disposition)
        self.check_preserve_meta.setChecked(self.config_manager.get("bypass_preserve_meta", True))
        for combo in (self.excel_combo, self.ppt_combo, self.word_combo, self.pdf_combo):
            combo.currentTextChanged.connect(self._invalidate_scan)
        
        # 레이아웃 배치
        v_combos = QVBoxLayout()
        h_row1 = QHBoxLayout()
        h_row1.addWidget(excel_label)
        h_row1.addWidget(self.excel_combo)
        h_row1.addWidget(ppt_label)
        h_row1.addWidget(self.ppt_combo)
        v_combos.addLayout(h_row1)
        
        h_row2 = QHBoxLayout()
        h_row2.addWidget(word_label)
        h_row2.addWidget(self.word_combo)
        h_row2.addWidget(pdf_label)
        h_row2.addWidget(self.pdf_combo)
        v_combos.addLayout(h_row2)
        rules_layout.addLayout(v_combos, 3)
        
        v_options = QVBoxLayout()
        v_options.addWidget(self.check_backup_orig)
        v_options.addWidget(self.check_preserve_meta)
        self.backup_recovery_btn = QPushButton(
            self._t(
                "Review / Restore Original Backup",
                "Original Backup 확인 / 복구",
                "Przejrzyj / przywróć Original Backup",
            )
        )
        self.backup_recovery_btn.clicked.connect(self.open_backup_recovery)
        v_options.addWidget(self.backup_recovery_btn)
        rules_layout.addLayout(v_options, 2)
        
        layout.addWidget(rules_group)
        
        # 4. 파일 리스트 및 로그 영역 (좌/우 분할)
        main_h_layout = QHBoxLayout()
        
        # 좌측: 스캔 파일 리스트 테이블
        left_panel = QGroupBox("Target Scan Files (Simulation)")
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)
        
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(4)
        self.file_table.setHorizontalHeaderLabels(["File Name", "Original Size", "Target Format", "Status"])
        self.file_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.file_table)
        
        self.summary_label = QLabel("검색된 대상 파일: 0개")
        left_layout.addWidget(self.summary_label)
        
        # 제어 버튼 레이아웃
        btn_layout = QHBoxLayout()
        self.scan_btn = QPushButton("대상 파일 스캔")
        self.scan_btn.clicked.connect(self.scan_source_folder)
        self.start_btn = QPushButton("파일 변환 시작")
        self.start_btn.setProperty("variant", "success")
        self.start_btn.clicked.connect(self.start_conversion)
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_conversion)
        
        btn_layout.addWidget(self.scan_btn)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        left_layout.addLayout(btn_layout)
        
        main_h_layout.addWidget(left_panel, 3)
        
        # 우측: 상세 작업 로그 콘솔
        right_panel = QGroupBox("Detailed Activity Log")
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #1e1e1e; color: #cbd5e1; border: 1px solid #334155; font-family: Consolas;")
        right_layout.addWidget(self.log_area)
        
        main_h_layout.addWidget(right_panel, 2)
        layout.addLayout(main_h_layout)
        
        # 진행 상태 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # 복구 폴더 연결
        last_src = self.config_manager.get("last_bypass_source_directory", "")
        if last_src and os.path.exists(last_src):
            self.set_source_folder_path(last_src)
            
        last_tgt = self.config_manager.get("last_bypass_target_directory", "")
        if last_tgt and os.path.exists(last_tgt):
            self.set_target_folder_path(last_tgt)
        self.tgt_layout_widget.setVisible(self.radio_custom.isChecked())
        self._update_source_action_ui()
        self._refresh_action_state()

    def _save_source_disposition(self, backup_enabled):
        disposition = SourceDisposition.BACKUP if backup_enabled else SourceDisposition.KEEP
        values = {
            "bypass_source_disposition": disposition.value,
            "bypass_delete_original": False,
            # Any change to the source action requires renewed unattended consent.
            "task_schedule_allow_source_backup": False,
        }
        update = getattr(self.config_manager, "update", None)
        if callable(update):
            update(values)
        else:
            for key, value in values.items():
                self.config_manager.set(key, value)
        self._update_source_action_ui()

    def open_backup_recovery(self):
        current_source = self.src_entry.text().strip()
        if not os.path.isdir(current_source):
            current_source = self.config_manager.get("last_bypass_source_directory", "")
        dialog = BackupRecoveryDialog(self.config_manager, current_source, self)
        dialog.exec()
        if dialog.restored_any and os.path.normcase(dialog.source_folder) == os.path.normcase(current_source):
            self.scan_source_folder()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = os.path.normpath(url.toLocalFile())
            if os.path.isdir(file_path):
                self.set_source_folder_path(file_path)
                self.log_area.append(self._msg("bypass_drop_source", path=file_path))
                self.scan_source_folder()
                break

    def toggle_target_mode(self):
        is_custom = self.radio_custom.isChecked()
        self.tgt_layout_widget.setVisible(is_custom)
        self.config_manager.set("bypass_output_mode", "custom" if is_custom else "inplace")
        self._update_source_action_ui()
        self._invalidate_scan()

    def _update_source_action_ui(self):
        if not hasattr(self, "source_action_hint"):
            return
        inplace = self.radio_inplace.isChecked()
        available = not self.is_running and not self._ui_locked
        self.check_backup_orig.setEnabled(available and not inplace)
        if inplace:
            self.source_action_hint.setText(self._t(
                "Source replacement: after output validation, the old source goes to the Recycle Bin. If unavailable, permanent deletion is used. This action runs only from this screen.",
                "원본 교체: 출력 검증 후 기존 원본을 휴지통으로 이동하며, 휴지통을 사용할 수 없을 때만 영구 삭제합니다. 현재 화면에서 직접 실행할 때만 동작합니다.",
                "Zastąpienie źródła: po weryfikacji stare źródło trafia do Kosza; gdy jest niedostępny, używane jest trwałe usunięcie. Akcja działa tylko na tym ekranie.",
            ))
            self.source_action_hint.setStyleSheet(
                "background-color: #3f2d16; color: #fde68a; border: 1px solid #d97706; "
                "padding: 8px; border-radius: 4px; font-weight: bold;"
            )
            self.check_backup_orig.setToolTip(self._t(
                "Original Backup is available only when saving to a separate folder.",
                "Original Backup은 별도 저장 폴더 모드에서만 사용할 수 있습니다.",
                "Original Backup jest dostępny tylko przy zapisie do osobnego folderu.",
            ))
            self.start_btn.setText(self._t(
                "Convert and Replace Sources",
                "변환 후 원본 교체",
                "Konwertuj i zastąp źródła",
            ))
        else:
            backup_enabled = self.check_backup_orig.isChecked()
            self.source_action_hint.setText(self._t(
                "Separate output: source files will be moved to Original Backup after validation."
                if backup_enabled else "Separate output: source files will remain unchanged.",
                "별도 저장: 검증 후 원본을 Original Backup으로 이동합니다."
                if backup_enabled else "별도 저장: 원본 파일은 변경하지 않고 그대로 보존합니다.",
                "Osobny wynik: po weryfikacji źródła trafią do Original Backup."
                if backup_enabled else "Osobny wynik: pliki źródłowe pozostaną bez zmian.",
            ))
            self.source_action_hint.setStyleSheet(
                "background-color: #152e2a; color: #a7f3d0; border: 1px solid #059669; "
                "padding: 8px; border-radius: 4px;"
            )
            self.check_backup_orig.setToolTip("")
            self.start_btn.setText(self._t("Start File Conversion", "파일 변환 시작", "Rozpocznij konwersję plików"))
        
    def select_source_folder(self):
        initial = self.config_manager.get("last_bypass_source_directory", "")
        folder = QFileDialog.getExistingDirectory(self, self._msg("bypass_select_source"), initial)
        if folder:
            self.set_source_folder_path(os.path.normpath(folder))
            self.scan_source_folder()
            
    def select_target_folder(self):
        initial = self.config_manager.get("last_bypass_target_directory", "")
        folder = QFileDialog.getExistingDirectory(self, self._msg("bypass_select_target"), initial)
        if folder:
            self.set_target_folder_path(os.path.normpath(folder))
            
    def set_source_folder_path(self, path):
        if self.src_entry.text() != path:
            self._invalidate_scan()
        self.src_entry.setText(path)
        self.src_entry.setStyleSheet(
            "background-color: #1e1e1e; color: #cbd5e1; border: 1px solid #334155; "
            "padding: 8px; border-radius: 4px; font-weight: bold;"
        )
        self.config_manager.set("last_bypass_source_directory", path)
        self._refresh_action_state()
        
    def set_target_folder_path(self, path):
        self.tgt_entry.setText(path)
        self.tgt_entry.setStyleSheet(
            "background-color: #1e1e1e; color: #cbd5e1; border: 1px solid #334155; "
            "padding: 8px; border-radius: 4px; font-weight: bold;"
        )
        self.config_manager.set("last_bypass_target_directory", path)
        self._refresh_action_state()

    def _source_is_ready(self):
        return os.path.isdir(self.src_entry.text().strip())

    def _target_is_ready(self):
        return self.radio_inplace.isChecked() or os.path.isdir(self.tgt_entry.text().strip())

    def _target_extension_for_source(self, source_ext):
        source_ext = source_ext.lower()
        if source_ext in ('.xlsx', '.xls', '.xlsm'):
            return self.excel_combo.currentText()
        if source_ext in ('.pptx', '.ppt', '.pptm'):
            return self.ppt_combo.currentText()
        if source_ext in ('.docx', '.doc', '.docm'):
            return self.word_combo.currentText()
        if source_ext == '.pdf':
            return self.pdf_combo.currentText()
        return ""

    def _invalidate_scan(self, *_args):
        self.scanned_files.clear()
        if hasattr(self, "file_table"):
            self.file_table.setRowCount(0)
            self.summary_label.setText(self._t("Files found: 0", "검색된 대상 파일: 0개", "Znalezione pliki: 0"))
            self._refresh_action_state()

    def _refresh_action_state(self):
        source_ready = self._source_is_ready()
        target_ready = self._target_is_ready()
        available = not self.is_running and not self._ui_locked
        self.scan_btn.setEnabled(available and source_ready)
        self.start_btn.setEnabled(available and source_ready and target_ready and bool(self.scanned_files))
        if not source_ready:
            scan_reason = self._t("Step 1: select a valid source folder.", "1단계: 올바른 원본 폴더를 선택하세요.", "Krok 1: wybierz prawidłowy folder źródłowy.")
            start_reason = scan_reason
            self.workflow_widget.reset()
        elif not target_ready:
            scan_reason = self._t("Source is ready to scan.", "원본 폴더를 스캔할 수 있습니다.", "Folder źródłowy jest gotowy do skanowania.")
            start_reason = self._t("Step 1: select the custom output folder.", "1단계: 별도 저장 폴더를 선택하세요.", "Krok 1: wybierz niestandardowy folder wyjściowy.")
            self.workflow_widget.set_active_step(0)
        elif not self.scanned_files:
            scan_reason = self._t("Ready to scan.", "스캔할 준비가 되었습니다.", "Gotowe do skanowania.")
            start_reason = self._t("Step 1: scan and review the source files first.", "1단계: 원본 파일을 먼저 스캔하고 확인하세요.", "Krok 1: najpierw przeskanuj i sprawdź pliki źródłowe.")
            if available:
                self.workflow_widget.set_active_step(0)
        else:
            scan_reason = self._t("Refresh the file scan.", "파일 목록을 다시 스캔합니다.", "Odśwież skan plików.")
            start_reason = self._t("Scan complete. Ready to convert.", "스캔 완료. 변환을 실행할 수 있습니다.", "Skan zakończony. Można konwertować.")
            if available:
                self.workflow_widget.set_active_step(1)
        self.scan_btn.setToolTip(scan_reason)
        self.start_btn.setToolTip(start_reason)

    def scan_source_folder(self):
        src_dir = self.src_entry.text()
        if not os.path.exists(src_dir) or src_dir.startswith(("드래그 앤 드롭", "Drag a folder", "Przeciągnij folder")):
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("Select a valid source folder first.", "올바른 소스 폴더를 먼저 선택해 주세요.", "Najpierw wybierz prawidłowy folder źródłowy."))
            return
            
        self.scanned_files.clear()
        self.file_table.setRowCount(0)
        self.log_area.clear()
        self.progress_bar.setValue(0)
        self.workflow_widget.reset()
        
        self.log_area.append(self._msg("bypass_scanning"))
        
        target_extensions = ('.xlsx', '.xls', '.xlsm', '.pptx', '.ppt', '.pptm', '.docx', '.doc', '.docm', '.pdf')
        already_target_count = 0
        
        try:
            # 1단계 직계 파일만 검색 (Spaghetti 방지 및 간단성 유지)
            for file_name in os.listdir(src_dir):
                file_path = os.path.join(src_dir, file_name)
                if os.path.isfile(file_path):
                    _, ext = os.path.splitext(file_name.lower())
                    if ext in target_extensions:
                        if self.radio_inplace.isChecked() and ext == self._target_extension_for_source(ext):
                            already_target_count += 1
                            continue
                        self.scanned_files.append(file_path)
                        
            # 테이블 채우기
            self.file_table.setRowCount(len(self.scanned_files))
            for idx, file_path in enumerate(self.scanned_files):
                filename = os.path.basename(file_path)
                size_bytes = os.path.getsize(file_path)
                size_kb = f"{size_bytes / 1024:.1f} KB"
                
                # 원본 종류 판별 및 우회 종류 매칭
                _, ext = os.path.splitext(filename.lower())
                tgt_ext = self._target_extension_for_source(ext)
                
                # 테이블 열 세팅
                self.file_table.setItem(idx, 0, QTableWidgetItem(filename))
                self.file_table.setItem(idx, 1, QTableWidgetItem(size_kb))
                self.file_table.setItem(idx, 2, QTableWidgetItem(tgt_ext))
                self.file_table.setItem(idx, 3, QTableWidgetItem(self._msg("common_waiting")))
                
            file_count = len(self.scanned_files)
            self.summary_label.setText(self._t(f"Files found: {file_count}", f"검색된 대상 파일: {file_count}개", f"Znalezione pliki: {file_count}"))
            self.log_area.append(self._msg("bypass_scan_complete", count=len(self.scanned_files)))
            if already_target_count:
                self.log_area.append(self._t(
                    f"ℹ️ Skipped {already_target_count} file(s) already in the selected target format; in-place replacement never performs same-format rewrites.",
                    f"ℹ️ 선택한 대상 형식과 이미 같은 파일 {already_target_count}개를 제외했습니다. 원본 교체 모드는 같은 형식으로 다시 변환하지 않습니다.",
                    f"ℹ️ Pominięto {already_target_count} plik(i) już w wybranym formacie; zastępowanie nie przepisuje plików w tym samym formacie.",
                ))
            self.workflow_widget.set_active_step(1)
            self._refresh_action_state()
            
        except Exception as e:
            self.log_area.append(self._msg("bypass_scan_failed_log", detail=str(e)))
            QMessageBox.critical(self, self._msg("common_error"), self._msg("bypass_scan_failed", detail=str(e)))

    def start_conversion(self):
        if not self.scanned_files:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("No files are ready. Scan the source folder first.", "변환할 대상 파일이 없습니다. 스캔을 먼저 실행해 주세요.", "Brak plików gotowych do konwersji. Najpierw przeskanuj folder źródłowy."))
            return
            
        # 설정값 실시간 캐시 동기화
        self.config_manager.set("bypass_excel_target", self.excel_combo.currentText())
        self.config_manager.set("bypass_ppt_target", self.ppt_combo.currentText())
        self.config_manager.set("bypass_word_target", self.word_combo.currentText())
        self.config_manager.set("bypass_pdf_target", self.pdf_combo.currentText())
        disposition = SourceDisposition.BACKUP if self.check_backup_orig.isChecked() else SourceDisposition.KEEP
        self.config_manager.set("bypass_source_disposition", disposition.value)
        self.config_manager.set("bypass_output_mode", "inplace" if self.radio_inplace.isChecked() else "custom")
        self.config_manager.set("bypass_delete_original", False)
        self.config_manager.set("bypass_preserve_meta", self.check_preserve_meta.isChecked())
        
        try:
            run_config = self.build_run_config()
        except TaskValidationError as exc:
            problem = tr(exc.message_key, self.language, **exc.values) if exc.message_key else exc.user_message
            QMessageBox.warning(self, self._msg("bypass_settings_error"), problem)
            return

        if run_config is None:
            QMessageBox.warning(self, self._msg("common_warning"), self._msg("bypass_scan_first"))
            return

        preflight, preflight_error, preflight_cancelled = run_bounded_preflight(
            self,
            RunPlan({TaskStep.BYPASS: run_config}),
            self.config_manager,
            auto_email=False,
            visible=True,
        )
        if preflight is None:
            detail = self._t(
                "Preflight was cancelled. No conversion was started."
                if preflight_cancelled else f"Preflight could not be completed: {preflight_error}",
                "실행 전 점검을 취소했습니다. 변환은 시작되지 않았습니다."
                if preflight_cancelled else f"실행 전 점검을 완료하지 못했습니다: {preflight_error}",
                "Anulowano kontrolę. Konwersja nie została uruchomiona."
                if preflight_cancelled else f"Nie można ukończyć kontroli: {preflight_error}",
            )
            QMessageBox.warning(self, self._t("Preflight Check", "실행 전 점검", "Kontrola przed uruchomieniem"), detail)
            return
        if preflight.has_blockers:
            QMessageBox.critical(self, self._msg("bypass_preflight_failed"), preflight.format(include_warnings=False, language=self.language))
            return

        if not self._confirm_source_action(run_config):
            self.log_area.append(self._t("Source action was cancelled.", "원본 처리 작업을 취소했습니다.", "Anulowano akcję na źródłach."))
            return

        tasks = [task.to_legacy_dict() for task in run_config.tasks]
            
        self.is_running = True
        self._refresh_action_state()
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        self.log_area.append(self._msg("bypass_starting"))
        self.workflow_widget.set_active_step(1)
        
        # 워커 실행
        self.worker = BypassConvertWorker(tasks, self.converter, self.language)
        self.worker.progress.connect(self.update_progress)
        self.worker.file_completed.connect(self.on_file_completed)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()
        
    def stop_conversion(self):
        if self.worker:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self.log_area.append(self._msg("bypass_stop_requested"))
            
    def stop_all(self):
        """MainWindow 종료 시 바인딩"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()

    def update_progress(self, current, total, status_msg):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.log_area.append(f"🔄 {status_msg}")
        if parent_win := self.window():
            if hasattr(parent_win, 'status_bar'):
                parent_win.status_bar.showMessage(status_msg)
                
    def on_file_completed(self, src_path, tgt_path, success, message):
        filename = os.path.basename(src_path)
        tgt_name = os.path.basename(tgt_path)
        
        for idx in range(self.file_table.rowCount()):
            if self.file_table.item(idx, 0).text() == filename:
                if success:
                    self.file_table.setItem(idx, 3, QTableWidgetItem(self._msg("common_completed")))
                    self.file_table.item(idx, 3).setForeground(Qt.GlobalColor.green)
                    detail = self._converter_message(message)
                    self.log_area.append(self._msg("bypass_log_success", source=filename, target=tgt_name) + f" — {detail}")
                else:
                    message = self._converter_message(message)
                    self.file_table.setItem(idx, 3, QTableWidgetItem(self._msg("bypass_failed_status", detail=message)))
                    self.file_table.item(idx, 3).setForeground(Qt.GlobalColor.red)
                    self.log_area.append(self._msg("bypass_log_failed", filename=filename, detail=message))
                break
                
        self.workflow_widget.set_active_step(2)

    def on_finished(self, success, message):
        self.is_running = False
        self.stop_btn.setEnabled(False)
        
        if success:
            self.log_area.append(f"\n✅ {message}")
            show_toast(self, self._msg("bypass_completed"), "success")
            QMessageBox.information(self, self._msg("common_completed"), message)
        else:
            self.workflow_widget.reset()
            message = self._error_text(message)
            self.log_area.append(self._msg("bypass_operation_stopped", detail=message))
            show_toast(self, self._msg("bypass_operation_failed", detail=message), "error")
            QMessageBox.critical(self, self._msg("common_error"), self._msg("bypass_operation_error", detail=message))
            
        # 스캔 리스트 리프레시 (원본 파일이 백업 폴더로 이동했을 수 있으므로)
        self.scan_source_folder()
        if success:
            self.workflow_widget.complete_all()

    def build_run_config(self):
        src_dir = self.src_entry.text().strip()
        if not src_dir or src_dir.startswith(("드래그 앤 드롭", "Drag a folder")):
            return None
            
        if not os.path.exists(src_dir):
            raise TaskValidationError(
                f"파일 변환 원본 폴더가 존재하지 않습니다: {src_dir}",
                message_key="bypass_source_folder_missing",
                values={"path": src_dir},
            )
            
        if not self.scanned_files:
            raise TaskValidationError(
                "파일 변환은 먼저 '대상 파일 스캔'을 실행한 뒤 통합 작업을 시작해 주세요.",
                message_key="bypass_scan_required",
            )
            
        inplace_mode = self.radio_inplace.isChecked()
        tgt_dir = src_dir if inplace_mode else self.tgt_entry.text().strip()
        
        if not inplace_mode and (not tgt_dir or tgt_dir.startswith(("저장할 우회", "Choose the folder"))):
            raise TaskValidationError(
                "파일 변환 저장 폴더가 지정되지 않았습니다.",
                message_key="bypass_target_folder_empty",
            )
            
        if not inplace_mode and not os.path.exists(tgt_dir):
            raise TaskValidationError(
                f"파일 변환 저장 폴더가 존재하지 않습니다: {tgt_dir}",
                message_key="bypass_target_folder_missing",
                values={"path": tgt_dir},
            )
            
        # 작업 리스트 작성
        tasks = []
        reserved_targets = set()
        source_disposition = (
            SourceDisposition.REPLACE
            if inplace_mode
            else SourceDisposition.BACKUP if self.check_backup_orig.isChecked() else SourceDisposition.KEEP
        )
        for idx in range(self.file_table.rowCount()):
            filename = self.file_table.item(idx, 0).text()
            src_file = os.path.join(src_dir, filename)
            if not os.path.exists(src_file):
                raise TaskValidationError(
                    f"파일 변환 원본 파일이 존재하지 않습니다: {src_file}",
                    message_key="bypass_source_file_missing",
                    values={"path": src_file},
                )
            
            tgt_ext = self.file_table.item(idx, 2).text()
            name_no_ext, _ = os.path.splitext(filename)
            tgt_filename = f"{name_no_ext}{tgt_ext}"
            tgt_file = os.path.join(tgt_dir, tgt_filename)

            normalized_target = os.path.normcase(os.path.abspath(tgt_file))
            normalized_source = os.path.normcase(os.path.abspath(src_file))
            same_as_source = normalized_target == normalized_source
            if same_as_source:
                tgt_filename = f"{name_no_ext}_converted{tgt_ext}"
                tgt_file = os.path.join(tgt_dir, tgt_filename)
                normalized_target = os.path.normcase(os.path.abspath(tgt_file))
                suffix = "_converted"
                counter = 1
                while os.path.exists(tgt_file) or normalized_target in reserved_targets:
                    tgt_filename = f"{name_no_ext}{suffix}_{counter}{tgt_ext}"
                    tgt_file = os.path.join(tgt_dir, tgt_filename)
                    normalized_target = os.path.normcase(os.path.abspath(tgt_file))
                    counter += 1
            elif os.path.exists(tgt_file) or normalized_target in reserved_targets:
                counter = 1
                while True:
                    tgt_filename = f"{name_no_ext}_{counter}{tgt_ext}"
                    tgt_file = os.path.join(tgt_dir, tgt_filename)
                    normalized_target = os.path.normcase(os.path.abspath(tgt_file))
                    if not os.path.exists(tgt_file) and normalized_target not in reserved_targets:
                        break
                    counter += 1

            reserved_targets.add(normalized_target)
                    
            tasks.append(BypassFileConfig(
                src=src_file,
                tgt=tgt_file,
                ext=tgt_ext,
                preserve_meta=self.check_preserve_meta.isChecked(),
                source_disposition=source_disposition,
            ))
            
        return BypassRunConfig(tasks=tasks, source_disposition=source_disposition)

    def get_task_info(self):
        config = self.build_run_config()
        return config.to_legacy_dict() if config else None
        
    def set_ui_locked(self, locked):
        self._ui_locked = locked
        for btn in self.findChildren(QPushButton):
            if btn not in (self.stop_btn,):
                btn.setEnabled(not locked)
        self.file_table.setEnabled(not locked)
        self.radio_inplace.setEnabled(not locked)
        self.radio_custom.setEnabled(not locked)
        self.excel_combo.setEnabled(not locked)
        self.ppt_combo.setEnabled(not locked)
        self.word_combo.setEnabled(not locked)
        self.pdf_combo.setEnabled(not locked)
        self.check_backup_orig.setEnabled(not locked and self.radio_custom.isChecked())
        self.check_preserve_meta.setEnabled(not locked)
        self._update_source_action_ui()
        self._refresh_action_state()
