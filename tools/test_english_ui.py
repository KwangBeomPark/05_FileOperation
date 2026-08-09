import copy
import os
import re
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTableWidget,
)

from src.ui.bypass_tab import BypassTab
from src.ui.eml_tab import EMLTab
from src.ui.eml_task_dialog import EMLTaskDialog
from src.ui.i18n import localize_widget_tree
from src.ui.ocr_tab import OCRTab
from src.ui.pdf_tab import PDFTab
from src.ui.settings_dialog import SettingsDialog
from src.ui.sync_tab import SyncTab
from src.ui.task_tab import TaskTab
from src.utils.config_manager import ConfigManager


KOREAN = re.compile(r"[가-힣]")


class FakeConfig:
    def __init__(self, language="en"):
        self.values = copy.deepcopy(ConfigManager.DEFAULT_CONFIG)
        self.values["ui_language"] = language
        self.app_dir = os.getcwd()

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return True

    def save_config(self):
        return True


def visible_widget_texts(widget):
    values = []
    values.extend(child.text() for child in widget.findChildren(QAbstractButton))
    values.extend(child.text() for child in widget.findChildren(QLabel))
    values.extend(child.title() for child in widget.findChildren(QGroupBox))
    values.extend(child.placeholderText() for child in widget.findChildren(QLineEdit))
    for combo in widget.findChildren(QComboBox):
        values.extend(combo.itemText(index) for index in range(combo.count()))
    for table in widget.findChildren(QTableWidget):
        for index in range(table.columnCount()):
            header = table.horizontalHeaderItem(index)
            if header:
                values.append(header.text())
    return [value for value in values if value]


class LocalizedUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_feature_tabs_start_without_korean_ui_text(self):
        tabs = []
        try:
            for tab_type in (TaskTab, SyncTab, EMLTab, PDFTab, OCRTab, BypassTab):
                tab = tab_type(FakeConfig())
                tabs.append(tab)
                localize_widget_tree(tab, "en")
                leaked = [text for text in visible_widget_texts(tab) if KOREAN.search(text)]
                self.assertEqual(leaked, [], f"{tab_type.__name__}: {leaked}")
        finally:
            for tab in tabs:
                if hasattr(tab, "schedule_timer"):
                    tab.schedule_timer.stop()
                tab.deleteLater()
            self.app.processEvents()

    def test_empty_state_warnings_are_english(self):
        captured = []

        def record(_parent, title, message, *_args, **_kwargs):
            captured.extend([title, message])

        tabs = [SyncTab(FakeConfig()), EMLTab(FakeConfig()), PDFTab(FakeConfig()), OCRTab(FakeConfig()), BypassTab(FakeConfig())]
        try:
            with patch("PyQt6.QtWidgets.QMessageBox.warning", side_effect=record):
                tabs[0].start_dry_run()
                tabs[1].start_conversion()
                tabs[2].start_conversion()
                tabs[3].start_ocr()
                tabs[4].scan_source_folder()
            leaked = [text for text in captured if KOREAN.search(text)]
            self.assertEqual(leaked, [], leaked)
            self.assertGreaterEqual(len(captured), 10)
        finally:
            for tab in tabs:
                tab.deleteLater()
            self.app.processEvents()

    def test_polish_dynamic_labels_and_empty_state_warnings(self):
        captured = []

        def record(_parent, title, message, *_args, **_kwargs):
            captured.extend([title, message])

        tabs = [SyncTab(FakeConfig("pl")), EMLTab(FakeConfig("pl")), PDFTab(FakeConfig("pl")), OCRTab(FakeConfig("pl")), BypassTab(FakeConfig("pl"))]
        try:
            for tab in tabs:
                localize_widget_tree(tab, "pl")
                if hasattr(tab, "refresh_language"):
                    tab.refresh_language()

            sync_tab, eml_tab, pdf_tab, ocr_tab, bypass_tab = tabs
            self.assertEqual(sync_tab.group_combo.currentText(), "Domyślna grupa synchronizacji")
            self.assertEqual(sync_tab.sync_groups[0]["name"], "Default Sync Group")
            self.assertEqual(sync_tab.plan_summary_label.text(), "Nie przeanalizowano")
            self.assertEqual(pdf_tab.workflow_widget.step_labels[0].text(), "1. Wybierz PDF")
            self.assertEqual(pdf_tab.pdf_summary_label.text(), "Wybrane PDF: 0")
            self.assertEqual(ocr_tab.workflow_widget.step_labels[1].text(), "2. Uruchom OCR i zmień nazwy")
            self.assertEqual(ocr_tab.image_summary_label.text(), "Obrazy: 0 (wybrane: 0)")
            self.assertEqual(bypass_tab.workflow_widget.step_labels[0].text(), "1. Skanuj pliki")
            self.assertEqual(
                [bypass_tab.file_table.horizontalHeaderItem(index).text() for index in range(4)],
                ["Nazwa pliku", "Rozmiar oryginału", "Format docelowy", "Stan"],
            )

            with patch("PyQt6.QtWidgets.QMessageBox.warning", side_effect=record):
                sync_tab.start_dry_run()
                eml_tab.start_conversion()
                pdf_tab.start_conversion()
                ocr_tab.start_ocr()
                bypass_tab.scan_source_folder()
            self.assertTrue(captured)
            self.assertTrue(all("Ostrzeżenie" == captured[index] for index in range(0, len(captured), 2)))
            self.assertTrue(any("co najmniej dwóch folderów" in text for text in captured))
            self.assertTrue(any("plik PDF" in text for text in captured))
            self.assertTrue(any("prawidłowy folder źródłowy" in text for text in captured))
        finally:
            for tab in tabs:
                tab.deleteLater()
            self.app.processEvents()

    def test_polish_eml_task_dialog_is_localized(self):
        dialog = EMLTaskDialog(language="pl")
        try:
            texts = visible_widget_texts(dialog)
            self.assertIn("Nazwa zadania:", texts)
            self.assertIn("Folder źródłowy:", texts)
            self.assertIn("Anuluj", texts)
            self.assertNotIn("Choose Folder", texts)
        finally:
            dialog.deleteLater()
            self.app.processEvents()

    def test_polish_settings_dialog_is_localized(self):
        dialog = SettingsDialog(FakeConfig("pl"))
        try:
            texts = visible_widget_texts(dialog)
            self.assertIn("Serwer SMTP:", texts)
            self.assertIn("Adres nadawcy:", texts)
            self.assertIn("Przykład: 465 lub 587", texts)
            self.assertNotIn("Sender Password:", texts)
        finally:
            dialog.deleteLater()
            self.app.processEvents()

    def test_workflow_retranslation_preserves_completion_state(self):
        from src.ui.workflow_widget import WorkflowWidget

        widget = WorkflowWidget(["One", "Two", "Three"])
        try:
            widget.set_active_step(1)
            widget.set_step_texts(["Jeden", "Dwa", "Trzy"])
            self.assertEqual(widget.step_labels[0].text(), "✓ Jeden")
            self.assertEqual(widget.step_labels[1].text(), "Dwa")
            self.assertEqual(widget.step_statuses, ["complete", "active", "pending"])
        finally:
            widget.deleteLater()

    def test_switching_from_korean_to_english_retranslates_live_tabs(self):
        tabs = []
        try:
            for tab_type in (TaskTab, SyncTab, EMLTab, PDFTab, OCRTab, BypassTab):
                config = FakeConfig("ko")
                tab = tab_type(config)
                tabs.append(tab)
                localize_widget_tree(tab, "ko")
                config.set("ui_language", "en")
                localize_widget_tree(tab, "en")
                if hasattr(tab, "refresh_language"):
                    tab.refresh_language()
                leaked = [text for text in visible_widget_texts(tab) if KOREAN.search(text)]
                self.assertEqual(leaked, [], f"{tab_type.__name__}: {leaked}")
        finally:
            for tab in tabs:
                if hasattr(tab, "schedule_timer"):
                    tab.schedule_timer.stop()
                tab.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
