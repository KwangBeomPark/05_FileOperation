import os
import tempfile
import unittest
from PyQt6.QtWidgets import QApplication

from src.core.task_contracts import SourceDisposition
from src.ui.bypass_tab import BypassTab
from src.utils.config_manager import ConfigManager

# Headless / shared QApplication
app = QApplication.instance() or QApplication([])


class BypassRecursiveAndHtmlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "settings.json")
        self.config_manager = ConfigManager(config_file=self.config_path)
        self.tab = BypassTab(self.config_manager)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_recursive_scan_finds_nested_files_and_skips_backup(self):
        src_root = os.path.join(self.temp_dir.name, "source")
        sub1 = os.path.join(src_root, "sub1")
        sub2 = os.path.join(src_root, "sub2", "deep")
        backup = os.path.join(src_root, "Original Backup")
        git_dir = os.path.join(src_root, ".git")

        for d in (sub1, sub2, backup, git_dir):
            os.makedirs(d, exist_ok=True)

        root_file = os.path.join(src_root, "root.pdf")
        sub1_file = os.path.join(sub1, "report.xlsx")
        sub2_file = os.path.join(sub2, "nested.pdf")
        backup_file = os.path.join(backup, "ignore.pdf")
        git_file = os.path.join(git_dir, "git_ignore.pdf")

        for f in (root_file, sub1_file, sub2_file, backup_file, git_file):
            with open(f, "wb") as fh:
                fh.write(b"%PDF-1.4 mock content")

        self.tab.set_source_folder_path(src_root)

        # 1. Non-recursive scan: only root_file should be found
        self.tab.check_recursive_scan.setChecked(False)
        self.tab.scan_source_folder()
        self.assertEqual(len(self.tab.scanned_files), 1)
        self.assertEqual(self.tab.scanned_files[0], root_file)
        self.assertEqual(self.tab.file_table.item(0, 0).text(), "root.pdf")

        # 2. Recursive scan: root_file, sub1_file, sub2_file found; backup and git skipped
        self.tab.check_recursive_scan.setChecked(True)
        self.tab.scan_source_folder()
        self.assertEqual(len(self.tab.scanned_files), 3)
        scanned_norm = [os.path.normcase(os.path.abspath(p)) for p in self.tab.scanned_files]
        self.assertIn(os.path.normcase(os.path.abspath(root_file)), scanned_norm)
        self.assertIn(os.path.normcase(os.path.abspath(sub1_file)), scanned_norm)
        self.assertIn(os.path.normcase(os.path.abspath(sub2_file)), scanned_norm)
        self.assertNotIn(os.path.normcase(os.path.abspath(backup_file)), scanned_norm)
        self.assertNotIn(os.path.normcase(os.path.abspath(git_file)), scanned_norm)

    def test_build_run_config_mirrors_directory_tree_in_custom_mode(self):
        src_root = os.path.join(self.temp_dir.name, "source")
        tgt_root = os.path.join(self.temp_dir.name, "target")
        sub_dir = os.path.join(src_root, "department", "finance")
        os.makedirs(sub_dir, exist_ok=True)
        os.makedirs(tgt_root, exist_ok=True)

        doc_pdf = os.path.join(sub_dir, "statement.pdf")
        with open(doc_pdf, "wb") as f:
            f.write(b"%PDF-1.4 mock content")

        self.tab.set_source_folder_path(src_root)
        self.tab.set_target_folder_path(tgt_root)
        self.tab.radio_custom.setChecked(True)
        self.tab.check_recursive_scan.setChecked(True)
        self.tab.check_pdf_html.setChecked(True)
        self.tab.scan_source_folder()

        run_config = self.tab.build_run_config()
        self.assertIsNotNone(run_config)
        self.assertTrue(run_config.recursive_scan)
        self.assertTrue(run_config.generate_pdf_html)
        self.assertEqual(len(run_config.tasks), 1)

        task = run_config.tasks[0]
        self.assertEqual(task.src, doc_pdf)
        self.assertTrue(task.generate_pdf_html)
        expected_target_dir = os.path.join(tgt_root, "department", "finance")
        self.assertEqual(os.path.dirname(task.tgt), expected_target_dir)
        self.assertEqual(os.path.basename(task.tgt), "statement.zip")

    def test_build_run_config_in_place_keeps_same_subfolder(self):
        src_root = os.path.join(self.temp_dir.name, "source")
        sub_dir = os.path.join(src_root, "sub")
        os.makedirs(sub_dir, exist_ok=True)

        doc_pdf = os.path.join(sub_dir, "doc.pdf")
        with open(doc_pdf, "wb") as f:
            f.write(b"%PDF-1.4 mock content")

        self.tab.set_source_folder_path(src_root)
        self.tab.radio_inplace.setChecked(True)
        self.tab.check_recursive_scan.setChecked(True)
        self.tab.check_pdf_html.setChecked(True)
        self.tab.scan_source_folder()

        run_config = self.tab.build_run_config()
        self.assertIsNotNone(run_config)
        self.assertEqual(run_config.source_disposition, SourceDisposition.REPLACE)
        task = run_config.tasks[0]
        self.assertEqual(os.path.dirname(task.tgt), sub_dir)
        self.assertEqual(os.path.basename(task.tgt), "doc.zip")
        self.assertTrue(task.generate_pdf_html)


    def test_auto_scan_on_source_folder_set_and_in_memory_format_update(self):
        src_root = os.path.join(self.temp_dir.name, "source_auto")
        os.makedirs(src_root, exist_ok=True)
        pdf_file = os.path.join(src_root, "doc.pdf")
        with open(pdf_file, "wb") as f:
            f.write(b"%PDF-1.4 1234567890")

        # 1. Setting source folder automatically triggers scan
        self.tab.set_source_folder_path(src_root)
        self.assertEqual(len(self.tab.scanned_files), 1)
        self.assertEqual(self.tab.file_table.rowCount(), 1)
        self.assertTrue("Total:" in self.tab.summary_label.text() or "총 용량:" in self.tab.summary_label.text())

        # 2. In-memory format update on pdf_combo change
        self.tab.pdf_combo.setCurrentText(".zip + .html")
        self.assertEqual(self.tab.file_table.item(0, 2).text(), ".zip + .html")
        self.assertTrue(self.tab.check_pdf_html.isChecked())

        # In custom mode, converting .pdf to .pdf is allowed and updates table column 2
        self.tab.radio_custom.setChecked(True)
        self.tab.pdf_combo.setCurrentText(".pdf")
        self.assertEqual(self.tab.file_table.item(0, 2).text(), ".pdf")
        self.assertFalse(self.tab.check_pdf_html.isChecked())



    def test_pdf_dual_output_protects_existing_html_file(self):
        from src.core.bypass_converter import BypassConverter
        converter = BypassConverter()
        src_pdf = os.path.join(self.temp_dir.name, 'report.pdf')
        with open(src_pdf, 'wb') as f:
            f.write(b'%PDF-1.4 sample content')
        tgt_zip = os.path.join(self.temp_dir.name, 'report.zip')
        tgt_html = os.path.join(self.temp_dir.name, 'report.html')

        with open(tgt_html, 'w', encoding='utf-8') as f:
            f.write('<html>existing important report</html>')

        success, msg = converter.convert_file(
            src_path=src_pdf,
            tgt_path=tgt_zip,
            target_ext='.zip',
            generate_pdf_html=True,
        )
        self.assertFalse(success)
        self.assertIn('TARGET_ALREADY_EXISTS', msg)
        with open(tgt_html, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), '<html>existing important report</html>')

    def test_inplace_mode_filters_discovered_files_when_combo_changes(self):
        src_root = os.path.join(self.temp_dir.name, 'source_filter')
        os.makedirs(src_root, exist_ok=True)
        xlsx_file = os.path.join(src_root, 'book.xlsx')
        with open(xlsx_file, 'wb') as f:
            f.write(b'mock xlsx')

        self.tab.radio_inplace.setChecked(True)
        self.tab.excel_combo.setCurrentText('.xlsb')
        self.tab.set_source_folder_path(src_root)
        self.assertEqual(len(self.tab.scanned_files), 1)

        self.tab.excel_combo.setCurrentText('.xlsx')
        self.assertEqual(len(self.tab.scanned_files), 0)

        self.tab.excel_combo.setCurrentText('.xlsm')
        self.assertEqual(len(self.tab.scanned_files), 1)

    def test_case_insensitive_pdf_handles_capital_extension(self):
        src_root = os.path.join(self.temp_dir.name, 'source_capital')
        os.makedirs(src_root, exist_ok=True)
        pdf_file = os.path.join(src_root, 'UPPER.PDF')
        with open(pdf_file, 'wb') as f:
            f.write(b'%PDF-1.4 upper test')

        self.tab.set_source_folder_path(src_root)
        self.tab.pdf_combo.setCurrentText('.zip + .html')
        run_config = self.tab.build_run_config()
        self.assertIsNotNone(run_config)
        self.assertEqual(len(run_config.tasks), 1)
        task = run_config.tasks[0]
        self.assertTrue(task.generate_pdf_html)
        self.assertEqual(task.ext, '.zip')



    def test_convert_pdf_to_standalone_html_generates_valid_html(self):
        from src.core.bypass_converter import BypassConverter
        converter = BypassConverter()
        src_pdf = os.path.join(self.temp_dir.name, 'doc_standalone.pdf')
        with open(src_pdf, 'wb') as f:
            f.write(b'%PDF-1.4 standalone test content')
        tgt_html = os.path.join(self.temp_dir.name, 'doc_standalone.html')

        success, msg = converter.convert_file(
            src_path=src_pdf,
            tgt_path=tgt_html,
            target_ext='.html',
            generate_pdf_html=False,
        )
        self.assertTrue(success, f"Failed to convert PDF to HTML: {msg}")
        self.assertTrue(os.path.isfile(tgt_html))
        with open(tgt_html, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('<!DOCTYPE html>', content)
        self.assertIn('doc_standalone.pdf', content)

    def test_capacity_impact_calculates_correctly_when_source_is_replaced(self):
        from unittest.mock import patch
        src_root = os.path.join(self.temp_dir.name, 'source_capacity')
        os.makedirs(src_root, exist_ok=True)
        pdf_file = os.path.join(src_root, 'sample.pdf')
        with open(pdf_file, 'wb') as f:
            f.write(b'%PDF-1.4 sample content with 100 bytes' + b'x' * 60)

        self.tab.set_source_folder_path(src_root)
        self.assertEqual(len(self.tab.scanned_files), 1)

        tgt_file = os.path.join(src_root, 'sample.zip')
        with open(tgt_file, 'wb') as f:
            f.write(b'PK' + b'y' * 50)

        class FakeWorker:
            tasks = [{'src': pdf_file, 'tgt': tgt_file, 'generate_pdf_html': False}]
        self.tab.worker = FakeWorker()
        self.tab._pre_conversion_src_size = 160

        # Remove source file as in REPLACE mode
        if os.path.exists(pdf_file):
            os.remove(pdf_file)

        with patch("src.ui.bypass_tab.QMessageBox.information"), patch("src.ui.bypass_tab.show_toast"):
            self.tab.on_finished(True, "변환 완료")
        self.assertTrue(self.tab.open_folder_btn.isEnabled())
        summary_text = self.tab.summary_label.text()
        self.assertIn("→", summary_text)

    def test_sorting_enabled_does_not_corrupt_build_run_config_target_extensions(self):
        src_root = os.path.join(self.temp_dir.name, 'source_sort')
        os.makedirs(src_root, exist_ok=True)
        f_pdf = os.path.join(src_root, 'z_file.pdf')
        f_xlsx = os.path.join(src_root, 'a_file.xlsx')
        with open(f_pdf, 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with open(f_xlsx, 'wb') as f:
            f.write(b'mock xlsx')

        self.tab.set_source_folder_path(src_root)
        self.assertEqual(len(self.tab.scanned_files), 2)

        # Enable sorting and trigger sort
        self.tab.file_table.setSortingEnabled(True)
        self.tab.file_table.sortItems(0)

        run_config = self.tab.build_run_config()
        self.assertIsNotNone(run_config)
        self.assertEqual(len(run_config.tasks), 2)
        task_map = {os.path.basename(t.src): t for t in run_config.tasks}
        self.assertEqual(task_map['z_file.pdf'].ext, '.zip')
        self.assertEqual(task_map['a_file.xlsx'].ext, '.xlsb')



    def test_html_generation_race_does_not_delete_foreign_file(self):
        from src.core.bypass_converter import BypassConverter
        converter = BypassConverter()
        src_pdf = os.path.join(self.temp_dir.name, 'foreign_test.pdf')
        with open(src_pdf, 'wb') as f:
            f.write(b'%PDF-1.4 test')
        existing_html = os.path.join(self.temp_dir.name, 'foreign_test.html')
        with open(existing_html, 'w', encoding='utf-8') as f:
            f.write('<html>foreign existing file content</html>')

        success, msg = converter._generate_pdf_html_viewer(src_pdf, existing_html)
        self.assertFalse(success)
        self.assertIn('TARGET_ALREADY_EXISTS', msg)
        self.assertTrue(os.path.isfile(existing_html))
        with open(existing_html, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), '<html>foreign existing file content</html>')

    def test_double_click_uses_exact_stored_target_in_subfolder(self):
        from unittest.mock import patch
        src_root = os.path.join(self.temp_dir.name, 'source_dbclick')
        sub_dir = os.path.join(src_root, 'subfolder')
        os.makedirs(sub_dir, exist_ok=True)
        pdf_file = os.path.join(sub_dir, 'report.pdf')
        with open(pdf_file, 'wb') as f:
            f.write(b'%PDF-1.4 test')

        self.tab.set_source_folder_path(src_root)
        self.tab.check_recursive_scan.setChecked(True)
        self.tab.pdf_combo.setCurrentText('.zip + .html')
        self.tab.scan_source_folder()
        run_config = self.tab.build_run_config()
        self.assertIsNotNone(run_config)

        # Output html is in sub_dir
        expected_html = os.path.join(sub_dir, 'report.html')
        with open(expected_html, 'w', encoding='utf-8') as f:
            f.write('<html>actual html</html>')

        with patch('PyQt6.QtGui.QDesktopServices.openUrl') as mock_open:
            self.tab._on_table_row_double_clicked(0, 0)
            self.assertTrue(mock_open.called)
            opened_url = mock_open.call_args[0][0]
            self.assertEqual(os.path.normcase(opened_url.toLocalFile()), os.path.normcase(os.path.abspath(expected_html)))



    def test_on_finished_restores_action_buttons_and_clears_stale_queue(self):
        from unittest.mock import patch
        src_root = os.path.join(self.temp_dir.name, 'source_action_state')
        os.makedirs(src_root, exist_ok=True)
        sample = os.path.join(src_root, 'file.pdf')
        with open(sample, 'wb') as f:
            f.write(b'%PDF-1.4 mock')

        self.tab.set_source_folder_path(src_root)
        self.assertEqual(len(self.tab.scanned_files), 1)
        self.assertTrue(self.tab.start_btn.isEnabled())

        with patch("src.ui.bypass_tab.QMessageBox.information"), patch("src.ui.bypass_tab.show_toast"):
            self.tab.on_finished(True, "변환 완료")

        # Scan button must be restored and enabled for subsequent scans
        self.assertTrue(self.tab.scan_btn.isEnabled())
        # Start button must be disabled to prevent re-conversion of replaced files
        self.assertFalse(self.tab.start_btn.isEnabled())
        # Result open folder button must be enabled
        self.assertTrue(self.tab.open_folder_btn.isEnabled())
        # Stale scanned_files must be cleared
        self.assertEqual(self.tab.scanned_files, [])
        # Table rows must remain visible with completed status
        self.assertEqual(self.tab.file_table.rowCount(), 1)
        self.assertIn(self.tab._msg("common_completed"), self.tab.file_table.item(0, 3).text())

    def test_html_viewer_template_includes_print_optimization_and_security_badge(self):
        from src.core.bypass_converter import BypassConverter
        converter = BypassConverter()
        pdf_file = os.path.join(self.temp_dir.name, "badge_test.pdf")
        html_file = os.path.join(self.temp_dir.name, "badge_test.html")
        with open(pdf_file, "wb") as f:
            f.write(b"%PDF-1.4 print badge test")

        ok, err = converter._generate_pdf_html_viewer(pdf_file, html_file)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(html_file))

        with open(html_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("@media print", content)
        self.assertIn("security-badge", content)
        self.assertIn("btn-print", content)
        self.assertIn("triggerPrint", content)
        self.assertIn("Ctrl+P", content)

    def test_on_finished_triggers_taskbar_alert_and_beep(self):
        from unittest.mock import patch
        with patch("src.ui.bypass_tab.QApplication.alert") as mock_alert, \
             patch("winsound.MessageBeep") as mock_beep, \
             patch("src.ui.bypass_tab.QMessageBox.information"), \
             patch("src.ui.bypass_tab.show_toast"):
            self.tab.on_finished(True, "성공 완료")
            mock_alert.assert_called_once_with(self.tab, 0)
            mock_beep.assert_called_once()

    def test_drag_and_drop_respects_running_lock_and_file_fallback(self):
        from unittest.mock import MagicMock
        from PyQt6.QtCore import QUrl

        # 1. Ignored when running
        self.tab.is_running = True
        mock_event = MagicMock()
        self.tab.dragEnterEvent(mock_event)
        mock_event.ignore.assert_called_once()

        mock_drop_event = MagicMock()
        self.tab.dropEvent(mock_drop_event)
        mock_drop_event.ignore.assert_called_once()

        # 2. Dropping single file uses parent directory
        self.tab.is_running = False
        self.tab._ui_locked = False
        sub_folder = os.path.join(self.temp_dir.name, "dnd_parent")
        os.makedirs(sub_folder, exist_ok=True)
        file_path = os.path.join(sub_folder, "single_doc.pdf")
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4 mock")

        mock_drop_valid = MagicMock()
        mock_drop_valid.mimeData().urls.return_value = [QUrl.fromLocalFile(file_path)]
        self.tab.dropEvent(mock_drop_valid)
        self.assertEqual(
            os.path.normcase(self.tab.src_entry.text().strip()),
            os.path.normcase(sub_folder)
        )

    def test_on_finished_survives_oserror_in_capacity_calculation(self):
        from unittest.mock import patch, MagicMock
        self.tab.set_source_folder_path(self.temp_dir.name)
        # Mock worker tasks
        self.tab.worker = MagicMock()
        self.tab.worker.tasks = [{"src": "C:\\fake\\src.pdf", "tgt": "C:\\fake\\tgt.zip"}]

        with patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", side_effect=PermissionError("Access denied")), \
             patch("src.ui.bypass_tab.QMessageBox.information"), \
             patch("src.ui.bypass_tab.show_toast"):
            # Must not crash even if getsize throws PermissionError
            self.tab.on_finished(True, "완료 테스트")
            self.assertTrue(self.tab.scan_btn.isEnabled())
            self.assertTrue(self.tab.open_folder_btn.isEnabled())

    def test_html_viewer_template_includes_pdf_viewer_check_and_print_handling(self):
        from src.core.bypass_converter import BypassConverter
        converter = BypassConverter()
        pdf_file = os.path.join(self.temp_dir.name, "print_test.pdf")
        html_file = os.path.join(self.temp_dir.name, "print_test.html")
        with open(pdf_file, "wb") as f:
            f.write(b"%PDF-1.4 test")

        ok, err = converter._generate_pdf_html_viewer(pdf_file, html_file)
        self.assertTrue(ok)
        with open(html_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("pdfViewerEnabled", content)
        self.assertIn("pdfBlobUrl", content)
        self.assertIn("window.open(pdfBlobUrl", content)
        # Verify execution order: Blob and download hrefs must be set before supportsPdf return
        blob_idx = content.find("fallbackBtn.href = pdfBlobUrl")
        supports_idx = content.find("!supportsPdf")
        self.assertGreater(supports_idx, blob_idx, "Blob URL and download href must be bound before supportsPdf check")

    def test_pdf_html_viewer_enforces_50mb_size_limit(self):
        from src.core.bypass_converter import BypassConverter, MAX_PDF_HTML_SIZE_BYTES
        from unittest.mock import patch
        converter = BypassConverter()
        pdf_file = os.path.join(self.temp_dir.name, "giant.pdf")
        html_file = os.path.join(self.temp_dir.name, "giant.html")
        with open(pdf_file, "wb") as f:
            f.write(b"%PDF-1.4 test")

        with patch("os.path.getsize", return_value=MAX_PDF_HTML_SIZE_BYTES + 1024):
            ok, err = converter._generate_pdf_html_viewer(pdf_file, html_file)
            self.assertFalse(ok)
            self.assertIn("PDF_EXCEEDS_HTML_SIZE_LIMIT", err)
            self.assertFalse(os.path.exists(html_file))

    def test_scan_failure_clears_discovered_files_and_prevents_stale_restore(self):
        from unittest.mock import patch
        folder_a = os.path.join(self.temp_dir.name, "folder_a")
        folder_b = os.path.join(self.temp_dir.name, "folder_b")
        os.makedirs(folder_a, exist_ok=True)
        os.makedirs(folder_b, exist_ok=True)
        with open(os.path.join(folder_a, "doc_a.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 a")

        # 1. Scan folder_a successfully
        self.tab.set_source_folder_path(folder_a)
        self.assertEqual(len(self.tab.scanned_files), 1)
        self.assertEqual(len(self.tab._discovered_files), 1)

        # 2. Scan folder_b with permission failure (mock os.listdir for non-recursive scan)
        self.tab.src_entry.setText(folder_b)
        with patch("os.listdir", side_effect=PermissionError("Scan denied")) as mock_listdir, \
             patch("src.ui.bypass_tab.QMessageBox.critical") as mock_critical:
            self.tab.scan_source_folder()
            mock_listdir.assert_called_once_with(folder_b)
            mock_critical.assert_called_once()

        # Cache must be completely wiped
        self.assertEqual(len(self.tab.scanned_files), 0)
        self.assertEqual(len(self.tab._discovered_files), 0)
        self.assertEqual(self.tab.file_table.rowCount(), 0)

        # 3. Changing format combos must NOT restore folder_a files
        self.tab.pdf_combo.setCurrentText(".html")
        self.assertEqual(self.tab.file_table.rowCount(), 0)
        self.assertEqual(len(self.tab.scanned_files), 0)

    def test_build_run_config_rejects_files_outside_source_dir(self):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt
        from src.core.task_contracts import TaskValidationError

        folder_a = os.path.join(self.temp_dir.name, "out_folder_a")
        folder_b = os.path.join(self.temp_dir.name, "out_folder_b")
        os.makedirs(folder_a, exist_ok=True)
        os.makedirs(folder_b, exist_ok=True)
        file_a = os.path.join(folder_a, "stale_a.pdf")
        with open(file_a, "wb") as f:
            f.write(b"%PDF-1.4 stale")

        self.tab.src_entry.setText(folder_b)
        self.tab.file_table.setRowCount(1)
        item = QTableWidgetItem("stale_a.pdf")
        item.setData(Qt.ItemDataRole.UserRole, file_a)
        self.tab.file_table.setItem(0, 0, item)
        self.tab.file_table.setItem(0, 2, QTableWidgetItem(".zip"))
        self.tab.scanned_files = [file_a]

        with self.assertRaises(TaskValidationError) as cm:
            self.tab.build_run_config()
        self.assertIn("bypass_source_file_outside", str(cm.exception.message_key))


if __name__ == "__main__":
    unittest.main()
