from __future__ import annotations

from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.ui.i18n import tr
from src.ui.manual_content import manual_topic, manual_topics


class ManualDialog(QDialog):
    def __init__(self, language: str, topic_id: str = "getting_started", parent=None):
        super().__init__(parent)
        self.language = language
        self.requested_topic_id = topic_id
        self.setWindowTitle(tr("manual_title", language))
        self.resize(1050, 680)
        self._build_ui()
        self.select_topic(topic_id)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        body_layout = QHBoxLayout()

        self.topic_list = QListWidget()
        self.topic_list.setMinimumWidth(220)
        self.topic_list.setMaximumWidth(280)
        self.topic_list.setStyleSheet(
            "QListWidget { background: #111827; color: #e2e8f0; border: 1px solid #334155; }"
            "QListWidget::item { padding: 9px; }"
            "QListWidget::item:selected { background: #0e639c; color: white; }"
        )
        for topic_id, topic in manual_topics(self.language):
            item = QListWidgetItem(str(topic["title"]))
            item.setData(Qt.ItemDataRole.UserRole, topic_id)
            self.topic_list.addItem(item)
        self.topic_list.currentItemChanged.connect(self._on_topic_changed)
        body_layout.addWidget(self.topic_list)

        self.content = QTextBrowser()
        self.content.setOpenExternalLinks(False)
        self.content.setStyleSheet(
            "QTextBrowser { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; padding: 8px; }"
        )
        body_layout.addWidget(self.content, 1)
        layout.addLayout(body_layout, 1)

        close_button = QPushButton(tr("manual_close", self.language))
        close_button.clicked.connect(self.accept)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)

    def select_topic(self, topic_id: str) -> None:
        for row in range(self.topic_list.count()):
            item = self.topic_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == topic_id:
                self.topic_list.setCurrentRow(row)
                return
        self.topic_list.setCurrentRow(0)

    def _on_topic_changed(self, current, _previous) -> None:
        if current is None:
            return
        topic_id = str(current.data(Qt.ItemDataRole.UserRole))
        self.content.setHtml(self._topic_html(manual_topic(topic_id, self.language)))

    def _topic_html(self, topic: dict) -> str:
        steps = "".join(f"<li>{escape(str(item))}</li>" for item in topic.get("steps", []))
        tips = "".join(f"<li>{escape(str(item))}</li>" for item in topic.get("tips", []))
        cautions = "".join(f"<li>{escape(str(item))}</li>" for item in topic.get("cautions", []))
        return f"""
        <style>
            body {{ color: #e2e8f0; font-family: 'Malgun Gothic', 'Segoe UI', sans-serif; font-size: 14px; }}
            h1 {{ color: #7dd3fc; font-size: 24px; margin-bottom: 8px; }}
            h2 {{ color: #cbd5e1; font-size: 17px; margin-top: 22px; }}
            p {{ line-height: 1.55; }}
            li {{ margin: 7px 0; line-height: 1.45; }}
            .summary {{ background: #17212b; border: 1px solid #334155; padding: 12px; }}
            .tip {{ background: #15251d; border-left: 4px solid #22c55e; padding: 8px 12px; }}
            .caution {{ background: #2b2113; border-left: 4px solid #f59e0b; padding: 8px 12px; }}
        </style>
        <h1>{escape(str(topic.get('title', '')))}</h1>
        <p class="summary">{escape(str(topic.get('summary', '')))}</p>
        <h2>{escape(tr('manual_steps', self.language))}</h2>
        <ol>{steps}</ol>
        <div class="tip"><h2>{escape(tr('manual_tips', self.language))}</h2><ul>{tips}</ul></div>
        <div class="caution"><h2>{escape(tr('manual_cautions', self.language))}</h2><ul>{cautions}</ul></div>
        """
