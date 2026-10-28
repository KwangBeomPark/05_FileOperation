import unittest
from unittest.mock import patch

from src.core import ocr_processor
from src.core.ocr_processor import OCRProcessor


class FakeConfig:
    def get(self, key, default=""):
        if key == "promotion_regex":
            return r"PL-[A-Z]TS[A-Z]-202\d{5}-\d{4}"
        return default

    def set(self, _key, _value):
        return True


class OCRProcessorTests(unittest.TestCase):
    def test_tesseract_failure_falls_back_to_windows_ocr(self):
        processor = OCRProcessor(FakeConfig())
        with (
            patch.object(processor, "check_tesseract_installed", return_value=True),
            patch("src.core.ocr_processor.Image.open", side_effect=RuntimeError("tess failed")),
            patch("src.core.ocr_processor.extract_text_with_windows_ocr", return_value="PL-ATSZ-20261234-6789"),
        ):
            success, promo_num, text, error = processor.process_image("sample.png")

        self.assertTrue(success)
        self.assertEqual(promo_num, "PL-ATSZ-20261234-6789")
        self.assertIn("PL-ATSZ", text)
        self.assertIsNone(error)

    def test_ocr_available_when_windows_fallback_exists(self):
        processor = OCRProcessor(FakeConfig())
        with (
            patch.object(processor, "check_tesseract_installed", return_value=False),
            patch.object(processor, "check_windows_ocr_available", return_value=True),
        ):
            self.assertTrue(processor.check_ocr_available())

    def test_extract_by_rule_method_shares_module_implementation(self):
        processor = OCRProcessor(FakeConfig())
        samples = [
            ("Invoice No: INV-2026-9876", "invoice_number", ""),
            ("Delivered on 2026-11-20", "date_ymd", ""),
            ("\n  Header Title \nnext", "first_line", ""),
            ("Serial [SN-XYZ-404]", "custom_regex", r"SN-[A-Z]+-\d+"),
            ("anything", "custom_regex", "(unclosed"),
        ]
        for text, mode, pattern in samples:
            with self.subTest(mode=mode, pattern=pattern):
                self.assertEqual(
                    processor.extract_by_rule(text, mode, pattern),
                    ocr_processor.extract_by_rule(text, mode, pattern),
                )

    def test_promotion_method_still_uses_configured_regex(self):
        processor = OCRProcessor(FakeConfig())
        text = "Promotion: 250101-99 / PL-ATSZ-20261234-6789"
        # 설정 정규식(정식 번호만)을 따르는 클래스 메서드 vs 축약 표기도 허용하는 모듈 기본 규칙
        self.assertEqual(processor.extract_by_rule(text, "promotion"), "PL-ATSZ-20261234-6789")
        self.assertEqual(ocr_processor.extract_by_rule(text, "promotion"), "250101-99")


if __name__ == "__main__":
    unittest.main()
