import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.core import ocr_processor, windows_ocr
from src.core.ocr_processor import OCRProcessor


class FakeConfig:
    def get(self, key, default=""):
        if key == "promotion_regex":
            return r"PL-[A-Z]TS[A-Z]-202\d{5}-\d{4}"
        return default

    def set(self, _key, _value):
        return True


class OCRProcessorTests(unittest.TestCase):
    def test_ocr_cleanup_failures_do_not_change_result_or_delete_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            source.write_bytes(b"original")
            with (
                patch.object(windows_ocr, "_prepare_image", return_value=("temporary-image", True)),
                patch.object(windows_ocr, "_write_script", return_value="temporary-script"),
                patch.object(windows_ocr, "_run_powershell", return_value=SimpleNamespace(returncode=0, stdout=" result ")),
                patch.object(Path, "unlink", autospec=True, side_effect=OSError("sensitive path")) as unlink,
                self.assertLogs(windows_ocr.logger, level="WARNING") as logs,
            ):
                result = windows_ocr.extract_text_with_windows_ocr(str(source))
            self.assertEqual(result, "result")
            self.assertEqual(source.read_bytes(), b"original")
            self.assertEqual(len(logs.output), 2)
            self.assertNotIn("sensitive path", " ".join(logs.output))
            self.assertEqual({call.args[0] for call in unlink.call_args_list}, {Path("temporary-script"), Path("temporary-image")})
            self.assertNotIn(source, {call.args[0] for call in unlink.call_args_list})

    def test_ocr_cleanup_failure_does_not_mask_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            source.write_bytes(b"original")
            original_error = RuntimeError("original failure")
            with (
                patch.object(windows_ocr, "_prepare_image", return_value=("temporary-image", True)),
                patch.object(windows_ocr, "_write_script", return_value="temporary-script"),
                patch.object(windows_ocr, "_run_powershell", side_effect=original_error),
                patch.object(Path, "unlink", autospec=True, side_effect=OSError("sensitive path")) as unlink,
                self.assertLogs(windows_ocr.logger, level="WARNING"),
                self.assertRaises(RuntimeError) as caught,
            ):
                windows_ocr.extract_text_with_windows_ocr(str(source))
            self.assertIs(caught.exception, original_error)
            self.assertEqual({call.args[0] for call in unlink.call_args_list}, {Path("temporary-script"), Path("temporary-image")})
            self.assertEqual(source.read_bytes(), b"original")

    def test_ocr_check_cleanup_failure_does_not_change_result(self):
        with (
            patch.object(windows_ocr.sys, "platform", "win32"),
            patch.object(windows_ocr, "_write_script", return_value="temporary-script"),
            patch.object(windows_ocr, "_run_powershell", return_value=SimpleNamespace(returncode=0)),
            patch.object(Path, "unlink", side_effect=OSError("sensitive path")),
            self.assertLogs(windows_ocr.logger, level="WARNING") as logs,
        ):
            available, _message = windows_ocr.windows_ocr_available()
        self.assertTrue(available)
        self.assertNotIn("sensitive path", " ".join(logs.output))

    def test_windows_ocr_script_is_closed_and_preserved_after_write(self):
        with tempfile.TemporaryDirectory() as directory:
            original_factory = tempfile.NamedTemporaryFile
            handles = []

            def create_file(*args, **kwargs):
                handle = original_factory(*args, dir=directory, **kwargs)
                handles.append(handle)
                return handle

            with patch.object(windows_ocr.tempfile, "NamedTemporaryFile", side_effect=create_file):
                path = Path(windows_ocr._write_script())
            self.assertTrue(handles[0].closed)
            self.assertEqual(path.read_text(encoding="utf-8-sig"), windows_ocr.POWERSHELL_OCR_SCRIPT)

    def test_windows_ocr_script_is_closed_and_preserved_after_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            original_factory = tempfile.NamedTemporaryFile
            handles = []

            def create_file(*args, **kwargs):
                handle = original_factory(*args, dir=directory, **kwargs)
                handles.append(handle)
                return handle

            with (
                patch.object(windows_ocr.tempfile, "NamedTemporaryFile", side_effect=create_file),
                patch.object(windows_ocr, "POWERSHELL_OCR_SCRIPT", None),
                self.assertRaises(TypeError),
            ):
                windows_ocr._write_script()
            self.assertTrue(handles[0].closed)
            self.assertTrue(Path(handles[0].name).is_file())

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
