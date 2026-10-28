"""Read-only previews, accurate risk labels and stale-review protection."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.run_summary import DISPLAY_LIMIT, build_run_summary
from src.core.task_contracts import (
    BypassFileConfig, BypassRunConfig, EmlRunConfig, EmlTaskConfig, OcrRunConfig,
    PdfRunConfig, RunPlan, SourceDisposition, SyncGroupConfig, SyncRunConfig, TaskStep,
)


class RunSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.source.mkdir()
        self.target.mkdir()

    def file(self, folder, name, content=b"data"):
        path = folder / name
        path.write_bytes(content)
        return str(path)

    def sync_plan(self, **options):
        return RunPlan({TaskStep.SYNC: SyncRunConfig([
            SyncGroupConfig("daily", [str(self.source), str(self.target)], **options),
        ])})

    def test_sync_preview_does_not_create_backups_copy_or_delete(self):
        self.file(self.source, "sample.txt")
        old = self.file(self.target, "sample.txt", b"older")
        stamp = time.time() - 60
        os.utime(old, (stamp, stamp))
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with (patch("os.makedirs", side_effect=AssertionError("preview wrote a directory")),
              patch("shutil.copy2", side_effect=AssertionError("preview copied a file")),
              patch("os.remove", side_effect=AssertionError("preview deleted a file"))):
            summary = build_run_summary(self.sync_plan())
        self.assertEqual(summary.counts, {"archive": 1, "copy": 1})
        self.assertIn("move_sources", summary.risks)
        self.assertEqual({str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)
        self.assertFalse((self.target / "to be deleted").exists())

    def test_disabled_archive_means_permanent_deletion_not_recycle(self):
        self.file(self.source, "sample.txt")
        old = self.file(self.target, "sample.txt", b"older")
        stamp = time.time() - 60
        os.utime(old, (stamp, stamp))
        summary = build_run_summary(self.sync_plan(move_to_deleted=False))
        self.assertEqual(summary.counts["delete"], 1)
        self.assertNotIn("archive", summary.counts)
        self.assertIn("delete_policy", summary.risks)
        self.assertEqual(next(row.target for row in summary.entries if row.action == "delete"), "")

    def test_delete_policy_visible_even_if_no_current_actions(self):
        summary = build_run_summary(self.sync_plan(move_to_deleted=False))
        self.assertEqual(summary.total_entries, 0)
        self.assertIn("delete_policy", summary.risks)

    def test_missing_sync_folder_is_not_reported_as_zero_changes(self):
        self.target.rmdir()
        with self.assertRaises(FileNotFoundError):
            build_run_summary(self.sync_plan())

    def test_scan_failure_is_not_reported_as_zero_changes(self):
        with patch("src.core.sync_manager.os.listdir", side_effect=PermissionError("denied")):
            with self.assertRaises(OSError):
                build_run_summary(self.sync_plan())

    def test_conflicting_copies_are_labeled_as_preserved(self):
        self.file(self.source, "sample.txt", b"new")
        self.file(self.target, "sample.txt", b"different")
        summary = build_run_summary(self.sync_plan())
        self.assertEqual(summary.counts["conflict_backup"], 1)
        self.assertIn("conflicts", summary.risks)
        self.assertTrue(any(row.target.endswith("to be deleted") for row in summary.entries))

    def test_bypass_move_and_replace_are_not_confused(self):
        source = self.file(self.source, "book.xlsx")
        for disposition, action, risk in ((SourceDisposition.BACKUP, "archive", "move_sources"),
                                          (SourceDisposition.REPLACE, "replace", "replace_policy")):
            with self.subTest(disposition=disposition):
                config = BypassRunConfig([BypassFileConfig(source, str(self.target / "book.xlsm"), ".xlsm", True, disposition)], disposition)
                summary = build_run_summary(RunPlan({TaskStep.BYPASS: config}))
                self.assertEqual(summary.counts["convert"], 1)
                self.assertEqual(summary.counts[action], 1)
                self.assertIn(risk, summary.risks)

    def test_pdf_dual_output_is_shown_without_double_counting_input(self):
        source = self.file(self.source, "doc.pdf")
        target = str(self.target / "doc.zip")
        task = BypassFileConfig(source, target, ".zip", True, generate_pdf_html=True)
        summary = build_run_summary(RunPlan({TaskStep.BYPASS: BypassRunConfig([task])}))
        self.assertEqual(summary.counts, {"convert": 1, "extra_output": 1})
        self.assertEqual(summary.entries[1].target, str(self.target / "doc.html"))

    def test_existing_bypass_output_is_not_described_as_safe_overwrite(self):
        source = self.file(self.source, "book.xlsx")
        target = self.file(self.target, "book.xlsm")
        summary = build_run_summary(RunPlan({TaskStep.BYPASS: BypassRunConfig([
            BypassFileConfig(source, target, ".xlsm", True),
        ])}))
        self.assertIn("target_exists", summary.risks)

    def test_pdf_summary_counts_inputs_not_pages_and_does_not_create_output(self):
        source = self.file(self.source, "doc.pdf", b"not opened by summary")
        output = str(self.target / "new" / "images")
        summary = build_run_summary(RunPlan({TaskStep.PDF: PdfRunConfig([source], output)}))
        self.assertEqual(summary.counts["convert"], 1)
        self.assertIn("dynamic_outputs", summary.notes)
        self.assertFalse(Path(output).exists())

    def test_eml_preview_excludes_other_files_and_does_not_render(self):
        self.file(self.source, "mail.eml")
        self.file(self.source, "note.txt")
        config = EmlRunConfig([EmlTaskConfig("mail", str(self.source), str(self.target))])
        summary = build_run_summary(RunPlan({TaskStep.EML: config}))
        self.assertEqual(summary.counts["convert"], 1)
        self.assertEqual(summary.entries[0].group, "mail")

    def test_chained_ocr_counts_are_explicitly_unknown(self):
        source = self.file(self.source, "doc.pdf")
        summary = build_run_summary(RunPlan({
            TaskStep.PDF: PdfRunConfig([source], str(self.target)), TaskStep.OCR: OcrRunConfig([]),
        }, chain_outputs=True))
        self.assertIsNone(summary.entries[-1].count)
        self.assertIn("chained_ocr", summary.notes)

    def test_same_plan_is_stable_but_changed_file_changes_fingerprint(self):
        source = self.file(self.source, "a.txt")
        plan = self.sync_plan()
        first = build_run_summary(plan)
        self.assertEqual(first.fingerprint, build_run_summary(plan).fingerprint)
        Path(source).write_bytes(b"changed input")
        self.assertNotEqual(first.fingerprint, build_run_summary(plan).fingerprint)

    def test_text_only_ocr_keeps_image_name_and_exposes_txt_overwrite(self):
        path = self.file(self.source, "image.png")
        text = self.file(self.source, "image.txt", b"important text")
        plan = RunPlan({TaskStep.OCR: OcrRunConfig([path], rule_mode="full_text_txt")})
        summary = build_run_summary(plan)
        self.assertEqual(summary.counts, {"ocr": 1, "overwrite": 1})
        self.assertIn("overwrite_text", summary.risks)
        self.assertNotIn("rename", summary.counts)
        self.assertEqual(Path(text).read_bytes(), b"important text")

    def test_chained_unknown_counts_do_not_appear_as_zero(self):
        path = self.file(self.source, "doc.pdf")
        plan = RunPlan({TaskStep.PDF: PdfRunConfig([path], str(self.target)),
                        TaskStep.OCR: OcrRunConfig([], export_txt=True)}, chain_outputs=True)
        summary = build_run_summary(plan)
        self.assertEqual(summary.pending_counts, ["rename", "text_output"])
        self.assertIn("ocr_text_policy", summary.risks)

    def test_adding_file_changes_fingerprint_even_for_previously_empty_group(self):
        plan = self.sync_plan()
        first = build_run_summary(plan)
        self.file(self.source, "appeared.txt")
        self.assertNotEqual(first.fingerprint, build_run_summary(plan).fingerprint)

    def test_new_output_appearing_invalidates_preview(self):
        source = self.file(self.source, "a.pdf")
        output = str(self.target / "a.zip")
        plan = RunPlan({TaskStep.BYPASS: BypassRunConfig([BypassFileConfig(source, output, ".zip", True)])})
        first = build_run_summary(plan)
        Path(output).write_bytes(b"new output")
        self.assertNotEqual(first.fingerprint, build_run_summary(plan).fingerprint)

    def test_display_limit_does_not_truncate_totals_or_fingerprint(self):
        paths = [self.file(self.source, f"img{index}.png") for index in range(DISPLAY_LIMIT + 1)]
        plan = RunPlan({TaskStep.OCR: OcrRunConfig(paths)})
        first = build_run_summary(plan)
        self.assertEqual(len(first.entries), DISPLAY_LIMIT)
        self.assertEqual(first.total_entries, DISPLAY_LIMIT + 1)
        self.assertEqual(first.counts["rename"], DISPLAY_LIMIT + 1)
        Path(paths[-1]).write_bytes(b"change beyond visible rows")
        self.assertNotEqual(first.fingerprint, build_run_summary(plan).fingerprint)


if __name__ == "__main__":
    unittest.main()
