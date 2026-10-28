import os
import shutil
import tempfile
import unittest

from src.core import bypass_planner
from src.core.task_contracts import TaskValidationError


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as file:
        file.write(data)
    return path


class BypassPlannerScanTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.src = os.path.join(self.root, "src")
        _touch(os.path.join(self.src, "a.xlsx"), b"1234")
        _touch(os.path.join(self.src, "notes.txt"))
        _touch(os.path.join(self.src, "sub", "b.pdf"))
        _touch(os.path.join(self.src, "Original Backup", "old.docx"))
        _touch(os.path.join(self.src, ".git", "c.pptx"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _names(self, discovered):
        return sorted(os.path.relpath(path, self.src).replace("\\", "/") for path, _size in discovered)

    def test_flat_scan_lists_supported_top_level_files_with_sizes(self):
        discovered = bypass_planner.scan_source_files(self.src, recursive=False)
        self.assertEqual(self._names(discovered), ["a.xlsx"])
        self.assertEqual(discovered[0][1], 4)

    def test_recursive_scan_skips_backup_and_system_folders(self):
        discovered = bypass_planner.scan_source_files(self.src, recursive=True)
        self.assertEqual(self._names(discovered), ["a.xlsx", "sub/b.pdf"])

    def test_recursive_scan_excludes_custom_target_inside_source(self):
        out_dir = os.path.join(self.src, "out")
        _touch(os.path.join(out_dir, "a.xlsb"))
        _touch(os.path.join(out_dir, "converted.docx"))
        exclude = bypass_planner.resolve_exclude_root(True, out_dir)

        discovered = bypass_planner.scan_source_files(self.src, recursive=True, exclude_root=exclude)

        self.assertEqual(self._names(discovered), ["a.xlsx", "sub/b.pdf"])

    def test_resolve_exclude_root_requires_custom_mode_and_existing_folder(self):
        self.assertEqual(bypass_planner.resolve_exclude_root(False, self.src), "")
        self.assertEqual(bypass_planner.resolve_exclude_root(True, os.path.join(self.root, "missing")), "")
        self.assertEqual(bypass_planner.resolve_exclude_root(True, self.src), bypass_planner.normalize_path(self.src))


class BypassPlannerFilterTests(unittest.TestCase):
    def test_inplace_mode_drops_files_already_in_target_format(self):
        def ext_for(ext):
            return bypass_planner.target_extension_for(ext, ".xlsx", ".pptx", ".docx", ".zip + .html")

        discovered = [("C:/s/a.xlsx", 1), ("C:/s/b.xls", 2), ("C:/s/c.pdf", 3)]

        filtered, skipped = bypass_planner.filter_discovered_files(discovered, ext_for, inplace_mode=True)

        self.assertEqual([path for path, _ in filtered], ["C:/s/b.xls", "C:/s/c.pdf"])
        self.assertEqual(skipped, 1)

        filtered, skipped = bypass_planner.filter_discovered_files(discovered, ext_for, inplace_mode=False)
        self.assertEqual(len(filtered), 3)
        self.assertEqual(skipped, 0)

    def test_target_and_display_extensions_for_pdf_zip_html(self):
        tgt = bypass_planner.target_extension_for(".PDF", ".xlsb", ".pptx", ".docx", ".zip + .html")
        self.assertEqual(tgt, ".zip")
        self.assertEqual(bypass_planner.display_target_extension(".pdf", tgt, ".zip + .html"), ".zip + .html")
        self.assertEqual(bypass_planner.display_target_extension(".pdf", ".zip", ".zip"), ".zip")
        self.assertEqual(bypass_planner.target_extension_for(".txt", ".xlsb", ".pptx", ".docx", ".zip"), "")

    def test_pdf_dual_output_rules(self):
        self.assertTrue(bypass_planner.is_pdf_dual_output(".pdf", ".zip + .html", False))
        self.assertTrue(bypass_planner.is_pdf_dual_output(".pdf", ".zip", True))
        self.assertFalse(bypass_planner.is_pdf_dual_output(".pdf", ".zip", False))
        self.assertFalse(bypass_planner.is_pdf_dual_output(".xlsx", ".zip + .html", True))


class BypassPlannerTargetTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.src = os.path.join(self.root, "src")
        self.out = os.path.join(self.root, "out")
        os.makedirs(self.out)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_dest_dir_mirrors_subfolders_in_custom_mode(self):
        src_file = _touch(os.path.join(self.src, "x", "y", "a.docx"))
        self.assertEqual(
            bypass_planner.resolve_dest_dir(src_file, self.src, self.out, inplace_mode=False),
            os.path.join(self.out, "x", "y"),
        )
        top_file = _touch(os.path.join(self.src, "b.docx"))
        self.assertEqual(bypass_planner.resolve_dest_dir(top_file, self.src, self.out, inplace_mode=False), self.out)

    def test_dest_dir_is_source_folder_in_inplace_mode(self):
        src_file = _touch(os.path.join(self.src, "x", "a.docx"))
        self.assertEqual(
            bypass_planner.resolve_dest_dir(src_file, self.src, self.src, inplace_mode=True),
            os.path.join(self.src, "x"),
        )

    def test_source_outside_source_folder_is_rejected(self):
        outside = _touch(os.path.join(self.root, "elsewhere", "a.xlsx"))
        with self.assertRaises(TaskValidationError) as ctx:
            bypass_planner.ensure_source_inside(outside, self.src)
        self.assertEqual(ctx.exception.message_key, "bypass_source_file_outside")
        bypass_planner.ensure_source_inside(_touch(os.path.join(self.src, "ok.xlsx")), self.src)

    def test_dest_escaping_target_is_rejected(self):
        with self.assertRaises(TaskValidationError) as ctx:
            bypass_planner.ensure_dest_inside_target(os.path.join(self.root, "other"), self.out)
        self.assertEqual(ctx.exception.message_key, "bypass_target_path_escaped")
        bypass_planner.ensure_dest_inside_target(os.path.join(self.out, "sub"), self.out)

    def test_same_as_source_gets_converted_suffix(self):
        src_file = _touch(os.path.join(self.src, "doc.pdf"))
        _touch(os.path.join(self.src, "doc_converted.pdf"))
        reserved = set()

        tgt = bypass_planner.allocate_target_path(src_file, self.src, ".pdf", reserved, check_pdf_html=False)

        self.assertEqual(tgt, os.path.join(self.src, "doc_converted_1.pdf"))

    def test_existing_and_reserved_targets_get_numbered_suffix(self):
        first = _touch(os.path.join(self.src, "book.xlsx"))
        second = _touch(os.path.join(self.src, "book.xls"))
        _touch(os.path.join(self.out, "book.xlsb"))
        reserved = set()

        tgt1 = bypass_planner.allocate_target_path(first, self.out, ".xlsb", reserved, check_pdf_html=False)
        bypass_planner.reserve_target(reserved, tgt1, include_html=False)
        tgt2 = bypass_planner.allocate_target_path(second, self.out, ".xlsb", reserved, check_pdf_html=False)

        self.assertEqual(tgt1, os.path.join(self.out, "book_1.xlsb"))
        self.assertEqual(tgt2, os.path.join(self.out, "book_2.xlsb"))

    def test_pdf_html_viewer_collision_is_detected(self):
        src_file = _touch(os.path.join(self.src, "scan.pdf"))
        _touch(os.path.join(self.out, "scan.html"))

        without_html = bypass_planner.allocate_target_path(src_file, self.out, ".zip", set(), check_pdf_html=False)
        with_html = bypass_planner.allocate_target_path(src_file, self.out, ".zip", set(), check_pdf_html=True)

        self.assertEqual(without_html, os.path.join(self.out, "scan.zip"))
        self.assertEqual(with_html, os.path.join(self.out, "scan_1.zip"))

    def test_reserved_html_viewer_blocks_next_pdf(self):
        reserved = set()
        bypass_planner.reserve_target(reserved, os.path.join(self.out, "scan.zip"), include_html=True)
        self.assertIn(bypass_planner.normalize_path(os.path.join(self.out, "scan.html")), reserved)
        self.assertTrue(
            bypass_planner.target_collides(os.path.join(self.out, "scan.zip"), ".pdf", reserved, check_pdf_html=True)
        )


if __name__ == "__main__":
    unittest.main()
