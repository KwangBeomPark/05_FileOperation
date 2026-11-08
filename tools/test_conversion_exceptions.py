"""Regression checks for conversion errors and fallback boundaries."""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.core.eml_converter import EMLConversionError, EMLConverter
from src.core.ocr_processor import OCRExtractionError, OCRProcessor
from src.core.pdf_converter import PDFConversionError, PDFConverter
from src.core.task_contracts import PdfRunConfig, StepResult, StepStatus, TaskStep
from src.core.task_runner import RunnerCallbacks, TaskRunner


class ConversionExceptionTests(unittest.TestCase):
    def test_eml_parse_error_retains_cause(self):
        failure = ValueError("bad message")
        converter = EMLConverter(MagicMock())
        with patch("src.core.eml_converter.os.path.exists", return_value=True), \
             patch("builtins.open", side_effect=failure), \
             self.assertRaises(EMLConversionError) as caught:
            converter.extract_html_from_eml("test.eml")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertIn("bad message", str(caught.exception))

    def test_pdf_read_error_retains_cause(self):
        failure = ValueError("bad pdf")
        with patch("src.core.pdf_converter.fitz.open", side_effect=failure), \
             self.assertRaises(PDFConversionError) as caught:
            PDFConverter(MagicMock()).get_page_count("test.pdf")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertIn("bad pdf", str(caught.exception))

    def test_pdf_missing_file(self):
        with patch("src.core.pdf_converter.os.path.exists", return_value=False), \
             self.assertRaises(PDFConversionError) as caught:
            PDFConverter(MagicMock()).convert("missing.pdf", "output")
        self.assertIn("missing.pdf", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_pdf_conversion_and_thumbnail_retain_cause(self):
        failure = ValueError("render failed")
        converter = PDFConverter(MagicMock())
        with patch("src.core.pdf_converter.os.path.exists", return_value=True), \
             patch("src.core.pdf_converter.fitz.open", side_effect=failure), \
             self.assertRaises(PDFConversionError) as caught:
            converter.convert("test.pdf", "output")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertIn("render failed", str(caught.exception))
        with patch("src.core.pdf_converter.Image.open", side_effect=failure), \
             self.assertRaises(PDFConversionError) as caught:
            converter.create_thumbnail("test.png")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertIn("render failed", str(caught.exception))

    def test_eml_browser_install_failure_retains_cause(self):
        failure = subprocess.CalledProcessError(1, "mock")
        converter = EMLConverter(MagicMock())
        with patch.object(converter, "_get_playwright_install_command", return_value=([], {})), \
             patch("src.core.eml_converter.subprocess.run", side_effect=failure), \
             self.assertRaises(EMLConversionError) as caught:
            converter.install_playwright_browsers()
        self.assertIs(caught.exception.__cause__, failure)
        self.assertIn("브라우저", str(caught.exception))

    def test_eml_cached_install_failure_skips_install(self):
        failure = RuntimeError("Executable doesn't exist")
        converter = EMLConverter(MagicMock())
        converter.playwright_install_failed = True
        playwright = MagicMock()
        playwright.sync_playwright.return_value.__enter__.return_value.chromium.launch.side_effect = failure
        temp_file = MagicMock()
        temp_file.__enter__.return_value.name = "synthetic.html"
        with patch.dict("sys.modules", {"playwright.sync_api": playwright}), \
             patch.object(converter, "extract_html_from_eml", return_value="html"), \
             patch.object(converter, "install_playwright_browsers") as install, \
             patch("src.core.eml_converter.tempfile.NamedTemporaryFile", return_value=temp_file), \
             patch("src.core.eml_converter.os.path.exists", return_value=False), \
             self.assertRaises(EMLConversionError) as caught:
            converter.convert_eml_to_image("test.eml", "test.png")
        self.assertIs(caught.exception.__cause__, failure)
        install.assert_not_called()

    def test_eml_failed_install_is_cached_for_next_conversion(self):
        launch_failure = RuntimeError("Executable doesn't exist")
        install_cause = OSError("network unavailable")
        install_failure = EMLConversionError("install failed")
        install_failure.__cause__ = install_cause
        converter = EMLConverter(MagicMock())
        playwright = MagicMock()
        playwright.sync_playwright.return_value.__enter__.return_value.chromium.launch.side_effect = launch_failure
        temp_file = MagicMock()
        temp_file.__enter__.return_value.name = "synthetic.html"
        with patch.dict("sys.modules", {"playwright.sync_api": playwright}), \
             patch.object(converter, "extract_html_from_eml", return_value="html"), \
             patch.object(converter, "install_playwright_browsers", side_effect=install_failure) as install, \
             patch("src.core.eml_converter.tempfile.NamedTemporaryFile", return_value=temp_file), \
             patch("src.core.eml_converter.os.path.exists", return_value=False):
            with self.assertRaises(EMLConversionError) as first:
                converter.convert_eml_to_image("first.eml", "first.png")
            self.assertIs(first.exception, install_failure)
            self.assertIs(first.exception.__cause__, install_cause)
            self.assertEqual(str(first.exception), "install failed")
            self.assertTrue(converter.playwright_install_failed)
            with self.assertRaises(EMLConversionError) as second:
                converter.convert_eml_to_image("second.eml", "second.png")
            self.assertIs(second.exception.__cause__, launch_failure)
            self.assertIn("이전 준비 시도도 실패", str(second.exception))
            install.assert_called_once_with()

    def test_runner_continues_after_pdf_conversion_error(self):
        runner = TaskRunner.__new__(TaskRunner)
        runner.is_running = True
        runner.language = "en"
        runner.chained_image_paths = []
        runner.pdf_converter = MagicMock()
        runner.pdf_converter.convert.side_effect = [PDFConversionError("bad"), ["second.jpg"]]
        result = StepResult(TaskStep.PDF)
        with patch("src.core.task_runner.os.makedirs"):
            runner._run_pdf(PdfRunConfig(["first.pdf", "second.pdf"], "output"), result, RunnerCallbacks())
        self.assertEqual(runner.pdf_converter.convert.call_count, 2)
        self.assertEqual(result.status, StepStatus.PARTIAL)
        self.assertEqual(result.success_count, 1)
        self.assertEqual(runner.chained_image_paths, ["second.jpg"])

    def test_ocr_fallback_and_aggregated_failure(self):
        with patch.object(OCRProcessor, "setup_tesseract"):
            processor = OCRProcessor(MagicMock())
        with patch.object(processor, "check_tesseract_installed", return_value=True), \
             patch("src.core.ocr_processor.Image.open", side_effect=ValueError("bad image")), \
             patch("src.core.ocr_processor.extract_text_with_windows_ocr", return_value=" fallback "):
            self.assertEqual(processor.extract_text("test.png"), "fallback")
        with patch.object(processor, "check_tesseract_installed", return_value=True), \
             patch("src.core.ocr_processor.Image.open", side_effect=ValueError("bad image")), \
             patch("src.core.ocr_processor.extract_text_with_windows_ocr", side_effect=RuntimeError("offline")), \
             self.assertRaises(OCRExtractionError) as caught:
            processor.extract_text("test.png")
        self.assertIn("bad image", str(caught.exception))
        self.assertIn("offline", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
