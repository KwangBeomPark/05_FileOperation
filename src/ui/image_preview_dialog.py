import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ImagePreviewDialog(QDialog):
    """이미지 미리보기 다이얼로그"""
    
    def __init__(self, parent, image_files, current_index, ocr_results):
        super().__init__(parent)
        self.image_files = image_files
        self.current_index = current_index
        self.ocr_results = ocr_results
        self.init_ui()
        self.load_image(self.current_index)
        
    def init_ui(self):
        self.setWindowTitle('Image Preview')
        self.resize(1000, 700)
        
        layout = QVBoxLayout()
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: #2b2b2b;")
        scroll.setWidget(self.image_label)
        
        layout.addWidget(scroll, 3)
        
        info_panel = QWidget()
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(10, 5, 10, 5)
        
        self.file_info_label = QLabel()
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        self.file_info_label.setFont(font)
        info_layout.addWidget(self.file_info_label)
        
        self.ocr_info_label = QLabel()
        self.ocr_info_label.setWordWrap(True)
        info_layout.addWidget(self.ocr_info_label)
        
        self.text_label = QLabel("📝 Extracted Text:")
        info_layout.addWidget(self.text_label)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumHeight(100)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #e2e8f0;
                border: 1px solid #3e3e3e;
                border-radius: 3px;
                padding: 5px;
                font-family: Consolas, monospace;
                font-size: 9pt;
            }
        """)
        info_layout.addWidget(self.text_edit)
        
        info_panel.setLayout(info_layout)
        layout.addWidget(info_panel, 1)
        
        nav_layout = QHBoxLayout()
        
        self.prev_btn = QPushButton('◀ Previous')
        self.prev_btn.clicked.connect(self.show_previous)
        self.prev_btn.setMinimumHeight(35)
        nav_layout.addWidget(self.prev_btn)
        
        self.index_label = QLabel()
        self.index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self.index_label)
        
        self.next_btn = QPushButton('Next ▶')
        self.next_btn.clicked.connect(self.show_next)
        self.next_btn.setMinimumHeight(35)
        nav_layout.addWidget(self.next_btn)
        
        close_btn = QPushButton('Close (ESC)')
        close_btn.clicked.connect(self.close)
        close_btn.setMinimumHeight(35)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d2d2d;
                color: #e2e8f0;
                border: 1px solid #3e3e3e;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #3e3e3e;
            }
        """)
        nav_layout.addWidget(close_btn)
        
        layout.addLayout(nav_layout)
        
        self.setLayout(layout)
    
    def load_image(self, index):
        if not (0 <= index < len(self.image_files)):
            return
        
        image_path = self.image_files[index]
        
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(800, 600, 
                                          Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
        
        filename = os.path.basename(image_path)
        file_size = os.path.getsize(image_path) / 1024
        self.file_info_label.setText(f"📄 {filename} ({file_size:.1f} KB)")
        
        if image_path in self.ocr_results:
            success, promo_num, full_text, error = self.ocr_results[image_path]
            
            if success and promo_num:
                self.ocr_info_label.setText(f"✓ Promotion No: <b style='color: #81c784;'>{promo_num}</b>")
                self.ocr_info_label.setStyleSheet("color: #81c784; padding: 5px; font-weight: bold;")
            else:
                error_msg = error or "Promotion number not found"
                self.ocr_info_label.setText(f"⚠️ {error_msg}")
                self.ocr_info_label.setStyleSheet("color: #ffb74d; padding: 5px; font-weight: bold;")
            
            if full_text:
                self.text_edit.setText(full_text)
                self.text_edit.setVisible(True)
                self.text_label.setVisible(True)
            else:
                self.text_edit.setVisible(False)
                self.text_label.setVisible(False)
        else:
            self.ocr_info_label.setText("ℹ️ OCR not run")
            self.ocr_info_label.setStyleSheet("color: #8a949e; padding: 5px;")
            self.text_edit.setVisible(False)
            self.text_label.setVisible(False)
        
        self.index_label.setText(f"{index + 1} / {len(self.image_files)}")
        
        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < len(self.image_files) - 1)
    
    def show_previous(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.load_image(self.current_index)
    
    def show_next(self):
        if self.current_index < len(self.image_files) - 1:
            self.current_index += 1
            self.load_image(self.current_index)
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Left:
            self.show_previous()
        elif event.key() == Qt.Key.Key_Right:
            self.show_next()
        else:
            super().keyPressEvent(event)
