import os
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QFileDialog, QMessageBox, QGroupBox, QFormLayout, QComboBox, QScrollArea, QWidget
)
from src.ui.i18n import choose, get_app_language, tr

class SettingsDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.language = get_app_language(config_manager)
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle(tr("settings_title", self.language))
        self.setMinimumWidth(550)
        self.setMinimumHeight(600)
        
        # 스크롤 영역 생성 (이메일 설정 필드가 많으므로 스크롤 지원)
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: transparent; border: none;")
        
        container = QWidget()
        container_layout = QVBoxLayout()
        container.setLayout(container_layout)
        
        language_group = QGroupBox(tr("language_group", self.language))
        language_form = QFormLayout()
        language_group.setLayout(language_form)
        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("language_auto", self.language), "auto")
        self.language_combo.addItem(tr("language_en", self.language), "en")
        self.language_combo.addItem(tr("language_ko", self.language), "ko")
        self.language_combo.addItem(tr("language_pl", self.language), "pl")
        language_form.addRow(tr("display_language", self.language), self.language_combo)
        container_layout.addWidget(language_group)

        # 1. OCR 설정 그룹
        ocr_group = QGroupBox(tr("ocr_settings", self.language))
        ocr_form = QFormLayout()
        ocr_group.setLayout(ocr_form)
        
        self.tesseract_path_input = QLineEdit()
        self.tesseract_path_input.setPlaceholderText(tr("optional_tesseract_path", self.language))
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.tesseract_path_input)
        browse_btn = QPushButton(tr("browse", self.language))
        browse_btn.clicked.connect(self.browse_tesseract)
        btn_layout.addWidget(browse_btn)
        
        ocr_form.addRow(tr("tesseract_path", self.language), btn_layout)
        container_layout.addWidget(ocr_group)
        
        # 2. GitHub 설정 그룹 (보안 키 적용)
        github_group = QGroupBox(tr("github_settings", self.language))
        github_form = QFormLayout()
        github_group.setLayout(github_form)
        
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password) # 토큰 글자 숨김 처리
        self.token_input.setPlaceholderText("GitHub Personal Access Token (ghp_...)")
        self.repo_input = QLineEdit()
        self.repo_input.setPlaceholderText("owner/repository")
        self.auto_check_combo = QComboBox()
        self.auto_check_combo.addItem(tr("on_start", self.language), "on_start")
        self.auto_check_combo.addItem(tr("manual", self.language), "manual")
        
        github_form.addRow(tr("github_repository", self.language), self.repo_input)
        github_form.addRow(tr("github_token", self.language), self.token_input)
        github_form.addRow(tr("update_check", self.language), self.auto_check_combo)
        container_layout.addWidget(github_group)
        
        # 3. SMTP 이메일 설정 그룹 (신규 추가)
        email_group = QGroupBox(tr("email_settings", self.language))
        email_form = QFormLayout()
        email_group.setLayout(email_form)
        
        self.smtp_server_input = QLineEdit()
        self.smtp_server_input.setPlaceholderText(choose(self.language, "Example: smtp.gmail.com", "예: smtp.gmail.com"))
        self.smtp_port_input = QLineEdit()
        self.smtp_port_input.setPlaceholderText(choose(self.language, "Example: 465 or 587", "예: 465 또는 587"))
        self.sender_email_input = QLineEdit()
        self.sender_email_input.setPlaceholderText(choose(self.language, "Example: sender@gmail.com", "예: sender@gmail.com"))
        self.sender_pwd_input = QLineEdit()
        self.sender_pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.sender_pwd_input.setPlaceholderText(choose(self.language, "Password or app password", "비밀번호 또는 앱 비밀번호"))
        
        self.receiver_email_input = QLineEdit()
        self.receiver_email_input.setPlaceholderText(choose(self.language, "Example: rc1@test.com, rc2@test.com (comma-separated)", "예: rc1@test.com, rc2@test.com (쉼표 구분)"))
        self.mail_subject_input = QLineEdit()
        self.mail_subject_input.setPlaceholderText(choose(self.language, "Task Result Report", "작업 실행 결과 보고서"))
        self.mail_body_header_input = QLineEdit()
        self.mail_body_header_input.setPlaceholderText(choose(self.language, "Optional text added above the report", "본문 상단에 추가할 내용"))
        
        email_form.addRow("SMTP Server:", self.smtp_server_input)
        email_form.addRow("SMTP Port:", self.smtp_port_input)
        email_form.addRow("Sender Email:", self.sender_email_input)
        email_form.addRow("Sender Password:", self.sender_pwd_input)
        email_form.addRow("Receiver Email(s):", self.receiver_email_input)
        email_form.addRow("Mail Subject:", self.mail_subject_input)
        email_form.addRow("Mail Body Header:", self.mail_body_header_input)
        container_layout.addWidget(email_group)
        
        # 4. 기타 변환 설정
        misc_group = QGroupBox(tr("conversion_settings", self.language))
        misc_form = QFormLayout()
        misc_group.setLayout(misc_form)
        
        self.eml_width_input = QLineEdit()
        self.eml_width_input.setPlaceholderText(choose(self.language, "Example: 1024", "예: 1024"))
        
        misc_form.addRow(tr("eml_width", self.language), self.eml_width_input)
        container_layout.addWidget(misc_group)
        
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)
        
        # 5. 하단 버튼 영역 (저장 / 취소)
        button_layout = QHBoxLayout()
        save_btn = QPushButton(tr("save", self.language))
        save_btn.clicked.connect(self.save_settings)
        save_btn.setDefault(True)
        
        cancel_btn = QPushButton(tr("cancel", self.language))
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        main_layout.addLayout(button_layout)
        
        # 데이터 초기 로드
        self.load_settings()
        
    def load_settings(self):
        tesseract_path = self.config_manager.get("tesseract_path", "")
        github_token = self.config_manager.get("github_token", "")
        github_repo = self.config_manager.get("github_repo", "")
        auto_check = self.config_manager.get("auto_check_update", "on_start")
        ui_language = self.config_manager.get("ui_language", "auto")
        eml_width = self.config_manager.get(
            "eml_output_width",
            self.config_manager.get("eml_width", "1024")
        )
        
        # SMTP 로드
        smtp_server = self.config_manager.get("smtp_server", "")
        smtp_port = self.config_manager.get("smtp_port", "")
        sender_email = self.config_manager.get("sender_email", "")
        sender_pwd = self.config_manager.get("sender_password", "")
                
        receiver_email = self.config_manager.get("receiver_email", "")
        mail_subject = self.config_manager.get("mail_subject", "통합 작업 완료 결과 보고서")
        if self.language != "ko" and mail_subject == "통합 작업 완료 결과 보고서":
            mail_subject = "Task Result Report"
        mail_body_header = self.config_manager.get("mail_body_header", "")
        
        self.tesseract_path_input.setText(tesseract_path)
        self.repo_input.setText(github_repo)
        self.token_input.setText(github_token)
        self.eml_width_input.setText(str(eml_width))
        combo_index = self.auto_check_combo.findData(auto_check)
        if combo_index >= 0:
            self.auto_check_combo.setCurrentIndex(combo_index)
        language_index = self.language_combo.findData(ui_language)
        if language_index >= 0:
            self.language_combo.setCurrentIndex(language_index)
            
        self.smtp_server_input.setText(smtp_server)
        self.smtp_port_input.setText(str(smtp_port))
        self.sender_email_input.setText(sender_email)
        self.sender_pwd_input.setText(sender_pwd)
        self.receiver_email_input.setText(receiver_email)
        self.mail_subject_input.setText(mail_subject)
        self.mail_body_header_input.setText(mail_body_header)
        
    def browse_tesseract(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, choose(self.language, "Select Tesseract Executable", "Tesseract 실행 파일 찾기"), "", "Executable Files (*.exe);;All Files (*)"
        )
        if file_path:
            self.tesseract_path_input.setText(os.path.normpath(file_path))
            
    def save_settings(self):
        tesseract_path = self.tesseract_path_input.text().strip()
        github_token = self.token_input.text().strip()
        github_repo = self.repo_input.text().strip()
        eml_width_raw = self.eml_width_input.text().strip()
        auto_check = self.auto_check_combo.currentData()
        
        # SMTP 세이브 입력 값 수집
        smtp_server = self.smtp_server_input.text().strip()
        smtp_port_raw = self.smtp_port_input.text().strip()
        sender_email = self.sender_email_input.text().strip()
        sender_pwd = self.sender_pwd_input.text().strip()
        receiver_email = self.receiver_email_input.text().strip()
        mail_subject = self.mail_subject_input.text().strip()
        mail_body_header = self.mail_body_header_input.text().strip()
        
        # --- 유효성 검사 (Validation) ---
        try:
            eml_width = int(eml_width_raw)
            if eml_width < 300 or eml_width > 4000:
                raise ValueError()
        except ValueError:
            QMessageBox.warning(self, tr("input_error", self.language), tr("eml_width_error", self.language))
            return
            
        if github_repo and "/" not in github_repo:
            QMessageBox.warning(self, tr("input_error", self.language), tr("github_repo_error", self.language))
            return
            
        # 이메일 / SMTP 입력 데이터 유효성 검사
        if smtp_port_raw:
            try:
                smtp_port = int(smtp_port_raw)
                if smtp_port < 1 or smtp_port > 65535:
                    raise ValueError()
            except ValueError:
                QMessageBox.warning(self, tr("input_error", self.language), tr("smtp_port_error", self.language))
                return
        else:
            smtp_port = ""
            
        email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        
        if sender_email and not re.match(email_regex, sender_email):
            QMessageBox.warning(self, tr("input_error", self.language), tr("sender_email_error", self.language))
            return
            
        if receiver_email:
            receivers = [r.strip() for r in receiver_email.replace(';', ',').split(',') if r.strip()]
            for r in receivers:
                if not re.match(email_regex, r):
                    QMessageBox.warning(
                        self,
                        tr("input_error", self.language),
                        tr("receiver_email_error", self.language, email=r),
                    )
                    return
                    
        # 설정 저장
        self.config_manager.set("tesseract_path", tesseract_path)
        self.config_manager.set("ui_language", self.language_combo.currentData())
        self.config_manager.set("github_repo", github_repo)
        self.config_manager.set("github_token", github_token)
        self.config_manager.set("auto_check_update", auto_check)
        self.config_manager.set("eml_output_width", eml_width)
        
        self.config_manager.set("smtp_server", smtp_server)
        self.config_manager.set("smtp_port", smtp_port)
        self.config_manager.set("sender_email", sender_email)
        self.config_manager.set("sender_password", sender_pwd)
        self.config_manager.set("receiver_email", receiver_email)
        self.config_manager.set("mail_subject", mail_subject)
        self.config_manager.set("mail_body_header", mail_body_header)
        
        self.config_manager.save_config()
        self.accept()
