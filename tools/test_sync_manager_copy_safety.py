import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.core.sync_manager import SyncManager, _file_digest, _move_without_replacement


class SyncCopySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.target = Path(self.temp.name) / "target"
        self.source.mkdir()
        self.target.mkdir()
        (self.source / "report.txt").write_text("source", encoding="utf-8")

    def manager(self, **kwargs):
        return SyncManager([str(self.source), str(self.target)], sync_mode="one_way", **kwargs)

    def test_reparse_attribute_below_root_is_rejected(self):
        manager = self.manager()
        component = self.target / 'nested'
        real_lstat = os.lstat
        def fake_lstat(path):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(component)):
                return SimpleNamespace(st_mode=0o40777, st_file_attributes=0x400)
            return real_lstat(path)
        with patch('src.core.sync_manager.os.lstat', side_effect=fake_lstat):
            self.assertFalse(manager.is_safe_path(str(self.target), str(component / 'file.txt')))
            self.assertTrue(manager.is_safe_path(str(component), str(component / 'file.txt')))

    @unittest.skipUnless(os.name == 'nt', 'Windows junction test')
    def test_archive_junction_is_blocked_before_external_directory_creation(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        junction = self.target / 'to be deleted'
        created = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
                                 capture_output=True, text=True, check=False)
        self.assertEqual(created.returncode, 0, created.stderr)
        try:
            nested = self.target / 'nested'
            nested.mkdir()
            old = nested / 'report.txt'
            old.write_text('old', encoding='utf-8')
            os.utime(old, (1_600_000_000, 1_600_000_000))
            (self.source / 'nested').mkdir()
            (self.source / 'nested' / 'report.txt').write_text('new', encoding='utf-8')
            manager = self.manager(include_subfolders=True)
            result = manager.execute_sync(manager.analyze_sync())
            self.assertGreater(result.fail, 0)
            self.assertEqual(old.read_text(encoding='utf-8'), 'old')
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            os.rmdir(junction)

    def test_replacement_copy_failure_preserves_old_at_original_location(self):
        old = self.target / 'report.txt'
        old.write_text('old', encoding='utf-8')
        os.utime(old, (1_600_000_000, 1_600_000_000))
        manager = self.manager()
        with patch('src.core.sync_manager.shutil.copyfileobj', side_effect=OSError('copy failed')):
            result = manager.execute_sync(manager.analyze_sync())
        self.assertGreater(result.fail, 0)
        self.assertEqual(old.read_text(encoding='utf-8'), 'old')
        self.assertFalse((self.target / 'to be deleted').exists())

    def test_one_way_equal_metadata_different_content_updates_source_authoritatively(self):
        target = self.target / 'report.txt'
        target.write_text('other!', encoding='utf-8')
        stamp = 1_700_000_000
        os.utime(self.source / 'report.txt', (stamp, stamp))
        os.utime(target, (stamp, stamp))
        manager = self.manager()
        result = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(result.fail, 0, result.errors)
        self.assertEqual(target.read_text(encoding='utf-8'), 'source')
        self.assertEqual((self.target / 'to be deleted' / 'report.txt').read_text(encoding='utf-8'), 'other!')

    def test_two_way_tied_latest_conflict_holds_entire_family(self):
        for name in ('doc.txt', 'doc_v2.0.txt'):
            for third_exists in (False, True):
                for reverse in (False, True):
                    with self.subTest(name=name, third_exists=third_exists, reverse=reverse), tempfile.TemporaryDirectory() as temp:
                        folders = [Path(temp) / c for c in ('a', 'b', 'c')]
                        for folder in folders:
                            folder.mkdir()
                        for folder, content in zip(folders[:2], ('first', 'other')):
                            path = folder / name
                            path.write_text(content, encoding='utf-8')
                            os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
                        if third_exists:
                            path = folders[2] / name
                            path.write_text('older', encoding='utf-8')
                            os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
                        order = list(reversed(folders)) if reverse else folders
                        manager = SyncManager([str(folder) for folder in order], sync_mode='two_way')
                        actions = manager.analyze_sync()
                        self.assertEqual([a['action'] for a in actions], ['보류'])
                        result = manager.execute_sync(actions)
                        self.assertEqual((result.fail, result.held_count), (0, 1))
                        self.assertEqual((folders[0] / name).read_text(encoding='utf-8'), 'first')
                        self.assertEqual((folders[1] / name).read_text(encoding='utf-8'), 'other')
                        self.assertEqual((folders[2] / name).exists(), third_exists)
                        if third_exists:
                            self.assertEqual((folders[2] / name).read_text(encoding='utf-8'), 'older')

    def test_version_newest_selection_uses_nanoseconds(self):
        name = 'doc_v2.0.txt'
        first, second = self.source / name, self.target / name
        first.write_text('first', encoding='utf-8')
        second.write_text('other', encoding='utf-8')
        stamp = 1_700_000_000_000_000_000
        os.utime(first, ns=(stamp, stamp))
        os.utime(second, ns=(stamp + 100, stamp + 100))
        if first.stat().st_mtime_ns == second.stat().st_mtime_ns:
            self.skipTest('Filesystem did not preserve 100 ns difference')
        manager = SyncManager([str(self.source), str(self.target)], sync_mode='two_way')
        actions = [a for a in manager.analyze_sync() if a['filename'] == name]
        self.assertTrue(any(a['action'] == '복사' and a['source_folder'] == str(self.target) for a in actions))
        self.assertFalse(any(a['action'] == '보류' for a in actions))

    def test_two_way_equivalent_different_names_hold_entire_family(self):
        for older in (False, True):
            for reverse in (False, True):
                with self.subTest(older=older, reverse=reverse), tempfile.TemporaryDirectory() as temp:
                    folders = [Path(temp) / c for c in ('a', 'b', 'c')]
                    for folder in folders:
                        folder.mkdir()
                    first = folders[0] / 'doc_v1.0.txt'
                    second = folders[1] / 'doc_v1.0.0.txt'
                    first.write_text('first', encoding='utf-8')
                    second.write_text('other', encoding='utf-8')
                    old = folders[2] / 'doc_v0.9.txt'
                    if older:
                        old.write_text('older', encoding='utf-8')
                    order = list(reversed(folders)) if reverse else folders
                    manager = SyncManager([str(folder) for folder in order], sync_mode='two_way')
                    actions = manager.analyze_sync()
                    self.assertEqual([a['action'] for a in actions], ['보류'])
                    self.assertEqual(actions[0]['reason'], 'Target has an equivalent version with a different filename')
                    result = manager.execute_sync(actions)
                    self.assertEqual((result.fail, result.held_count), (0, 1))
                    self.assertEqual(first.read_text(encoding='utf-8'), 'first')
                    self.assertEqual(second.read_text(encoding='utf-8'), 'other')
                    self.assertEqual(old.exists(), older)
                    self.assertEqual(sorted(p.name for p in folders[2].iterdir()), ['doc_v0.9.txt'] if older else [])

    def test_three_latest_ties_with_one_different_are_held(self):
        for name in ('doc.txt', 'doc_v1.0.txt'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                folders = [Path(temp) / c for c in ('a', 'b', 'c')]
                for folder, content in zip(folders, ('same', 'same', 'diff')):
                    folder.mkdir()
                    path = folder / name
                    path.write_text(content, encoding='utf-8')
                    os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
                manager = SyncManager([str(folder) for folder in folders], sync_mode='two_way')
                actions = manager.analyze_sync()
                self.assertEqual([a['action'] for a in actions], ['보류'])
                result = manager.execute_sync(actions)
                self.assertEqual((result.fail, result.held_count), (0, 1))
                self.assertEqual([(folder / name).read_text(encoding='utf-8') for folder in folders], ['same', 'same', 'diff'])

    def test_changed_target_during_staging_is_not_archived(self):
        target = self.target / 'report.txt'
        target.write_text('old', encoding='utf-8')
        os.utime(target, (1_600_000_000, 1_600_000_000))
        manager = self.manager()
        actions = manager.analyze_sync()
        real_copy = shutil.copyfileobj
        def change_target(source, out):
            real_copy(source, out)
            target.write_text('changed after analysis', encoding='utf-8')
        with patch('src.core.sync_manager.shutil.copyfileobj', side_effect=change_target):
            result = manager.execute_sync(actions)
        self.assertGreater(result.fail, 0)
        self.assertEqual(target.read_text(encoding='utf-8'), 'changed after analysis')
        self.assertFalse((self.target / 'to be deleted').exists())

    def test_change_during_archive_path_selection_with_restored_mtime_is_blocked(self):
        for approved in (False, True):
            with self.subTest(approved=approved):
                target = self.target / 'report.txt'
                target.write_text('old', encoding='utf-8')
                os.utime(target, (1_600_000_000, 1_600_000_000))
                manager = self.manager()
                actions = manager.analyze_sync()
                if approved:
                    info = target.stat()
                    manager.approved_actions = [
                        {'action': 'archive', 'source': os.path.normcase(os.path.abspath(target)),
                         'source_snapshot': (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_mode)},
                        {'action': 'copy', 'source': os.path.normcase(os.path.abspath(self.source / 'report.txt')),
                         'target': os.path.normcase(os.path.abspath(target))},
                    ]
                real_unique = manager.get_unique_deleted_path
                def mutate(folder, filename, selected_target=target, unique_path=real_unique):
                    archive = unique_path(folder, filename)
                    stamp = selected_target.stat().st_mtime_ns
                    selected_target.write_text('new', encoding='utf-8')
                    os.utime(selected_target, ns=(stamp, stamp))
                    return archive
                with patch.object(manager, 'get_unique_deleted_path', side_effect=mutate):
                    result = manager.execute_sync(actions)
                self.assertGreater(result.fail, 0)
                self.assertEqual(target.read_text(encoding='utf-8'), 'new')
                self.assertFalse((self.target / 'to be deleted' / 'report.txt').exists())
                target.unlink()

    @unittest.skipUnless(os.name == 'nt', 'Windows case-insensitive paths')
    def test_plain_name_case_difference_is_held(self):
        target = self.target / 'REPORT.txt'
        target.write_text('target', encoding='utf-8')
        manager = self.manager()
        actions = manager.analyze_sync()
        self.assertEqual([a['action'] for a in actions], ['보류'])
        result = manager.execute_sync(actions)
        self.assertEqual(result.held_count, 1)
        self.assertIn(str(target), result.held[0])
        self.assertEqual(target.read_text(encoding='utf-8'), 'target')

    def test_target_changed_after_analysis_is_not_archived_or_replaced(self):
        old = self.target / 'report.txt'
        old.write_text('old', encoding='utf-8')
        os.utime(old, (1_600_000_000, 1_600_000_000))
        manager = self.manager()
        actions = manager.analyze_sync()
        old.write_text('new user edits', encoding='utf-8')
        result = manager.execute_sync(actions)
        self.assertGreater(result.fail, 0)
        self.assertIn('File changed since analysis', result.errors[0])
        self.assertEqual(old.read_text(encoding='utf-8'), 'new user edits')
        self.assertFalse((self.target / 'to be deleted').exists())

    def test_source_changed_after_analysis_does_not_displace_target(self):
        source = self.source / 'report.txt'
        old = self.target / 'report.txt'
        old.write_text('old', encoding='utf-8')
        os.utime(old, (1_600_000_000, 1_600_000_000))
        manager = self.manager()
        actions = manager.analyze_sync()
        source.write_text('changed after analysis', encoding='utf-8')
        result = manager.execute_sync(actions)
        self.assertGreater(result.fail, 0)
        self.assertIn('File changed since analysis', result.errors[0])
        self.assertEqual(old.read_text(encoding='utf-8'), 'old')
        self.assertFalse((self.target / 'to be deleted').exists())

    def test_target_changed_during_staging_is_not_archived_or_replaced(self):
        old = self.target / 'report.txt'
        old.write_text('old', encoding='utf-8')
        os.utime(old, (1_600_000_000, 1_600_000_000))
        manager = self.manager()
        actions = manager.analyze_sync()
        original_copy = shutil.copyfileobj
        def edit_target(source, target):
            original_copy(source, target)
            old.write_text('edit while staging', encoding='utf-8')
        with patch('src.core.sync_manager.shutil.copyfileobj', side_effect=edit_target):
            result = manager.execute_sync(actions)
        self.assertGreater(result.fail, 0)
        self.assertIn('File changed since analysis', result.errors[0])
        self.assertEqual(old.read_text(encoding='utf-8'), 'edit while staging')
        self.assertFalse((self.target / 'to be deleted').exists())

    def test_publication_failure_restores_multiple_old_versions(self):
        (self.source / 'doc_v3.0.txt').write_text('new', encoding='utf-8')
        for version in ('1.0', '2.0'):
            (self.target / f'doc_v{version}.txt').write_text(version, encoding='utf-8')
        manager = self.manager()
        real_move = _move_without_replacement
        def fail_publication(source, target):
            if Path(source).name.startswith('.fileops-sync-'):
                raise OSError('publication failed')
            return real_move(source, target)
        with patch('src.core.sync_manager._move_without_replacement', side_effect=fail_publication):
            result = manager.execute_sync(manager.analyze_sync())
        self.assertGreater(result.fail, 0)
        for version in ('1.0', '2.0'):
            self.assertEqual((self.target / f'doc_v{version}.txt').read_text(encoding='utf-8'), version)

    def test_restore_collision_reports_recovery_location(self):
        old = self.target / 'report.txt'
        old.write_text('old', encoding='utf-8')
        os.utime(old, (1_600_000_000, 1_600_000_000))
        manager = self.manager()
        real_move = _move_without_replacement
        def race(source, target):
            if Path(source).name.startswith('.fileops-sync-'):
                old.write_text('arrival', encoding='utf-8')
                raise OSError('publication failed')
            return real_move(source, target)
        with patch('src.core.sync_manager._move_without_replacement', side_effect=race):
            result = manager.execute_sync(manager.analyze_sync())
        archive = self.target / 'to be deleted' / 'report.txt'
        self.assertEqual(old.read_text(encoding='utf-8'), 'arrival')
        self.assertEqual(archive.read_text(encoding='utf-8'), 'old')
        self.assertIn(str(archive), result.errors[0])

    def test_one_way_newer_target_is_held(self):
        source = self.source / 'doc_v1.0.txt'
        target = self.target / 'doc_v2.0.txt'
        source.write_text('source', encoding='utf-8')
        target.write_text('newer', encoding='utf-8')
        manager = self.manager()
        actions = manager.analyze_sync()
        held = [a for a in actions if a['action'] == '보류']
        self.assertEqual(len(held), 1)
        result = manager.execute_sync(actions)
        self.assertEqual(result.held_count, 1)
        self.assertIn(str(target), result.held[0])
        self.assertEqual(target.read_text(encoding='utf-8'), 'newer')
        self.assertEqual(source.read_text(encoding='utf-8'), 'source')

    def test_newer_target_is_held_when_version_family_case_differs(self):
        source = self.source / 'Report_v1.0.txt'
        target = self.target / 'report_v2.0.txt'
        source.write_text('source', encoding='utf-8')
        target.write_text('newer', encoding='utf-8')
        manager = self.manager()
        actions = manager.analyze_sync()
        held = [action for action in actions if action['action'] == '보류']
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]['filename'], target.name)
        self.assertFalse(any(action['action'] in ('복사', 'to_be_deleted이동')
                             and action['filename'].casefold().startswith('report_v')
                             for action in actions))
        self.assertEqual(manager.execute_sync(actions).held_count, 1)
        self.assertEqual(target.read_text(encoding='utf-8'), 'newer')

    def test_case_variant_version_family_copy_failure_preserves_old(self):
        source = self.source / 'Report_v3.0.txt'
        target = self.target / 'report_v1.0.txt'
        source.write_text('source', encoding='utf-8')
        target.write_text('old', encoding='utf-8')
        manager = self.manager()
        with patch('src.core.sync_manager.shutil.copyfileobj', side_effect=OSError('copy failed')):
            result = manager.execute_sync(manager.analyze_sync())
        self.assertGreater(result.fail, 0)
        self.assertEqual(target.read_text(encoding='utf-8'), 'old')

    def test_equivalent_versions_with_different_names_are_held_in_both_directions(self):
        for source_version, target_version in (('1.0', '1.0.0'), ('1.0.0', '1.0')):
            with self.subTest(source=source_version, target=target_version):
                source = self.source / f'doc_v{source_version}.txt'
                target = self.target / f'doc_v{target_version}.txt'
                source.write_text('source', encoding='utf-8')
                target.write_text('target', encoding='utf-8')
                manager = self.manager()
                actions = manager.analyze_sync()
                held = [a for a in actions if a['action'] == '보류']
                self.assertEqual(len(held), 1)
                self.assertEqual(held[0]['reason'], 'Target has an equivalent version with a different filename')
                self.assertEqual(held[0]['filename'], target.name)
                result = manager.execute_sync(actions)
                self.assertEqual(result.held_count, 1)
                self.assertEqual(source.read_text(encoding='utf-8'), 'source')
                self.assertEqual(target.read_text(encoding='utf-8'), 'target')
                source.unlink()
                target.unlink()

    def test_version_components_compare_numerically(self):
        source = self.source / 'doc_v1.2.txt'
        target = self.target / 'doc_v1.10.txt'
        source.write_text('source', encoding='utf-8')
        target.write_text('target', encoding='utf-8')
        manager = self.manager()
        held = [a for a in manager.analyze_sync() if a['action'] == '보류']
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]['reason'], 'Target has a newer version')
        self.assertEqual(held[0]['filename'], target.name)

    def test_one_way_same_version_content_uses_first_folder_even_when_target_newer(self):
        source = self.source / 'plan_v1.0.xlsx'
        target = self.target / 'plan_v1.0.xlsx'
        source.write_bytes(b'first folder')
        target.write_bytes(b'newer target')
        os.utime(source, (1_600_000_000, 1_600_000_000))
        os.utime(target, (1_700_000_000, 1_700_000_000))
        manager = self.manager()
        result = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(result.fail, 0, result.errors)
        self.assertEqual(target.read_bytes(), b'first folder')
        self.assertEqual((self.target / 'to be deleted' / target.name).read_bytes(), b'newer target')

    def test_two_way_same_version_content_uses_more_recent_modification(self):
        for newer_folder in ('source', 'target'):
            with self.subTest(newer=newer_folder), tempfile.TemporaryDirectory() as root:
                first, second = Path(root) / 'first', Path(root) / 'second'
                first.mkdir()
                second.mkdir()
                a, b = first / 'plan_v1.0.xlsx', second / 'plan_v1.0.xlsx'
                a.write_bytes(b'first')
                b.write_bytes(b'second')
                newer, older = (a, b) if newer_folder == 'source' else (b, a)
                os.utime(newer, (1_700_000_000, 1_700_000_000))
                os.utime(older, (1_600_000_000, 1_600_000_000))
                expected = newer.read_bytes()
                previous = older.read_bytes()
                manager = SyncManager([str(first), str(second)], sync_mode='two_way')
                result = manager.execute_sync(manager.analyze_sync())
                self.assertEqual(result.fail, 0, result.errors)
                self.assertEqual(a.read_bytes(), expected)
                self.assertEqual(b.read_bytes(), expected)
                self.assertEqual((older.parent / 'to be deleted' / older.name).read_bytes(), previous)

    def test_same_version_equal_timestamps_different_content_is_held(self):
        source = self.source / 'plan_v1.0.xlsx'
        target = self.target / 'plan_v1.0.xlsx'
        source.write_bytes(b'first')
        target.write_bytes(b'other')
        os.utime(source, (1_700_000_000, 1_700_000_000))
        os.utime(target, (1_700_000_000, 1_700_000_000))
        manager = SyncManager([str(self.source), str(self.target)], sync_mode='two_way')
        actions = manager.analyze_sync()
        held = [action for action in actions if action['action'] == '보류']
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]['reason'], 'Same version files differ with equal modification times')
        self.assertEqual(manager.execute_sync(actions).held_count, 1)
        self.assertEqual(source.read_bytes(), b'first')
        self.assertEqual(target.read_bytes(), b'other')

    def test_same_version_identical_contents_do_not_repeat(self):
        source = self.source / 'plan_v1.0.xlsx'
        target = self.target / 'plan_v1.0.xlsx'
        source.write_bytes(b'identical')
        target.write_bytes(b'identical')
        os.utime(source, (1_700_000_000, 1_700_000_000))
        os.utime(target, (1_600_000_000, 1_600_000_000))
        for mode in ('one_way', 'two_way'):
            with self.subTest(mode=mode):
                manager = SyncManager([str(self.source), str(self.target)], sync_mode=mode)
                version_actions = [a for a in manager.analyze_sync() if a['filename'].endswith('.xlsx')]
                self.assertEqual(version_actions, [])

    def test_same_version_content_comparison_error_prevents_sync(self):
        source = self.source / 'plan_v1.0.xlsx'
        target = self.target / 'plan_v1.0.xlsx'
        source.write_bytes(b'first')
        target.write_bytes(b'other')
        manager = self.manager()
        with patch('src.core.sync_manager._same_stable_content', side_effect=OSError('cannot read')):
            actions = manager.analyze_sync()
        self.assertTrue(manager.scan_errors)
        self.assertGreater(manager.execute_sync(actions).fail, 0)
        self.assertEqual(target.read_bytes(), b'other')

    def test_legacy_delete_setting_and_mutated_flag_still_preserve_old_version(self):
        for scheduled in (False, True):
            with self.subTest(scheduled=scheduled):
                old = self.target / "report.txt"
                old.write_text("old", encoding="utf-8")
                stamp = time.time() - 120
                os.utime(old, (stamp, stamp))
                manager = self.manager(move_to_deleted=False, is_scheduled=scheduled)
                manager.move_to_deleted = False  # even a mutated legacy manager cannot delete
                actions = manager.analyze_sync()
                with patch("src.core.sync_manager.os.remove", side_effect=AssertionError("permanent delete")):
                    result = manager.execute_sync(actions)
                self.assertEqual(result.fail, 0, result.errors)
                self.assertEqual(old.read_text(encoding="utf-8"), "source")
                archived = list((self.target / "to be deleted").rglob("report*.txt"))
                self.assertTrue(any(path.read_text(encoding="utf-8") == "old" for path in archived))
                old.unlink()

    def test_unsupported_and_legacy_delete_actions_fail_without_changing_files(self):
        for action_type in ("삭제", "delete", "unknown"):
            with self.subTest(action=action_type):
                manager = self.manager(move_to_deleted=False)
                action = {"action": action_type, "filename": "report.txt",
                          "source_folder": str(self.source), "target_folder": str(self.target)}
                with patch("src.core.sync_manager.os.remove", side_effect=AssertionError("permanent delete")):
                    result = manager.execute_sync([action])
                self.assertEqual((result.success, result.fail), (0, 1))
                self.assertIn("Unsupported synchronization action", result.errors[0])
                self.assertEqual((self.source / "report.txt").read_text(encoding="utf-8"), "source")
                self.assertEqual(list(self.target.iterdir()), [])

    def test_created_after_analysis_is_not_overwritten_manual_or_scheduled(self):
        for scheduled in (False, True):
            with self.subTest(scheduled=scheduled):
                manager = self.manager(is_scheduled=scheduled)
                actions = manager.analyze_sync()
                target = self.target / "report.txt"
                target.write_text("new arrival", encoding="utf-8")
                result = manager.execute_sync(actions)
                self.assertEqual((result.success, result.fail), (0, 1))
                self.assertEqual(target.read_text(encoding="utf-8"), "new arrival")
                target.unlink()

    def test_file_created_at_publication_is_not_overwritten(self):
        manager = self.manager()
        actions = manager.analyze_sync()
        target = self.target / "report.txt"
        def racing_publish(source, destination):
            target.write_text("racing arrival", encoding="utf-8")
            return _move_without_replacement(source, destination)

        with patch("src.core.sync_manager._move_without_replacement", side_effect=racing_publish):
            result = manager.execute_sync(actions)
        self.assertEqual(result.fail, 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "racing arrival")
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["report.txt"])

    def test_copy_failure_does_not_publish_partial_file(self):
        manager = self.manager()
        actions = manager.analyze_sync()

        def partial_copy(source, target):
            target.write(b"partial")
            raise OSError("copy failed")

        with patch("src.core.sync_manager.shutil.copyfileobj", side_effect=partial_copy):
            result = manager.execute_sync(actions)
        self.assertEqual(result.fail, 1)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_interrupted_temporary_file_is_not_scanned(self):
        for name in (".fileops-sync-report_v20260101.tmp", ".fileops-date-report_v20260101.tmp"):
            (self.source / name).write_text("partial", encoding="utf-8")
        manager = self.manager(exclude_patterns=[])
        actions = manager.analyze_sync()
        self.assertEqual([action["filename"] for action in actions], ["report.txt"])
        date_manager = SyncManager([str(self.source), str(self.target)], date_latest_only=True, exclude_patterns=[])
        self.assertEqual(date_manager.analyze_sync(), [])

    def test_cleanup_error_does_not_hide_copy_error(self):
        manager = self.manager()
        actions = manager.analyze_sync()
        real_unlink = os.unlink
        with patch("src.core.sync_manager.shutil.copyfileobj", side_effect=OSError("original copy failure")), \
             patch("src.core.sync_manager.os.chmod", side_effect=OSError("cleanup failure")), \
             patch("src.core.sync_manager.os.unlink", wraps=real_unlink) as unlink:
            result = manager.execute_sync(actions)
        self.assertEqual(result.fail, 1)
        self.assertIn("original copy failure", result.errors[0])
        unlink.assert_called_once()
        self.assertFalse((self.target / "report.txt").exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_same_size_source_change_during_copy_is_not_published(self):
        manager = self.manager()
        actions = manager.analyze_sync()
        original_copy = shutil.copyfileobj

        def change_source(source, target):
            original_copy(source, target)
            (self.source / "report.txt").write_text("alter!", encoding="utf-8")

        with patch("src.core.sync_manager.shutil.copyfileobj", side_effect=change_source):
            result = manager.execute_sync(actions)
        self.assertEqual((result.success, result.fail), (0, 1))
        self.assertIn("Source changed during copy", result.errors[0])
        self.assertEqual(list(self.target.iterdir()), [])

    def test_copy_metadata_uses_open_source_handle(self):
        manager = self.manager()
        actions = manager.analyze_sync()
        real_copystat = shutil.copystat
        with patch("src.core.sync_manager.shutil.copystat", wraps=real_copystat) as copystat:
            result = manager.execute_sync(actions)
        self.assertEqual(result.fail, 0)
        self.assertIsInstance(copystat.call_args.args[0], int)

    def test_source_change_during_metadata_copy_blocks_publication(self):
        manager = self.manager()
        actions = manager.analyze_sync()
        real_copystat = shutil.copystat

        def change_during_metadata(source, target):
            real_copystat(source, target)
            (self.source / "report.txt").write_text("alter!", encoding="utf-8")

        with patch("src.core.sync_manager.shutil.copystat", side_effect=change_during_metadata):
            result = manager.execute_sync(actions)
        self.assertEqual(result.fail, 1)
        self.assertIn("Source changed during copy", result.errors[0])
        self.assertFalse((self.target / "report.txt").exists())

    def test_metadata_copy_change_is_detected_with_unchanged_fingerprint(self):
        manager = self.manager()
        actions = manager.analyze_sync()
        real_copystat = shutil.copystat
        def change_during_metadata(source, target):
            real_copystat(source, target)
            (self.source / 'report.txt').write_text('alter!', encoding='utf-8')
        with patch('src.core.sync_manager._file_fingerprint', return_value=(1, 2, 6, 3, 4)), \
             patch('src.core.sync_manager.shutil.copystat', side_effect=change_during_metadata):
            result = manager.execute_sync(actions)
        self.assertEqual(result.fail, 1)
        self.assertIn('Source changed during copy', result.errors[0])
        self.assertFalse((self.target / 'report.txt').exists())

    def test_cancellation_during_copy_verification_blocks_publication(self):
        manager = self.manager()
        actions = manager.analyze_sync()

        def cancel_digest(stream, cancelled=None):
            manager.cancel()
            return _file_digest(stream, cancelled)

        with patch("src.core.sync_manager._file_digest", side_effect=cancel_digest):
            result = manager.execute_sync(actions)
        self.assertEqual(result.fail, 1)
        self.assertIn("cancelled", result.errors[0])
        self.assertFalse((self.target / "report.txt").exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_archive_then_copy_and_approval(self):
        target = self.target / "report.txt"
        target.write_text("old", encoding="utf-8")
        os.utime(target, (1_600_000_000, 1_600_000_000))
        manager = self.manager()
        actions = manager.analyze_sync()
        manager.approved_actions = [
            {"action": "archive", "source": os.path.normcase(os.path.abspath(target))},
            {"action": "copy", "source": os.path.normcase(os.path.abspath(self.source / "report.txt")),
             "target": os.path.normcase(os.path.abspath(target))},
        ]
        result = manager.execute_sync(actions)
        self.assertEqual((result.success, result.fail), (2, 0))
        self.assertEqual(target.read_text(encoding="utf-8"), "source")
        self.assertEqual((self.target / "to be deleted" / "report.txt").read_text(encoding="utf-8"), "old")

    def test_failed_archive_does_not_allow_copy_to_overwrite(self):
        target = self.target / "report.txt"
        target.write_text("old", encoding="utf-8")
        os.utime(target, (1_600_000_000, 1_600_000_000))
        manager = self.manager()
        actions = manager.analyze_sync()
        with patch("src.core.sync_manager._move_without_replacement", side_effect=OSError("move failed")):
            result = manager.execute_sync(actions)
        self.assertEqual((result.success, result.fail), (0, 2))
        self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_archive_and_conflict_backup_do_not_overwrite_racing_file(self):
        for action_type in ("to_be_deleted이동", "충돌 보존 백업"):
            with self.subTest(action=action_type):
                manager = self.manager()
                target = self.target / "report.txt"
                target.write_text("local original", encoding="utf-8")
                action = {"filename": "report.txt", "source_folder": str(self.target),
                          "target_folder": str(self.target), "action": action_type}
                real_unique = manager.get_unique_deleted_path
                occupied = []

                def racing_unique(folder, filename, real_unique=real_unique, occupied=occupied):
                    path = Path(real_unique(folder, filename))
                    path.write_text("existing archive", encoding="utf-8")
                    occupied.append(path)
                    return str(path)

                with patch.object(manager, "get_unique_deleted_path", side_effect=racing_unique):
                    result = manager.execute_sync([action])
                self.assertEqual((result.success, result.fail), (0, 1))
                self.assertEqual(target.read_text(encoding="utf-8"), "local original")
                self.assertEqual(occupied[0].read_text(encoding="utf-8"), "existing archive")

    def test_move_failure_does_not_fall_back_to_copy(self):
        target = self.target / "report.txt"
        target.write_text("local original", encoding="utf-8")
        manager = self.manager()
        action = {"filename": "report.txt", "source_folder": str(self.target),
                  "target_folder": str(self.target), "action": "to_be_deleted이동"}
        move_method = "rename" if os.name == "nt" else "link"
        with patch(f"src.core.sync_manager.os.{move_method}", side_effect=OSError("unsupported")), \
             patch("src.core.sync_manager.shutil.copy2") as copy:
            result = manager.execute_sync([action])
        self.assertEqual((result.success, result.fail), (0, 1))
        self.assertEqual(target.read_text(encoding="utf-8"), "local original")
        copy.assert_not_called()

    def test_two_way_identical_files_do_not_repeat_sync(self):
        manager = SyncManager([str(self.source), str(self.target)])
        self.assertEqual(manager.execute_sync(manager.analyze_sync()).fail, 0)
        self.assertEqual(manager.analyze_sync(), [])
        self.assertEqual(manager.scan_errors, [])
        self.assertFalse((self.target / "to be deleted").exists())

    def test_two_way_same_size_and_time_but_different_bytes_is_held(self):
        source = self.source / "report.txt"
        target = self.target / "report.txt"
        target.write_text("other!", encoding="utf-8")
        timestamp = 1_700_000_000
        os.utime(source, (timestamp, timestamp))
        os.utime(target, (timestamp, timestamp))
        for scheduled in (False, True):
            manager = SyncManager([str(self.source), str(self.target)], is_scheduled=scheduled)
            actions = manager.analyze_sync()
            self.assertEqual([a['action'] for a in actions], ['보류'])
            result = manager.execute_sync(actions)
            self.assertEqual((result.success, result.fail, result.held_count), (0, 0, 1))
            self.assertEqual(source.read_text(encoding="utf-8"), "source")
            self.assertEqual(target.read_text(encoding="utf-8"), "other!")

    def test_two_way_comparison_failure_holds_file(self):
        source = self.source / "report.txt"
        target = self.target / "report.txt"
        target.write_text("source", encoding="utf-8")
        info = source.stat()
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
        manager = SyncManager([str(self.source), str(self.target)])
        with patch("src.core.sync_manager._same_stable_content", side_effect=OSError("comparison failed")):
            self.assertEqual(manager.analyze_sync(), [])
        self.assertEqual(len(manager.scan_errors), 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "source")

    def test_cancellation_during_comparison_is_not_a_successful_noop(self):
        source = self.source / "report.txt"
        target = self.target / "report.txt"
        target.write_text("source", encoding="utf-8")
        info = source.stat()
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
        manager = SyncManager([str(self.source), str(self.target)])

        def cancel_digest(stream, cancelled=None):
            manager.cancel()
            return _file_digest(stream, cancelled)

        with patch("src.core.sync_manager._file_digest", side_effect=cancel_digest):
            self.assertEqual(manager.analyze_sync(), [])
        self.assertTrue(manager.is_cancelled)
        self.assertTrue(manager.scan_errors)


if __name__ == "__main__":
    unittest.main()
