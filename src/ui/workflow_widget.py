from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class WorkflowWidget(QWidget):
    """워크플로우 단계 표시 위젯"""
    
    def __init__(self, steps=None):
        super().__init__()
        self.steps = steps or [
            "1. Select PDF",
            "2. Convert Image",
            "3. Run OCR",
            "4. Rename Files",
            "5. Organize Files"
        ]
        self.step_statuses = ['pending'] * len(self.steps)
        self.step_labels = []
        self.arrow_labels = []
        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)
        
        for i, step_text in enumerate(self.steps):
            step_label = QLabel(step_text)
            step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step_label.setMinimumWidth(120)
            step_label.setMinimumHeight(40)
            step_label.setStyleSheet(self._get_style('pending'))
            
            font = QFont()
            font.setBold(True)
            step_label.setFont(font)
            
            self.step_labels.append(step_label)
            layout.addWidget(step_label)
            
            if i < len(self.steps) - 1:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setStyleSheet("font-size: 20pt; color: #3e3e3e;")
                self.arrow_labels.append(arrow)
                layout.addWidget(arrow)
        
        layout.addStretch()
        self.setLayout(layout)
    
    def _get_style(self, status):
        styles = {
            'pending': """
                QLabel {
                    background-color: #252526;
                    color: #8a949e;
                    border: 1px solid #3e3e3e;
                    border-radius: 5px;
                    padding: 8px;
                    font-size: 10pt;
                }
            """,
            'active': """
                QLabel {
                    background-color: #0e639c;
                    color: white;
                    border-radius: 5px;
                    padding: 8px;
                    font-size: 10pt;
                    border: 2px solid #1177bb;
                }
            """,
            'complete': """
                QLabel {
                    background-color: #16a34a;
                    color: white;
                    border-radius: 5px;
                    padding: 8px;
                    font-size: 10pt;
                    border: 1px solid #15803d;
                }
            """
        }
        return styles.get(status, styles['pending'])
    
    def update_step(self, step_index, status):
        if 0 <= step_index < len(self.step_labels):
            self.step_statuses[step_index] = status
            label = self.step_labels[step_index]
            label.setStyleSheet(self._get_style(status))
            
            if status == 'complete':
                original_text = self.steps[step_index]
                label.setText(f"✓ {original_text}")
            else:
                label.setText(self.steps[step_index])

    def set_step_texts(self, steps):
        """Replace translated step labels without resetting workflow progress."""
        if len(steps) != len(self.step_labels):
            raise ValueError("The number of workflow steps cannot change after initialization.")
        self.steps = list(steps)
        for index, status in enumerate(self.step_statuses):
            self.update_step(index, status)
    
    def set_active_step(self, step_index):
        for i in range(len(self.step_labels)):
            if i < step_index:
                self.update_step(i, 'complete')
            elif i == step_index:
                self.update_step(i, 'active')
            else:
                self.update_step(i, 'pending')
    
    def reset(self):
        for i in range(len(self.step_labels)):
            self.update_step(i, 'pending')
    
    def complete_all(self):
        for i in range(len(self.step_labels)):
            self.update_step(i, 'complete')
