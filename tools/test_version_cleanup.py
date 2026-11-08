import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.version_cleanup import (
    _Cancelled,
    _digest_cancellable,
    _lock_versions,
    execute_version_cleanup,
    scan_version_cleanup,
)


class VersionCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'report_v20240101.txt').write_text('old')
        (self.root / 'report_v20250101.txt').write_text('new')

    def test_folder_move_only_selected_and_never_overwrites(self):
        candidates = scan_version_cleanup([self.root])
        archive = self.root / 'Old Versions'
        archive.mkdir()
        (archive / 'report_v20240101.txt').write_text('existing')
        result = execute_version_cleanup(candidates, 'folder')
        self.assertEqual(result['fail'], 1)
        self.assertTrue((self.root / 'report_v20240101.txt').exists())
        self.assertEqual((archive / 'report_v20240101.txt').read_text(), 'existing')

    def test_changed_family_blocks_before_any_move(self):
        candidates = scan_version_cleanup([self.root])
        (self.root / 'report_v20250101.txt').write_text('changed')
        result = execute_version_cleanup(candidates, 'folder')
        self.assertEqual(result['fail'], 1)
        self.assertTrue((self.root / 'report_v20240101.txt').exists())

    def test_volume_preflight_blocks_whole_selection(self):
        (self.root / 'other_v20240101.txt').write_text('old')
        (self.root / 'other_v20250101.txt').write_text('new')
        candidates = scan_version_cleanup([self.root])
        with patch('src.core.version_cleanup._require_internal_physical_volume', side_effect=OSError('blocked')), patch('src.core.version_cleanup.recycle_file') as recycle:
            result = execute_version_cleanup(candidates)
        self.assertEqual(result['fail'], 2)
        recycle.assert_not_called()

    def test_conflict_blocks_preview(self):
        (self.root / 'report-v20250101.txt').write_text('different')
        with self.assertRaises(OSError):
            scan_version_cleanup([self.root])

    def test_cancel_does_not_move(self):
        candidates = scan_version_cleanup([self.root])
        result = execute_version_cleanup(candidates, 'folder', cancel_callback=lambda: True)
        self.assertEqual(result['cancelled'], 1)
        self.assertTrue((self.root / 'report_v20240101.txt').exists())

    def test_cancellation_during_chunked_hash(self):
        path = self.root / 'large.bin'
        path.write_bytes(b'x' * (3 * 1024 * 1024))
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            return calls == 3
        with self.assertRaises(_Cancelled):
            _digest_cancellable(path, cancel)
        self.assertEqual(path.stat().st_size, 3 * 1024 * 1024)

    def test_cancellation_during_preflight_hash_reports_cancelled(self):
        (self.root / 'report_v20240101.txt').write_bytes(b'x' * (3 * 1024 * 1024))
        candidates = scan_version_cleanup([self.root])
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            return calls == 5
        result = execute_version_cleanup(candidates, 'folder', cancel_callback=cancel)
        self.assertEqual((result['cancelled'], result['fail']), (1, 0))
        self.assertTrue(Path(candidates[0]['path']).exists())

    def test_hash_rejects_opened_file_identity_mismatch(self):
        path = self.root / 'report_v20240101.txt'
        actual_fstat = os.fstat
        def mismatched(fd):
            info = actual_fstat(fd)
            values = list(info)
            values[1] += 1
            return os.stat_result(values)
        with (patch('src.core.version_cleanup.os.fstat', side_effect=mismatched),
              self.assertRaisesRegex(OSError, 'replaced before reading')):
            _digest_cancellable(path, None)

    def test_callback_failure_preserves_prior_success(self):
        (self.root / 'other_v20240101.txt').write_text('old')
        (self.root / 'other_v20250101.txt').write_text('new')
        for callback_type in ('progress', 'cancel'):
            with self.subTest(callback_type=callback_type), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for name in ('a_v20240101.txt', 'a_v20250101.txt',
                             'b_v20240101.txt', 'b_v20250101.txt'):
                    (root / name).write_text(name)
                candidates = scan_version_cleanup([root])
                def progress(index, total, path):
                    if index == 1:
                        raise RuntimeError('progress failed')
                def cancel(root=root):
                    if (root / 'Old Versions' / 'a_v20240101.txt').exists():
                        raise RuntimeError('cancel failed')
                    return False
                kwargs = {'progress_callback': progress} if callback_type == 'progress' else {'cancel_callback': cancel}
                result = execute_version_cleanup(candidates, 'folder', **kwargs)
                self.assertEqual((result['success'], result['fail'], result['not_processed']), (1, 1, 0))
                self.assertEqual(result['error_details'][0]['path'], candidates[1]['path'])
                self.assertFalse(result['error_details'][0]['uncertain'])
                self.assertTrue(Path(candidates[1]['path']).exists())

    def test_recursive_scan_excludes_archive_names_case_insensitively(self):
        for folder in ('tO bE dElEtEd', 'mY aRcHiVe'):
            directory = self.root / folder
            directory.mkdir()
            (directory / 'report_v20230101.txt').write_text('old')
            (directory / 'report_v20240101.txt').write_text('new')
        candidates = scan_version_cleanup([self.root], True, archive_folder_name='My Archive')
        self.assertEqual([c['filename'] for c in candidates], ['report_v20240101.txt'])

    def test_uncertain_failure_stops_remaining_items(self):
        (self.root / 'other_v20240101.txt').write_text('old')
        (self.root / 'other_v20250101.txt').write_text('new')
        candidates = scan_version_cleanup([self.root])
        with patch('src.core.version_cleanup._require_internal_physical_volume'), patch('src.core.version_cleanup.recycle_file', side_effect=OSError('uncertain')) as recycle:
            result = execute_version_cleanup(candidates)
        self.assertEqual((result['fail'], result['not_processed']), (1, 1))
        self.assertTrue(result['error_details'][0]['uncertain'])
        recycle.assert_called_once()

    def test_later_archive_collision_blocks_all_moves(self):
        (self.root / 'other_v20240101.txt').write_text('old')
        (self.root / 'other_v20250101.txt').write_text('new')
        candidates = scan_version_cleanup([self.root])
        archive = self.root / 'Old Versions'
        archive.mkdir()
        (archive / candidates[-1]['filename']).write_text('existing')
        result = execute_version_cleanup(candidates, 'folder')
        self.assertEqual(result['success'], 0)
        self.assertEqual(result['fail'], 2)
        self.assertTrue(all(Path(c['path']).exists() for c in candidates))

    def test_later_archive_path_as_file_blocks_all_moves(self):
        sub = self.root / 'child'
        sub.mkdir()
        for name in ('other_v20240101.txt', 'other_v20250101.txt'):
            (sub / name).write_text(name)
        candidates = scan_version_cleanup([self.root], True)
        (sub / 'Old Versions').write_text('not a folder')
        result = execute_version_cleanup(candidates, 'folder')
        self.assertEqual(result['success'], 0)
        self.assertEqual(result['fail'], 2)
        self.assertTrue(all(Path(c['path']).exists() for c in candidates))

    def test_callback_change_is_detected_before_move(self):
        candidates = scan_version_cleanup([self.root])
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                (self.root / 'report_v20250101.txt').write_text('changed')
            return False
        result = execute_version_cleanup(candidates, 'folder', cancel_callback=cancel)
        self.assertEqual(result['success'], 0)
        self.assertTrue(Path(candidates[0]['path']).exists())

    def test_numeric_versions_compare_integer_components(self):
        for name in ('data_v1.2.txt', 'data_v1.10.txt', 'data_v0.1.txt'):
            (self.root / name).write_text(name)
        candidates = scan_version_cleanup([self.root])
        names = {c['filename'] for c in candidates}
        self.assertIn('data_v1.2.txt', names)
        self.assertIn('data_v0.1.txt', names)
        self.assertNotIn('data_v1.10.txt', names)

    def test_extensionless_dotted_versions_not_misidentified(self):
        for name in ('item_v1.1.3', 'item_v1.2.3', 'item_v1.1.7z', 'item_v1.2.7z'):
            (self.root / name).write_text(name)
        names = {c['filename'] for c in scan_version_cleanup([self.root])}
        self.assertNotIn('item_v1.1.3', names)
        self.assertNotIn('item_v1.2.3', names)
        self.assertIn('item_v1.1.7z', names)

    def test_extensions_and_folders_are_independent(self):
        for name in ('item_v1.1.txt', 'item_v1.2.txt', 'item_v1.3.csv'):
            (self.root / name).write_text(name)
        sub = self.root / 'child'
        sub.mkdir()
        for name in ('item_v0.1.txt', 'item_v0.2.txt'):
            (sub / name).write_text(name)
        names = {c['filename'] for c in scan_version_cleanup([self.root], True)}
        self.assertIn('item_v1.1.txt', names)
        self.assertIn(os.path.join('child', 'item_v0.1.txt'), names)
        self.assertNotIn('item_v1.3.csv', names)

    def test_mixed_invalid_and_equivalent_versions_block(self):
        for names in (('item_v1.2.txt', 'item_v20260103.txt'),
                      ('item_v20260230.txt', 'item_v20260103.txt'),
                      ('item_v1.2.txt', 'item_v1.2.0.txt')):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as directory:
                for name in names:
                    (Path(directory) / name).write_text(name)
                with self.assertRaises(OSError):
                    scan_version_cleanup([directory])

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics required')
    def test_real_folder_move_with_locks(self):
        candidates = scan_version_cleanup([self.root])
        result = execute_version_cleanup(candidates, 'folder')
        self.assertEqual(result['success'], 1, result['errors'])
        self.assertTrue((self.root / 'Old Versions' / 'report_v20240101.txt').exists())
        self.assertTrue((self.root / 'report_v20250101.txt').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics required')
    def test_locks_block_latest_write_and_delete_and_old_write(self):
        latest = self.root / 'report_v20250101.txt'
        old = self.root / 'report_v20240101.txt'
        with _lock_versions(str(latest), str(old)):
            with self.assertRaises(OSError):
                latest.write_text('changed')
            with self.assertRaises(OSError):
                latest.unlink()
            with self.assertRaises(OSError):
                old.write_text('changed')

    def test_lock_failure_stops_without_retry(self):
        candidates = scan_version_cleanup([self.root])
        with patch('src.core.version_cleanup._lock_versions', side_effect=OSError('sharing violation')) as lock:
            result = execute_version_cleanup(candidates, 'folder')
        self.assertEqual(result['fail'], 1)
        self.assertEqual(lock.call_count, 1)
        self.assertTrue(Path(candidates[0]['path']).exists())


if __name__ == '__main__':
    unittest.main()
