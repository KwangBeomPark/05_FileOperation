import unittest

from src.ui.i18n import detect_system_language, localize_static_text, normalize_language, tr


class LocalizationTests(unittest.TestCase):
    def test_supported_windows_and_locale_languages(self):
        self.assertEqual(detect_system_language(ui_language_id=0x0409), "en")
        self.assertEqual(detect_system_language(ui_language_id=0x0412), "ko")
        self.assertEqual(detect_system_language(ui_language_id=0x0415), "pl")
        self.assertEqual(detect_system_language(ui_language_id=0x0411), "en")
        self.assertEqual(detect_system_language(ui_language_id=0, locale_name="pl_PL"), "pl")
        self.assertEqual(detect_system_language(ui_language_id=0, locale_name="fr_FR"), "en")

    def test_language_normalization_and_english_fallback(self):
        self.assertEqual(normalize_language("ko-KR"), "ko")
        self.assertEqual(normalize_language("pl_PL"), "pl")
        self.assertIsNone(normalize_language("ja-JP"))
        self.assertEqual(tr("ready", "pl"), "Gotowe")
        self.assertEqual(tr("ready", "ja"), "Ready")

    def test_common_feature_labels_are_localized(self):
        self.assertEqual(localize_static_text("PDF Input Files", "ko"), "PDF 입력 파일")
        self.assertEqual(localize_static_text("PDF Input Files", "pl"), "Pliki PDF")
        self.assertEqual(localize_static_text("중지", "en"), "Stop")

    def test_qt_static_widget_retranslation_keeps_the_original_source_text(self):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton, QVBoxLayout, QWidget
        from src.ui.i18n import localize_widget_tree

        app = QApplication.instance() or QApplication([])
        root = QWidget()
        layout = QVBoxLayout(root)
        label = QLabel("PDF Input Files")
        button = QPushButton("중지")
        group_box = QGroupBox("Conversion Results")
        layout.addWidget(label)
        layout.addWidget(button)
        layout.addWidget(group_box)

        localize_widget_tree(root, "pl")
        self.assertEqual(label.text(), "Pliki PDF")
        self.assertEqual(button.text(), "Zatrzymaj")
        self.assertEqual(group_box.title(), "Wyniki konwersji")

        localize_widget_tree(root, "en")
        self.assertEqual(label.text(), "PDF Input Files")
        self.assertEqual(button.text(), "Stop")
        self.assertEqual(group_box.title(), "Conversion Results")

        label.setText("Selected PDFs: 3")
        localize_widget_tree(root, "ko")
        self.assertEqual(label.text(), "Selected PDFs: 3")
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
