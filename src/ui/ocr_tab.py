import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QProgressBar,
    QFileDialog, QMessageBox, QListWidgetItem, QGroupBox, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.ui.workflow_widget import WorkflowWidget
from src.ui.toast_notification import show_toast
from src.ui.image_preview_dialog import ImagePreviewDialog
from src.ui.i18n import choose, get_app_language

from src.core.ocr_processor import OCRProcessor
from src.core.file_manager import FileManager
from src.core.task_contracts import OcrRunConfig, TaskValidationError
from src.utils.logger import get_logger

logger = get_logger()

class OCRWorker(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, status_msg
    ocr_completed = pyqtSignal(str, str, str, bool, str)  # original_path, new_path, promo_num, success, ocr_text
    finished = pyqtSignal(bool, str)      # success, message
    
    def __init__(self, image_paths, ocr_processor, file_manager, language="en"):
        super().__init__()
        self.image_paths = image_paths
        self.ocr_processor = ocr_processor
        self.file_manager = file_manager
        self.is_running = True
        self.language = language

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def _detail(self, value):
        text = str(value)
        if self.language != "ko":
            text = text.replace("프로모션 번호를 찾을 수 없습니다", "Promotion number not found")
            text = text.replace("OCR 텍스트 추출 실패", "OCR text extraction failed")
            text = text.replace("Tesseract 실패", "Tesseract failed")
            text = text.replace("Windows OCR 실패", "Windows OCR failed")
        return text
        
    def stop(self):
        self.is_running = False
        
    def run(self):
        try:
            # 1. OCR 엔진 확인: Tesseract 우선, 없으면 Windows 내장 OCR fallback
            if not self.ocr_processor.check_ocr_available():
                self.finished.emit(False, self._t("No OCR engine is available. Install Tesseract or check the Windows OCR language pack.", "사용 가능한 OCR 엔진이 없습니다. Tesseract를 설치하거나 Windows OCR 언어팩을 확인하세요."))
                return
                
            total_images = len(self.image_paths)
            success_count = 0
            
            for idx, img_path in enumerate(self.image_paths):
                if not self.is_running:
                    self.finished.emit(False, self._t("Cancelled by the user.", "사용자에 의해 취소되었습니다."))
                    return
                
                filename = os.path.basename(img_path)
                self.progress.emit(idx, total_images, self._t(f"Running OCR: {filename}", f"OCR 분석 중: {filename}"))
                
                try:
                    # OCR 판독
                    success, promo_num, ocr_text, error_msg = self.ocr_processor.process_image(img_path)
                    
                    if success and promo_num:
                        # 파일명 변경 시도 (Collision Protection 포함)
                        ext = os.path.splitext(filename)[1]
                        dir_path = os.path.dirname(img_path)
                        
                        # 고유 이름 생성
                        new_name = f"{promo_num}{ext}"
                        target_path = os.path.join(dir_path, new_name)
                        
                        # 충돌 방지: 파일이 이미 존재하면 카운터 접미사 붙임
                        if os.path.exists(target_path) and target_path != img_path:
                            counter = 1
                            while True:
                                new_name = f"{promo_num}_{counter}{ext}"
                                target_path = os.path.join(dir_path, new_name)
                                if not os.path.exists(target_path):
                                    break
                                counter += 1
                        
                        # os.rename 실행
                        if target_path != img_path:
                            # 만약 기존 파일이 읽기전용이라면 쓰기 권한 추가
                            if os.path.exists(target_path):
                                try:
                                    os.chmod(target_path, 0o777)
                                    os.remove(target_path)
                                except Exception as rem_err:
                                    logger.error(f"Cannot overwrite existing path: {rem_err}")
                            
                            os.chmod(img_path, 0o777)
                            os.rename(img_path, target_path)
                            final_path = target_path
                        else:
                            final_path = img_path
                            
                        success_count += 1
                        self.ocr_completed.emit(img_path, final_path, promo_num, True, ocr_text)
                    else:
                        self.ocr_completed.emit(img_path, img_path, "", False, self._detail(error_msg or self._t("Promotion number not found.", "프로모션 번호를 찾지 못했습니다.")))
                        
                except Exception as e:
                    logger.error(f"Failed to process image {img_path}: {e}")
                    self.ocr_completed.emit(img_path, img_path, "", False, str(e))
                    
            self.progress.emit(total_images, total_images, self._t(f"OCR completed ({success_count}/{total_images} successful)", f"OCR 완료 ({success_count}/{total_images} 성공)"))
            self.finished.emit(
                success_count == total_images,
                self._t(f"OCR and renaming completed. (Successful: {success_count} / Total: {total_images})", f"OCR 및 리네임 작업이 완료되었습니다. (성공: {success_count}개 / 전체: {total_images}개)")
            )
            
        except Exception as e:
            logger.error(f"Error in OCRWorker: {e}")
            self.finished.emit(False, str(e))


class OCRTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.ocr_processor = OCRProcessor(self.config_manager)
        self.file_manager = FileManager()
        
        self.image_files = []
        self.ocr_results = {}
        self.is_converting = False
        self.worker = None
        
        self.init_ui()
        self.setAcceptDrops(True)

    @property
    def language(self):
        return get_app_language(self.config_manager)

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def refresh_language(self):
        self.update_summary_labels()
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 1. 워크플로우 인디케이터
        self.workflow_widget = WorkflowWidget(steps=["1. Load Images", "2. Run OCR & Rename", "3. Complete"])
        layout.addWidget(self.workflow_widget)
        
        # 2. 메인 패널 구조 (좌/우 분할)
        main_h_layout = QHBoxLayout()
        
        # 좌측 패널: 대상 이미지 파일 목록
        left_panel = QGroupBox("Target Image Files")
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)
        
        self.image_list_widget = QListWidget()
        self.image_list_widget.itemDoubleClicked.connect(self.preview_image)
        self.image_list_widget.itemChanged.connect(self.update_summary_labels)
        left_layout.addWidget(self.image_list_widget)
        
        self.image_summary_label = QLabel("불러온 이미지: 0개 (선택됨: 0개)")
        left_layout.addWidget(self.image_summary_label)
        
        # 유틸리티 버튼
        select_ctrl_layout = QHBoxLayout()
        select_all_btn = QPushButton("전체 선택")
        select_all_btn.clicked.connect(self.select_all_items)
        deselect_all_btn = QPushButton("전체 해제")
        deselect_all_btn.clicked.connect(self.deselect_all_items)
        select_ctrl_layout.addWidget(select_all_btn)
        select_ctrl_layout.addWidget(deselect_all_btn)
        left_layout.addLayout(select_ctrl_layout)
        
        # 이미지 추가 및 비우기 버튼
        btn_layout = QHBoxLayout()
        add_img_btn = QPushButton("이미지 파일 추가")
        add_img_btn.clicked.connect(self.select_images)
        clear_img_btn = QPushButton("목록 비우기")
        clear_img_btn.clicked.connect(self.clear_images)
        
        btn_layout.addWidget(add_img_btn)
        btn_layout.addWidget(clear_img_btn)
        left_layout.addLayout(btn_layout)
        
        main_h_layout.addWidget(left_panel, 1)
        
        # 우측 패널: OCR 판독 상세 로그 및 제어
        right_panel = QGroupBox("OCR & Rename Logs")
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #1e1e1e; color: #e2e8f0; border: 1px solid #3e3e3e;")
        right_layout.addWidget(self.log_area)
        
        # 진행 제어 영역
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("OCR 및 이름 변경 시작")
        self.start_btn.setProperty("variant", "success")
        self.start_btn.clicked.connect(self.start_ocr)
        
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_ocr)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        right_layout.addLayout(control_layout)
        
        # 진행 바
        self.progress_bar = QProgressBar()
        right_layout.addWidget(self.progress_bar)
        
        main_h_layout.addWidget(right_panel, 1)
        layout.addLayout(main_h_layout)
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = os.path.normpath(url.toLocalFile())
            if file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp')):
                self.add_image_to_list(file_path)
                
    def add_image_to_list(self, file_path):
        if file_path not in self.image_files:
            self.image_files.append(file_path)
            
            # 체크박스 형태의 아이템 생성
            item = QListWidgetItem(os.path.basename(file_path))
            item.setToolTip(file_path)
            item.setData(Qt.ItemDataRole.UserRole, file_path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            
            self.image_list_widget.addItem(item)
            self.config_manager.set("last_ocr_image_directory", os.path.dirname(file_path))
            self.update_summary_labels()
            self.workflow_widget.set_active_step(1)
            

            
    def select_images(self):
        initial_dir = self.config_manager.get("last_ocr_image_directory", "")
        files, _ = QFileDialog.getOpenFileNames(
            self, self._t("Select Image Files", "이미지 파일 다중 선택"), initial_dir, "Image Files (*.jpg *.jpeg *.png *.bmp);;All Files (*)"
        )
        for f in files:
            self.add_image_to_list(os.path.normpath(f))
            
    def clear_images(self):
        self.image_files.clear()
        self.ocr_results.clear()
        self.image_list_widget.clear()
        self.log_area.clear()
        self.workflow_widget.reset()
        self.update_summary_labels()
        
    def select_all_items(self):
        for idx in range(self.image_list_widget.count()):
            item = self.image_list_widget.item(idx)
            item.setCheckState(Qt.CheckState.Checked)
        self.update_summary_labels()
        
    def deselect_all_items(self):
        for idx in range(self.image_list_widget.count()):
            item = self.image_list_widget.item(idx)
            item.setCheckState(Qt.CheckState.Unchecked)
        self.update_summary_labels()
        
    def start_ocr(self):
        # 체크된 이미지 경로들 추출
        checked_paths = []
        for idx in range(self.image_list_widget.count()):
            item = self.image_list_widget.item(idx)
            if item.checkState() == Qt.CheckState.Checked:
                checked_paths.append(item.data(Qt.ItemDataRole.UserRole))
                
        if not checked_paths:
            QMessageBox.warning(self, self._t("Warning", "경고"), self._t("Select at least one image using its checkbox.", "분석을 실행할 이미지 파일을 체크박스에서 먼저 선택해 주세요."))
            return
            
        self.is_converting = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_area.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        
        self.log_area.append(self._t("ℹ️ Starting OCR and renaming...", "ℹ️ OCR 및 이름 변경 작업을 시작합니다..."))
        self.workflow_widget.set_active_step(1)
        
        self.worker = OCRWorker(
            image_paths=checked_paths,
            ocr_processor=self.ocr_processor,
            file_manager=self.file_manager,
            language=self.language,
        )
        
        self.worker.progress.connect(self.update_progress)
        self.worker.ocr_completed.connect(self.on_ocr_completed)
        self.worker.finished.connect(self.on_ocr_finished)
        self.worker.start()
        
    def stop_ocr(self):
        if self.worker:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self.log_area.append(self._t("⚠️ Stop requested.", "⚠️ 작업 중지 요청을 전송했습니다."))
            
    def stop_all(self):
        """MainWindow 종료 시 연동될 안전 취소 헬퍼"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            
    def update_progress(self, current, total, status_msg):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}% ({current}/{total})")
        self.log_area.append(f"🔄 {status_msg}")
        if parent_win := self.window():
            if hasattr(parent_win, 'status_bar'):
                parent_win.status_bar.showMessage(status_msg)
                
    def on_ocr_completed(self, original_path, new_path, promo_num, success, ocr_text):
        # 1. 캐시 및 리스트 데이터 갱신
        self.ocr_results[new_path] = (success, promo_num, ocr_text, None if success else self._t("Recognition failed", "판독 실패"))
        
        # 2. image_files의 원래 경로를 새로운 경로로 교체
        if original_path in self.image_files:
            idx = self.image_files.index(original_path)
            self.image_files[idx] = new_path
            
        # 3. GUI 아이템 상태 갱신
        orig_filename = os.path.basename(original_path)
        new_filename = os.path.basename(new_path)
        
        for idx in range(self.image_list_widget.count()):
            item = self.image_list_widget.item(idx)
            if item.data(Qt.ItemDataRole.UserRole) == original_path:
                item.setData(Qt.ItemDataRole.UserRole, new_path)
                if success:
                    item.setText(self._t(f"{new_filename} [Success: {promo_num}]", f"{new_filename} [성공: {promo_num}]"))
                    self.log_area.append(self._t(f"🟢 [Success] {orig_filename} -> {new_filename}", f"🟢 [성공] {orig_filename} -> {new_filename}"))
                else:
                    item.setText(self._t(f"{orig_filename} [Recognition failed]", f"{orig_filename} [판독 실패]"))
                    self.log_area.append(self._t(f"🔴 [Failed] {orig_filename}: {ocr_text}", f"🔴 [실패] {orig_filename}: {ocr_text}"))
                break
                
        self.update_summary_labels()
        self.workflow_widget.set_active_step(2)
        
    def on_ocr_finished(self, success, message):
        self.is_converting = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.update_summary_labels()
        
        if success:
            self.workflow_widget.complete_all()
            self.log_area.append(f"\n✅ {message}")
            show_toast(self, self._t("OCR completed.", "OCR 작업 성공!"), "success")
            QMessageBox.information(self, self._t("Completed", "완료"), message)
        else:
            self.workflow_widget.reset()
            self.log_area.append(self._t(f"\n❌ Operation stopped: {message}", f"\n❌ 작업 중단: {message}"))
            show_toast(self, self._t(f"Operation failed: {message}", f"작업 실패: {message}"), "error")
            QMessageBox.critical(self, self._t("Error", "오류"), self._t(f"An error occurred: {message}", f"작업 중 오류 발생: {message}"))
            
    def preview_image(self, item):
        img_path = item.data(Qt.ItemDataRole.UserRole)
        if img_path and os.path.exists(img_path):
            try:
                current_idx = self.image_files.index(img_path)
            except ValueError:
                current_idx = 0
                
            dialog = ImagePreviewDialog(self, self.image_files, current_idx, self.ocr_results)
            dialog.exec()

    def update_summary_labels(self):
        total = len(self.image_files)
        checked = 0
        
        # itemChanged 커넥션 루프 도중 UI 소멸 시의 방어 코드
        try:
            for idx in range(self.image_list_widget.count()):
                item = self.image_list_widget.item(idx)
                if item.checkState() == Qt.CheckState.Checked:
                    checked += 1
        except RuntimeError:
            pass
            
        self.image_summary_label.setText(self._t(f"Images: {total} (selected: {checked})", f"불러온 이미지: {total}개 (선택됨: {checked}개)"))

    def build_run_config(self):
        checked_paths = []
        for idx in range(self.image_list_widget.count()):
            item = self.image_list_widget.item(idx)
            if item.checkState() == Qt.CheckState.Checked:
                checked_paths.append(item.data(Qt.ItemDataRole.UserRole))
                
        if not checked_paths:
            return None
            
        if not self.ocr_processor.check_ocr_available():
            raise TaskValidationError(
                "사용 가능한 OCR 엔진이 없습니다. Tesseract를 설치하거나 Windows OCR 언어팩을 확인하세요.",
                message_key="ocr_engine_missing",
            )
            
        # 이미지 파일들의 실제 존재 여부 검사
        for path in checked_paths:
            if not os.path.exists(path):
                raise TaskValidationError(
                    f"분석할 이미지 파일이 존재하지 않습니다: {path}",
                    message_key="ocr_file_missing",
                    values={"path": path},
                )
                
        return OcrRunConfig(image_paths=checked_paths)

    def get_task_info(self):
        config = self.build_run_config()
        return config.to_legacy_dict() if config else None
        
    def set_ui_locked(self, locked):
        for btn in self.findChildren(QPushButton):
            if btn not in (self.stop_btn,):
                btn.setEnabled(not locked)
        self.image_list_widget.setEnabled(not locked)
