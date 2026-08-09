import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QProgressBar,
    QFileDialog, QMessageBox, QListWidgetItem, QLineEdit, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.ui.workflow_widget import WorkflowWidget
from src.ui.toast_notification import show_toast
from src.ui.image_preview_dialog import ImagePreviewDialog
from src.ui.i18n import choose, get_app_language

from src.core.pdf_converter import PDFConverter
from src.core.file_manager import FileManager
from src.core.task_contracts import PdfRunConfig, TaskValidationError
from src.utils.logger import get_logger

logger = get_logger()

class PDFConvertWorker(QThread):
    progress = pyqtSignal(int, int, str) # current, total, status_msg
    page_converted = pyqtSignal(int, str) # page_num, image_path
    finished = pyqtSignal(bool, str) # success, message
    
    def __init__(self, pdf_paths, output_folder, pdf_converter, file_manager, language="en"):
        super().__init__()
        self.pdf_paths = pdf_paths
        self.output_folder = output_folder
        self.pdf_converter = pdf_converter
        self.file_manager = file_manager
        self.is_running = True
        self.language = language

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)

    def stop(self):
        self.is_running = False
        
    def run(self):
        try:
            total_files = len(self.pdf_paths)
            for file_idx, pdf_path in enumerate(self.pdf_paths):
                if not self.is_running:
                    self.finished.emit(False, self._t("Cancelled by the user.", "사용자에 의해 취소되었습니다."))
                    return
                
                self.progress.emit(file_idx, total_files, self._t(f"Converting PDF: {os.path.basename(pdf_path)}", f"PDF 변환 중: {os.path.basename(pdf_path)}"))
                
                # PDF to Image 변환
                image_paths = self.pdf_converter.convert(pdf_path, self.output_folder)
                
                for page_idx, img_path in enumerate(image_paths):
                    if not self.is_running:
                        self.finished.emit(False, self._t("Cancelled by the user.", "사용자에 의해 취소되었습니다."))
                        return
                    
                    self.page_converted.emit(page_idx + 1, img_path)
                    
            self.progress.emit(total_files, total_files, self._t("All PDF files were converted successfully.", "모든 PDF 변환이 성공적으로 완료되었습니다."))
            self.finished.emit(True, self._t("Conversion completed successfully.", "변환이 성공적으로 완료되었습니다."))
        except Exception as e:
            logger.error(f"Error in PDFConvertWorker: {e}")
            self.finished.emit(False, str(e))


class PDFTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.pdf_converter = PDFConverter(self.config_manager)
        self.file_manager = FileManager()
        
        self.selected_pdf_paths = []
        self.image_files = []
        self.ocr_results = {}  # 미리보기 다이얼로그 호환성용 빈 딕셔너리
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
        self.workflow_widget.set_step_texts([
            self._t("1. Select PDF", "1. PDF 선택", "1. Wybierz PDF"),
            self._t("2. Convert Images", "2. 이미지 변환", "2. Konwertuj obrazy"),
            self._t("3. Complete", "3. 완료", "3. Zakończ"),
        ])
        self.update_summary_labels()
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 1. 워크플로우 인디케이터 (PDF 변환 전용 단계를 전달)
        self.workflow_widget = WorkflowWidget(steps=["1. Select PDF", "2. Convert Image", "3. Complete"])
        layout.addWidget(self.workflow_widget)
        
        # 2. 메인 패널 구조 (좌/우 분할)
        main_h_layout = QHBoxLayout()
        
        # 좌측 패널: PDF 파일 선택 및 리스트
        left_panel = QGroupBox("PDF Input Files")
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)
        
        self.pdf_list_widget = QListWidget()
        left_layout.addWidget(self.pdf_list_widget)
        self.pdf_summary_label = QLabel("선택된 PDF: 0개")
        left_layout.addWidget(self.pdf_summary_label)
        
        btn_layout = QHBoxLayout()
        add_pdf_btn = QPushButton("PDF 추가")
        add_pdf_btn.clicked.connect(self.select_pdfs)
        clear_pdf_btn = QPushButton("목록 비우기")
        clear_pdf_btn.clicked.connect(self.clear_pdfs)
        
        btn_layout.addWidget(add_pdf_btn)
        btn_layout.addWidget(clear_pdf_btn)
        left_layout.addLayout(btn_layout)
        
        # 출력 경로 설정
        path_layout = QHBoxLayout()
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("출력 저장 폴더를 선택하세요")
        self.output_path_input.setReadOnly(True)
        browse_output_btn = QPushButton("출력 폴더")
        browse_output_btn.clicked.connect(self.select_output_folder)
        
        path_layout.addWidget(self.output_path_input)
        path_layout.addWidget(browse_output_btn)
        left_layout.addLayout(path_layout)
        
        # 기본 저장경로 로드
        default_out = self.config_manager.get(
            "output_folder",
            os.path.join(os.path.expanduser("~"), "Documents", "PDF_Output")
        )
        if not default_out:
            default_out = os.path.join(os.path.expanduser("~"), "Documents", "PDF_Output")
        self.output_path_input.setText(default_out)
        
        main_h_layout.addWidget(left_panel, 1)
        
        # 우측 패널: 변환 결과 이미지 및 상세 정보
        right_panel = QGroupBox("Conversion Results")
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        
        self.image_list_widget = QListWidget()
        self.image_list_widget.itemDoubleClicked.connect(self.preview_image)
        right_layout.addWidget(self.image_list_widget)
        self.result_summary_label = QLabel("생성 이미지: 0개")
        right_layout.addWidget(self.result_summary_label)
        
        # 진행 제어 영역
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("변환 시작")
        self.start_btn.setProperty("variant", "success")
        self.start_btn.clicked.connect(self.start_conversion)
        
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_conversion)
        
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
            if file_path.lower().endswith('.pdf'):
                self.add_pdf_to_list(file_path)
                
    def add_pdf_to_list(self, file_path):
        if file_path not in self.selected_pdf_paths:
            self.selected_pdf_paths.append(file_path)
            item = QListWidgetItem(os.path.basename(file_path))
            item.setToolTip(file_path)
            item.setData(Qt.ItemDataRole.UserRole, file_path)
            self.pdf_list_widget.addItem(item)
            self.config_manager.set("last_pdf_directory", os.path.dirname(file_path))
            self.update_summary_labels()
            self.workflow_widget.set_active_step(1)
            
    def select_pdfs(self):
        initial_dir = self.config_manager.get("last_pdf_directory", "")
        files, _ = QFileDialog.getOpenFileNames(
            self, self._t("Select PDF Files", "PDF 파일 다중 선택"), initial_dir, "PDF Files (*.pdf);;All Files (*)"
        )
        for f in files:
            self.add_pdf_to_list(os.path.normpath(f))
            
    def clear_pdfs(self):
        self.selected_pdf_paths.clear()
        self.pdf_list_widget.clear()
        self.workflow_widget.reset()
        self.update_summary_labels()
        
    def select_output_folder(self):
        current_folder = self.output_path_input.text().strip()
        folder = QFileDialog.getExistingDirectory(self, self._t("Select Output Folder", "출력 저장 폴더 선택"), current_folder)
        if folder:
            normalized = os.path.normpath(folder)
            self.output_path_input.setText(normalized)
            self.config_manager.set("output_folder", normalized)
            
    def start_conversion(self):
        if not self.selected_pdf_paths:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("Add at least one PDF file first.", "변환할 PDF 파일을 먼저 추가해 주세요.", "Najpierw dodaj co najmniej jeden plik PDF."))
            return
            
        output_folder = self.output_path_input.text().strip()
        if not output_folder:
            QMessageBox.warning(self, self._t("Warning", "경고", "Ostrzeżenie"), self._t("Select an output folder.", "출력 저장 폴더를 지정해 주세요.", "Wybierz folder wyjściowy."))
            return
            
        os.makedirs(output_folder, exist_ok=True)
        self.config_manager.set("output_folder", output_folder)
        
        self.is_converting = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.image_list_widget.clear()
        self.image_files.clear()
        self.ocr_results.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.result_summary_label.setText(self._t("Preparing conversion...", "변환 준비 중"))
        
        self.workflow_widget.set_active_step(2)
        
        # 백그라운드 Worker 스레드 구동
        self.worker = PDFConvertWorker(
            pdf_paths=self.selected_pdf_paths,
            output_folder=output_folder,
            pdf_converter=self.pdf_converter,
            file_manager=self.file_manager,
            language=self.language,
        )
        
        self.worker.progress.connect(self.update_progress)
        self.worker.page_converted.connect(self.on_page_converted)
        self.worker.finished.connect(self.on_conversion_finished)
        self.worker.start()
        
    def stop_conversion(self):
        if self.worker:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            logger.info("PDF 변환 중지 요청을 보냈습니다.")
            
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
                parent_win.status_bar.showMessage(status_msg)
                
    def on_page_converted(self, page_num, image_path):
        self.image_files.append(image_path)
        
        # 이미지 리스트 아이템 추가
        filename = os.path.basename(image_path)
        item_text = self._t(f"Page {page_num}: {filename}", f"페이지 {page_num}: {filename}")
            
        item = QListWidgetItem(item_text)
        item.setData(Qt.ItemDataRole.UserRole, image_path)
        self.image_list_widget.addItem(item)
        self.update_summary_labels()
            
    def on_conversion_finished(self, success, message):
        self.is_converting = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.update_summary_labels()
        
        if success:
            self.workflow_widget.complete_all()
            show_toast(self, self._t("Conversion completed.", "변환 성공!"), "success")
            QMessageBox.information(self, self._t("Completed", "완료"), message)
        else:
            self.workflow_widget.reset()
            show_toast(self, self._t(f"Conversion failed: {message}", f"변환 실패: {message}"), "error")
            QMessageBox.critical(self, self._t("Error", "오류"), self._t(f"The operation failed: {message}", f"작업에 실패했습니다: {message}"))
            
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
        pdf_count = len(self.selected_pdf_paths)
        image_count = len(self.image_files)
        self.pdf_summary_label.setText(self._t(f"Selected PDFs: {pdf_count}", f"선택된 PDF: {pdf_count}개", f"Wybrane PDF: {pdf_count}"))
        self.result_summary_label.setText(self._t(f"Created images: {image_count}", f"생성 이미지: {image_count}개", f"Utworzone obrazy: {image_count}"))

    def build_run_config(self):
        if not self.selected_pdf_paths:
            return None
            
        output_folder = self.output_path_input.text().strip()
        if not output_folder:
            raise TaskValidationError(
                "PDF 변환 저장 폴더가 지정되지 않았습니다.",
                message_key="pdf_output_folder_empty",
            )
            
        # PDF 파일들의 실제 존재 여부 검사
        for path in self.selected_pdf_paths:
            if not os.path.exists(path):
                raise TaskValidationError(
                    f"변환할 PDF 파일이 존재하지 않습니다: {path}",
                    message_key="pdf_file_missing",
                    values={"path": path},
                )
                
        return PdfRunConfig(pdf_paths=list(self.selected_pdf_paths), output_folder=output_folder)

    def get_task_info(self):
        config = self.build_run_config()
        return config.to_legacy_dict() if config else None
        
    def set_ui_locked(self, locked):
        for btn in self.findChildren(QPushButton):
            if btn not in (self.stop_btn,):
                btn.setEnabled(not locked)
        self.pdf_list_widget.setEnabled(not locked)
