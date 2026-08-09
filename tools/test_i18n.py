import ast
import re
import unittest
from string import Formatter
from pathlib import Path

from src.ui.i18n import FEATURE_MESSAGES, MESSAGES, STATIC_TEXT, detect_system_language, localize_static_text, normalize_language, tr


class LocalizationTests(unittest.TestCase):
    def test_catalog_languages_have_identical_keys_and_placeholders(self):
        self.assertEqual(set(MESSAGES["en"]), set(MESSAGES["ko"]))
        self.assertEqual(set(MESSAGES["en"]), set(MESSAGES["pl"]))
        formatter = Formatter()
        for key in MESSAGES["en"]:
            placeholders = {
                language: {field for _, field, _, _ in formatter.parse(MESSAGES[language][key]) if field}
                for language in ("en", "ko", "pl")
            }
            self.assertEqual(placeholders["en"], placeholders["ko"], key)
            self.assertEqual(placeholders["en"], placeholders["pl"], key)

    def test_non_korean_catalogs_do_not_contain_hangul(self):
        hangul = re.compile(r"[가-힣]")
        for language in ("en", "pl"):
            leaked = [key for key, value in MESSAGES[language].items() if hangul.search(value)]
            self.assertEqual(leaked, [], language)

    def test_static_text_has_all_supported_languages(self):
        for source, translations in STATIC_TEXT.items():
            self.assertEqual(set(translations), {"en", "ko", "pl"}, source)

    def test_feature_runtime_catalog_is_merged_and_formats_polish(self):
        for prefix in ("sync_", "eml_", "pdf_", "ocr_", "bypass_"):
            self.assertTrue(any(key.startswith(prefix) for key in FEATURE_MESSAGES), prefix)
        self.assertEqual(
            tr("pdf_page_item", "pl", page=2, filename="sample.png"),
            "Strona 2: sample.png",
        )
        self.assertIn(
            "3/5",
            tr("eml_task_completed_log", "pl", success=3, total=5),
        )

    def test_production_source_has_no_two_language_inline_translation_calls(self):
        incomplete = []
        unknown_keys = []
        source_folder = Path(__file__).resolve().parents[1] / "src"
        for path in source_folder.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    name = node.func.id
                else:
                    continue
                missing_polish = name in {"_t", "_text", "localize"} and len(node.args) == 2
                missing_polish = missing_polish or name == "choose" and len(node.args) == 3
                if missing_polish:
                    incomplete.append(f"{path.name}:{node.lineno}")
                if name in {"_msg", "tr"} and node.args:
                    key_arg = node.args[0]
                    if isinstance(key_arg, ast.Constant) and isinstance(key_arg.value, str):
                        if key_arg.value not in MESSAGES["en"]:
                            unknown_keys.append(f"{path.name}:{node.lineno}:{key_arg.value}")
        self.assertEqual(incomplete, [])
        self.assertEqual(unknown_keys, [])

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
        self.assertEqual(localize_static_text("목록 비우기", "pl"), "Wyczyść listę")
        self.assertEqual(localize_static_text("OCR 및 이름 변경 시작", "pl"), "Rozpocznij OCR i zmianę nazw")

    def test_tray_messages_are_localized(self):
        self.assertEqual(tr("tray_open", "ko"), "FileOps Hub 열기")
        self.assertEqual(tr("tray_exit", "pl"), "Zakończ FileOps Hub")
        self.assertIn("background", tr("tray_tooltip", "en"))

    def test_run_task_labels_and_validation_are_localized(self):
        self.assertEqual(tr("task_step_sync", "en"), "Sync Folders")
        self.assertEqual(tr("task_status_skipped", "en"), "Not selected")
        self.assertNotRegex(
            tr("bypass_source_folder_missing", "en", path=r"C:\missing"),
            r"[가-힣]",
        )
        self.assertEqual(tr("diagnostics_cancel", "ko"), "취소")
        self.assertEqual(tr("diagnostics_cancelled", "pl"), "Diagnostyka została anulowana. Pliki źródłowe nie zostały zmienione.")

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
