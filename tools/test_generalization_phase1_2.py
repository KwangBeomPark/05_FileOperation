import os
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.core.ocr_processor import (
    extract_by_rule,
    format_rename_filename,
    export_text_file,
)
from src.core.sync_manager import SyncManager
from src.core.task_contracts import (
    OcrRunConfig,
    RunPlan,
    SyncRunConfig,
    TaskStep,
)
from src.core.task_runner import TaskRunner


class GeneralizationPhase1And2Tests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. OCR Rule Engine Tests
    def test_extract_by_rule_presets(self):
        # Promotion preset
        text_promo = "Product Event 2026\nItem Code: P1234567\nPromotion: 250101-99\nThank you"
        res_promo = extract_by_rule(text_promo, rule_mode="promotion")
        self.assertEqual(res_promo, "250101-99")

        # Invoice number preset
        text_inv = "TAX INVOICE\nInvoice No: INV-2026-9876\nDate: 2026-03-15\nTotal: $500"
        res_inv = extract_by_rule(text_inv, rule_mode="invoice_number")
        self.assertEqual(res_inv, "INV-2026-9876")

        # Date preset
        text_date = "Delivered on 2026-11-20 at 14:00"
        res_date = extract_by_rule(text_date, rule_mode="date_ymd")
        self.assertEqual(res_date, "2026-11-20")

        # Digits preset
        text_digits = "Barcode scan result: 8801234567890"
        res_digits = extract_by_rule(text_digits, rule_mode="digits")
        self.assertEqual(res_digits, "8801234567890")

        # First line preset
        text_first = "\n\n  Document Header Title  \nSecond line"
        res_first = extract_by_rule(text_first, rule_mode="first_line")
        self.assertEqual(res_first, "Document_Header_Title")

        # Custom regex preset
        text_custom = "Serial tracking: [SN-XYZ-404] verified"
        res_custom = extract_by_rule(text_custom, rule_mode="custom_regex", custom_pattern=r"SN-[A-Z]+-\d+")
        self.assertEqual(res_custom, "SN-XYZ-404")

        # Full text mode returns sanitized first 60 chars
        text_full = "Line 1\nLine 2\nLine 3"
        res_full = extract_by_rule(text_full, rule_mode="full_text_txt")
        self.assertEqual(res_full, "Line_1_Line_2_Line_3")

    def test_format_rename_filename_templates(self):
        original = "raw_scan_01.png"
        match = "INV-1001"

        # Default template
        out1 = format_rename_filename("{match}", original_filename=original, match_token=match)
        self.assertEqual(out1, "INV-1001.png")

        # Composite template with date and original
        out2 = format_rename_filename("{date}_{match}_{original}_{seq}", original_filename=original, match_token=match, seq_index=3)
        self.assertIn("_INV-1001_raw_scan_01_003.png", out2)

        # Fallback when match is empty
        out_fallback = format_rename_filename("{match}", original_filename=original, match_token="")
        self.assertEqual(out_fallback, "raw_scan_01.png")

    def test_export_text_file(self):
        img_path = os.path.join(self.test_dir, "sample_doc.png")
        with open(img_path, "wb") as f:
            f.write(b"fake image data")

        txt_path = export_text_file(img_path, "Extracted OCR body text here.")
        self.assertTrue(os.path.exists(txt_path))
        self.assertEqual(txt_path, os.path.join(self.test_dir, "sample_doc.txt"))
        with open(txt_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Extracted OCR body text here.")

    # 2. SyncManager Generalization Tests
    def test_sync_manager_subfolders_and_excludes(self):
        dir_a = os.path.join(self.test_dir, "dir_a")
        dir_b = os.path.join(self.test_dir, "dir_b")
        os.makedirs(os.path.join(dir_a, "nested", "sub"), exist_ok=True)
        os.makedirs(dir_b, exist_ok=True)

        file_sync = os.path.join(dir_a, "nested", "sub", "valid.txt")
        file_temp = os.path.join(dir_a, "nested", "temp.tmp")
        file_backup = os.path.join(dir_a, "backup.bak")

        with open(file_sync, "w", encoding="utf-8") as f:
            f.write("synchronize me")
        with open(file_temp, "w", encoding="utf-8") as f:
            f.write("ignore temp")
        with open(file_backup, "w", encoding="utf-8") as f:
            f.write("ignore backup")

        manager = SyncManager(
            folders=[dir_a, dir_b],
            include_subfolders=True,
            exclude_patterns=["*.tmp", "*.bak"],
            archive_folder_name="my_custom_archive",
        )
        actions = manager.analyze_sync()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["filename"], os.path.join("nested", "sub", "valid.txt"))

        success, fail, errors = manager.execute_sync(actions)
        self.assertEqual(success, 1)
        self.assertEqual(fail, 0)
        self.assertTrue(os.path.exists(os.path.join(dir_b, "nested", "sub", "valid.txt")))
        self.assertFalse(os.path.exists(os.path.join(dir_b, "nested", "temp.tmp")))

    def test_sync_manager_one_way_mode(self):
        src = os.path.join(self.test_dir, "source")
        target = os.path.join(self.test_dir, "target")
        os.makedirs(src, exist_ok=True)
        os.makedirs(target, exist_ok=True)

        # File exists only in source
        with open(os.path.join(src, "from_src.txt"), "w", encoding="utf-8") as f:
            f.write("from source")
        # Newer file exists only in target
        with open(os.path.join(target, "from_target.txt"), "w", encoding="utf-8") as f:
            f.write("from target")

        manager = SyncManager(
            folders=[src, target],
            sync_mode="one_way",
        )
        actions = manager.analyze_sync()

        # In one-way mode, only source -> target actions should be planned!
        target_destinations = [act["target_folder"] for act in actions]
        self.assertTrue(all(dest == target for dest in target_destinations))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["filename"], "from_src.txt")

    def test_sync_manager_custom_archive_folder_name(self):
        dir_a = os.path.join(self.test_dir, "dir_a")
        dir_b = os.path.join(self.test_dir, "dir_b")
        os.makedirs(dir_a, exist_ok=True)
        os.makedirs(dir_b, exist_ok=True)

        # Newer file in dir_a, older in dir_b
        file_a = os.path.join(dir_a, "data.txt")
        file_b = os.path.join(dir_b, "data.txt")
        with open(file_b, "w", encoding="utf-8") as f:
            f.write("older version")
        os.utime(file_b, (1000, 1000))

        with open(file_a, "w", encoding="utf-8") as f:
            f.write("newer version")
        os.utime(file_a, (5000, 5000))

        archive_dir = "custom_backup_vault"
        manager = SyncManager(
            folders=[dir_a, dir_b],
            move_to_deleted=True,
            archive_folder_name=archive_dir,
        )
        actions = manager.analyze_sync()
        self.assertEqual(len(actions), 2)  # 1 to archive old in dir_b, 1 to copy new from dir_a to dir_b

        success, fail, errors = manager.execute_sync(actions)
        self.assertEqual(fail, 0)
        self.assertTrue(os.path.exists(os.path.join(dir_b, archive_dir, "data.txt")))

    # 3. Dynamic Step Order and Pipeline Chaining Tests
    def test_run_plan_dynamic_step_order(self):
        custom_order = [TaskStep.PDF, TaskStep.OCR, TaskStep.SYNC]
        plan = RunPlan(
            configs={
                TaskStep.SYNC: SyncRunConfig([]),
                TaskStep.OCR: OcrRunConfig([]),
                TaskStep.PDF: Mock(),
            },
            step_order=custom_order,
            chain_outputs=True,
        )
        self.assertEqual(plan.active_steps, [TaskStep.PDF, TaskStep.OCR, TaskStep.SYNC])
        self.assertTrue(plan.chain_outputs)

    def test_task_runner_chains_eml_and_pdf_outputs_to_ocr(self):
        mock_config = Mock()
        mock_config.get.return_value = ""

        plan = RunPlan(
            configs={
                TaskStep.OCR: OcrRunConfig(
                    image_paths=[],  # Initially empty, chaining should feed them!
                    rule_mode="promotion",
                )
            },
            step_order=[TaskStep.OCR],
            chain_outputs=True,
        )

        runner = TaskRunner(mock_config, plan)
        # Simulate EML generating images
        runner.chained_image_paths = [
            os.path.join(self.test_dir, "gen_1.png"),
            os.path.join(self.test_dir, "gen_2.png"),
        ]
        for p in runner.chained_image_paths:
            with open(p, "wb") as f:
                f.write(b"dummy")

        with patch.object(runner.ocr_processor, "process_image") as mock_proc, \
             patch.object(runner, "_rename_ocr_file", return_value="renamed.png"):
            mock_proc.return_value = (True, "mocked_path", "Extracted text", None)
            _ = runner.run()
            self.assertEqual(mock_proc.call_count, 2)


if __name__ == "__main__":
    unittest.main()
