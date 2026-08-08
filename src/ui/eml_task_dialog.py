import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QFileDialog, QMessageBox, QDialogButtonBox
)
from src.ui.i18n import choose

class EMLTaskDialog(QDialog):
    """
    EML 변환 태스크의 이름, 소스 폴더, 저장 대상 폴더를 설정하는 다이얼로그.
    """
    def __init__(self, parent=None, task_name="", source_folder="", target_folder="", existing_names=None, language="en"):
        super().__init__(parent)
        self.language = language
        self.existing_names = existing_names or []
        self.original_name = task_name
        self.init_ui(task_name, source_folder, target_folder)

    def _t(self, english, korean, polish=None):
        return choose(self.language, english, korean, polish)
        
    def init_ui(self, name, source, target):
        self.setWindowTitle(self._t("EML Conversion Task", "EML 변환 태스크 설정"))
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 1. 태스크 이름
        name_layout = QHBoxLayout()
        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText(self._t("Example: Sales EML Conversion", "예: 영업관리팀 EML 변환"))
        name_layout.addWidget(QLabel(self._t("Task name:", "태스크 이름:")))
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # 2. 소스 폴더
        source_layout = QHBoxLayout()
        self.source_input = QLineEdit(source)
        self.source_input.setReadOnly(True)
        self.source_input.setPlaceholderText(self._t("Select the folder containing EML files.", "EML 파일이 보관된 폴더를 선택하세요."))
        source_btn = QPushButton(self._t("Choose Folder", "폴더 선택"))
        source_btn.clicked.connect(self.browse_source)
        source_layout.addWidget(QLabel(self._t("Source folder:", "소스 폴더:")))
        source_layout.addWidget(self.source_input)
        source_layout.addWidget(source_btn)
        layout.addLayout(source_layout)
        
        # 3. 대상 폴더
        target_layout = QHBoxLayout()
        self.target_input = QLineEdit(target)
        self.target_input.setReadOnly(True)
        self.target_input.setPlaceholderText(self._t("Select the folder for converted PNG images.", "변환된 PNG 이미지가 저장될 폴더를 선택하세요."))
        target_btn = QPushButton(self._t("Choose Folder", "폴더 선택"))
        target_btn.clicked.connect(self.browse_target)
        target_layout.addWidget(QLabel(self._t("Output folder:", "저장 폴더:")))
        target_layout.addWidget(self.target_input)
        target_layout.addWidget(target_btn)
        layout.addLayout(target_layout)
        
        # 4. 확인 / 취소 버튼
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(self._t("OK", "확인"))
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(self._t("Cancel", "취소"))
        layout.addWidget(self.button_box)
        
    def browse_source(self):
        initial = self.source_input.text().strip() or os.getcwd()
        folder = QFileDialog.getExistingDirectory(self, self._t("Select EML Source Folder", "EML 파일들이 보관된 소스 폴더 선택"), initial)
        if folder:
            norm_folder = os.path.normpath(folder)
            self.source_input.setText(norm_folder)
            
            # 태스크 이름이 비어있거나 소스 폴더 경로 기반으로 자동 세팅을 돕는 로직
            if not self.name_input.text().strip():
                folder_name = os.path.basename(norm_folder)
                self.name_input.setText(self._t(f"{folder_name} EML Conversion", f"{folder_name} EML 변환"))
                
            # 대상 폴더도 비어있으면 소스 폴더와 동일하게 기본 제공
            if not self.target_input.text().strip():
                self.target_input.setText(norm_folder)
                
    def browse_target(self):
        initial = self.target_input.text().strip() or self.source_input.text().strip() or os.getcwd()
        folder = QFileDialog.getExistingDirectory(self, self._t("Select PNG Output Folder", "PNG 이미지를 저장할 폴더 선택"), initial)
        if folder:
            self.target_input.setText(os.path.normpath(folder))
            
    def validate_and_accept(self):
        name = self.name_input.text().strip()
        source = self.source_input.text().strip()
        target = self.target_input.text().strip()
        
        if not name:
            QMessageBox.warning(self, self._t("Input error", "입력 오류"), self._t("Enter a task name.", "태스크 이름을 입력해 주세요."))
            return
            
        if name != self.original_name and name in self.existing_names:
            QMessageBox.warning(self, self._t("Input error", "입력 오류"), self._t(f"A task named '{name}' already exists.", f"'{name}'은(는) 이미 존재하는 태스크 이름입니다."))
            return
            
        if not source:
            QMessageBox.warning(self, self._t("Input error", "입력 오류"), self._t("Select a source folder.", "소스 폴더를 선택해 주세요."))
            return
            
        if not os.path.isdir(source):
            QMessageBox.warning(self, self._t("Input error", "입력 오류"), self._t("The selected source folder does not exist.", "선택한 소스 폴더가 존재하지 않습니다."))
            return
            
        if not target:
            QMessageBox.warning(self, self._t("Input error", "입력 오류"), self._t("Select an output folder.", "저장 폴더를 선택해 주세요."))
            return
            
        self.accept()
        
    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "source_folder": self.source_input.text().strip(),
            "target_folder": self.target_input.text().strip()
        }
