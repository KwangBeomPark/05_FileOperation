from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget


class ToastNotification(QWidget):
    """토스트 알림 위젯"""
    
    def __init__(self, parent, message, toast_type='info'):
        super().__init__(parent)
        self.message = message
        self.toast_type = toast_type
        self.init_ui()
        self.position_widget()
        
    def init_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 10, 15, 10)
        
        label = QLabel(self.message)
        label.setWordWrap(True)
        label.setMaximumWidth(350)
        
        font = QFont()
        font.setPointSize(10)
        label.setFont(font)
        
        styles = {
            'success': """
                QLabel {
                    background-color: #4CAF50;
                    color: white;
                    padding: 12px 20px;
                    border-radius: 8px;
                    border-left: 5px solid #388E3C;
                }
            """,
            'warning': """
                QLabel {
                    background-color: #FF9800;
                    color: white;
                    padding: 12px 20px;
                    border-radius: 8px;
                    border-left: 5px solid #F57C00;
                }
            """,
            'error': """
                QLabel {
                    background-color: #F44336;
                    color: white;
                    padding: 12px 20px;
                    border-radius: 8px;
                    border-left: 5px solid #D32F2F;
                }
            """,
            'info': """
                QLabel {
                    background-color: #2196F3;
                    color: white;
                    padding: 12px 20px;
                    border-radius: 8px;
                    border-left: 5px solid #1976D2;
                }
            """
        }
        
        label.setStyleSheet(styles.get(self.toast_type, styles['info']))
        layout.addWidget(label)
        
        self.setLayout(layout)
        self.adjustSize()
    
    def position_widget(self):
        if self.parent():
            parent_rect = self.parent().rect()
            x = parent_rect.width() - self.width() - 20
            y = parent_rect.height() - self.height() - 80
            self.move(x, y)
    
    def show_toast(self):
        self.show()
        
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        
        self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(300)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_in.start()
        
        QTimer.singleShot(3000, self.fade_out_toast)
    
    def fade_out_toast(self):
        self.fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(300)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_out.finished.connect(self.close)
        self.fade_out.start()


def show_toast(parent, message, toast_type='info'):
    toast = ToastNotification(parent, message, toast_type)
    toast.show_toast()
    return toast
