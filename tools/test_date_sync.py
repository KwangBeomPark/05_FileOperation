import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.sync_manager import SyncManager


class DateSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = Path(self.tmp.name) / "a"
        self.b = Path(self.tmp.name) / "b"
        self.a.mkdir()
        self.b.mkdir()

    def manager(self, **kwargs):
        return SyncManager([str(self.a), str(self.b)], date_latest_only=True, **kwargs)

    def test_headless_saved_archive_modes_reach_real_sync(self):
        from src.main import run_headless

        for mode in ("trash", "folder", None):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                first, second = root / "first", root / "second"
                first.mkdir()
                second.mkdir()
                (first / "r_v20260201.txt").write_bytes(b"new")
                old = second / "r_v20260101.txt"
                old.write_bytes(b"old")
                group = {"name": "g", "folders": [str(first), str(second)], "date_latest_only": True}
                if mode is not None:
                    group["date_archive_mode"] = mode
                config_path = root / "config.json"
                config_path.write_text(json.dumps({"sync_groups": [group], "task_enabled_steps": ["sync"]}), encoding="utf-8")
                with (patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local"), "APPDATA": str(root / "roaming")}),
                      patch("src.core.task_runner.SyncManager", wraps=SyncManager) as manager_cls):
                    result = run_headless(str(config_path))
                self.assertTrue(manager_cls.call_args.kwargs["date_latest_only"])
                self.assertEqual(manager_cls.call_args.kwargs["date_archive_mode"], mode or "folder")
                # Headless runs have no approval manifest: folder operations fail closed.
                self.assertEqual(result, 1)
                self.assertEqual(old.read_bytes(), b"old")
                self.assertFalse((second / "r_v20260201.txt").exists())
                self.assertFalse((second / "to be deleted").exists())

    def test_headless_legacy_group_uses_both_defaults(self):
        from src.main import run_headless

        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            config_path = root / "config.json"
            config_path.write_text(json.dumps({
                "sync_groups": [{"name": "legacy", "folders": [str(first), str(second)]}],
                "task_enabled_steps": ["sync"],
            }), encoding="utf-8")
            with (patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local"), "APPDATA": str(root / "roaming")}),
                  patch("src.core.task_runner.SyncManager", wraps=SyncManager) as manager_cls):
                self.assertEqual(run_headless(str(config_path)), 0)
            self.assertFalse(manager_cls.call_args.kwargs["date_latest_only"])
            self.assertEqual(manager_cls.call_args.kwargs["date_archive_mode"], "folder")

    def test_manual_approved_folder_mode_copies_and_archives(self):
        from dataclasses import replace

        from src.core.run_summary import build_run_summary
        from src.core.task_contracts import (
            RunPlan,
            SyncGroupConfig,
            SyncRunConfig,
            TaskStep,
        )
        from src.core.task_runner import TaskRunner
        from src.utils.config_manager import ConfigManager

        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        plan = RunPlan({TaskStep.SYNC: SyncRunConfig([
            SyncGroupConfig("g", [str(self.a), str(self.b)], date_latest_only=True, date_archive_mode="folder")
        ])})
        with patch.dict(os.environ, {"LOCALAPPDATA": str(Path(self.tmp.name) / "local"), "APPDATA": str(Path(self.tmp.name) / "roaming")}):
            summary = build_run_summary(plan)
            approved = replace(plan, approved_manifest=tuple(summary.approved_manifest))
            result = TaskRunner(ConfigManager(), approved).run()
        self.assertTrue(result.overall_success, result.report_body)
        self.assertEqual((self.b / "r_v20260201.txt").read_bytes(), b"new")
        self.assertEqual((self.b / "to be deleted" / old.name).read_bytes(), b"old")
        self.assertFalse(old.exists())

    def test_copy_before_archive_and_ignore_non_dates(self):
        (self.a / "report_v20260228.txt").write_bytes(b"new")
        (self.b / "report_v20260101.txt").write_bytes(b"old")
        (self.a / "report_v20260230.txt").write_bytes(b"invalid")
        (self.a / "report_v1.2.txt").write_bytes(b"semver")
        manager = self.manager(move_to_deleted=False)
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[:2], (1, 0))
        self.assertEqual(len(res.held), 0)
        self.assertEqual((self.b / "report_v20260228.txt").read_bytes(), b"new")
        self.assertEqual((self.b / "to be deleted" / "report_v20260101.txt").read_bytes(), b"old")
        self.assertFalse((self.b / "report_v1.2.txt").exists())
        self.assertEqual(manager.analyze_sync(), [])

    def test_same_date_conflict_is_held(self):
        (self.a / "r_v20260101.txt").write_bytes(b"a")
        (self.b / "r_v20260101.txt").write_bytes(b"b")
        manager = self.manager()
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[1], 0)
        self.assertEqual(len(res.held), 1)
        self.assertEqual((self.a / "r_v20260101.txt").read_bytes(), b"a")
        self.assertEqual((self.b / "r_v20260101.txt").read_bytes(), b"b")

    def test_old_same_date_conflict_holds_entire_family(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        (self.a / "r_v20260101.txt").write_bytes(b"old a")
        (self.b / "r_v20260101.txt").write_bytes(b"old b")
        manager = self.manager()
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[1], 0)
        self.assertEqual(len(res.held), 1)
        self.assertFalse((self.b / "r_v20260201.txt").exists())
        self.assertEqual((self.a / "r_v20260101.txt").read_bytes(), b"old a")
        self.assertEqual((self.b / "r_v20260101.txt").read_bytes(), b"old b")
        self.assertEqual((self.a / "r_v20260201.txt").read_bytes(), b"new")

    def test_alias_appearing_during_copy_blocks_install(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        manager = self.manager()
        actions = manager.analyze_sync()
        from src.core import date_sync
        original = date_sync.shutil.copyfileobj
        def inject(source, target):
            original(source, target)
            (self.b / "r-v20260201.txt").write_bytes(b"conflict")
        with patch("src.core.date_sync.shutil.copyfileobj", side_effect=inject):
            res = manager.execute_sync(actions)
            self.assertEqual(res[1], 1)
            self.assertEqual(len(res.held), 0)
        self.assertFalse((self.b / "r_v20260201.txt").exists())
        self.assertEqual(old.read_bytes(), b"old")
        self.assertEqual((self.a / "r_v20260201.txt").read_bytes(), b"new")

    def test_alias_appearing_after_install_blocks_archive(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        manager = self.manager()
        actions = manager.analyze_sync()
        from src.core import date_sync
        original = date_sync._exclusive_move
        def inject(source, target):
            original(source, target)
            if target.endswith("r_v20260201.txt"):
                (self.b / "r-v20260201.txt").write_bytes(b"conflict")
        with patch("src.core.date_sync._exclusive_move", side_effect=inject):
            res = manager.execute_sync(actions)
            self.assertEqual(res[1], 1)
            self.assertEqual(len(res.held), 0)
        self.assertEqual(old.read_bytes(), b"old")
        self.assertEqual((self.b / "r_v20260201.txt").read_bytes(), b"new")
        self.assertEqual((self.a / "r_v20260201.txt").read_bytes(), b"new")

    def test_preview_shows_archive_folder_and_hold_reason(self):
        from src.core.run_summary import _SummaryBuilder
        from src.core.task_contracts import SyncGroupConfig, SyncRunConfig
        from src.ui.sync_tab import date_preview_rows
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        (self.b / "r_v20260101.txt").write_bytes(b"old")
        manager = self.manager()
        actions = manager.analyze_sync()
        rows = date_preview_rows(actions)
        self.assertEqual([row["action"] for row in rows], ["복사", "to_be_deleted이동"])
        self.assertEqual(Path(rows[1]["target_folder"]), self.b / "to be deleted")
        builder = _SummaryBuilder()
        builder.sync(SyncRunConfig([SyncGroupConfig("g", [str(self.a), str(self.b)], date_latest_only=True)]))
        archive = next(entry for entry in builder.summary.entries if entry.action == "archive")
        self.assertEqual(Path(archive.target), self.b / "to be deleted")
        (self.b / "r_v20260201.txt").write_bytes(b"conflict")
        builder = _SummaryBuilder()
        builder.sync(SyncRunConfig([SyncGroupConfig("g", [str(self.a), str(self.b)], date_latest_only=True)]))
        held = next(entry for entry in builder.summary.entries if entry.action == "held")
        self.assertIn("Conflicting", held.reason)
        self.assertTrue(held.target.startswith(str(self.b)) or held.target.startswith(str(self.a)))

    def test_invalid_windows_archive_names_are_blocked(self):
        for name in ("sub.", "sub ", " sub", ".sub", "CON", "a:b", "LPT1.txt"):
            with self.subTest(name=name):
                manager = self.manager(archive_folder_name=name)
                res = manager.execute_sync(manager.analyze_sync())
                self.assertEqual(res[1], 1)
                self.assertEqual(len(res.held), 0)
                self.assertTrue(any("Invalid archive folder name" in err for err in res[2]))

    def test_empty_archive_uses_consistent_default(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        (self.b / "r_v20260101.txt").write_bytes(b"old")
        manager = self.manager(archive_folder_name="")
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[1], 0)
        self.assertEqual(len(res.held), 0)
        self.assertTrue((self.b / "to be deleted" / "r_v20260101.txt").exists())
        self.assertEqual(manager.analyze_sync(), [])

    @unittest.skipUnless(os.name == "nt", "Windows case-insensitive filesystem")
    def test_windows_subfolder_case_difference(self):
        (self.a / "Sub").mkdir()
        (self.b / "sub").mkdir()
        (self.a / "Sub" / "r_v20260201.txt").write_bytes(b"new")
        (self.b / "sub" / "r_v20260101.txt").write_bytes(b"old")
        manager = self.manager(include_subfolders=True)
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[:2], (1, 0))
        self.assertEqual(len(res.held), 0)
        self.assertEqual((self.b / "sub" / "r_v20260201.txt").read_bytes(), b"new")
        self.assertTrue((self.b / "to be deleted" / "sub" / "r_v20260101.txt").exists())

    def test_archive_physical_alias_is_blocked(self):
        archive = self.a / "archive-long"
        archive.mkdir()
        manager = self.manager(archive_folder_name="ARCHIV~1")
        import src.core.date_sync as module
        real_lstat = module.os.lstat
        real_samefile = module.os.path.samefile
        def fake_lstat(path, *args, **kwargs):
            if str(path) == str(self.a / "ARCHIV~1"):
                return real_lstat(archive)
            return real_lstat(path, *args, **kwargs)
        def fake_samefile(left, right):
            if str(right) == str(self.a / "ARCHIV~1"):
                return Path(left) == archive
            return real_samefile(left, right)
        with patch("src.core.date_sync.os.lstat", side_effect=fake_lstat), patch("src.core.date_sync.os.path.samefile", side_effect=fake_samefile):
            res = manager.execute_sync(manager.analyze_sync())
            self.assertEqual(res[1], 1)
            self.assertEqual(len(res.held), 0)
            self.assertTrue(any("Archive folder alias is ambiguous" in err for err in res[2]))

    def test_non_ascii_digits_are_not_dates(self):
        (self.a / "r_v２０２６０２０１.txt").write_bytes(b"ignored")
        self.assertEqual(self.manager().analyze_sync(), [])

    def test_ancestor_access_failure_blocks(self):
        import src.core.date_sync as module
        original = module.os.lstat
        def fail_parent(path, *args, **kwargs):
            if Path(path) == self.a.parent:
                raise PermissionError("denied ancestor")
            return original(path, *args, **kwargs)
        manager = self.manager()
        with patch("src.core.date_sync.os.lstat", side_effect=fail_parent):
            res = manager.execute_sync(manager.analyze_sync())
            self.assertEqual(res[1], 1)
            self.assertEqual(len(res.held), 0)
            self.assertTrue(any("denied ancestor" in err for err in res[2]))

    def test_one_way_newer_target_is_held(self):
        (self.a / "r_v20260101.txt").write_bytes(b"a")
        (self.b / "r_v20260201.txt").write_bytes(b"b")
        manager = self.manager(sync_mode="one_way")
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[1], 0)
        self.assertEqual(len(res.held), 1)
        self.assertEqual((self.a / "r_v20260101.txt").read_bytes(), b"a")
        self.assertEqual((self.b / "r_v20260201.txt").read_bytes(), b"b")

    def test_one_way_new_source_after_preview_is_held(self):
        (self.a / "r_v20260101.txt").write_bytes(b"a")
        manager = self.manager(sync_mode="one_way")
        actions = manager.analyze_sync()
        (self.a / "r_v20260201.txt").write_bytes(b"b")
        res = manager.execute_sync(actions)
        self.assertEqual(res[1], 1)
        self.assertEqual(len(res.held), 0)
        self.assertFalse((self.b / "r_v20260101.txt").exists())
        self.assertEqual((self.a / "r_v20260101.txt").read_bytes(), b"a")
        self.assertEqual((self.a / "r_v20260201.txt").read_bytes(), b"b")

    def test_changed_target_preserves_old(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        manager = self.manager()
        actions = manager.analyze_sync()
        old.write_bytes(b"changed")
        res = manager.execute_sync(actions)
        self.assertEqual(res[1], 1)
        self.assertEqual(len(res.held), 0)
        self.assertEqual(old.read_bytes(), b"changed")
        self.assertEqual((self.a / "r_v20260201.txt").read_bytes(), b"new")
        self.assertFalse((self.b / "r_v20260201.txt").exists())

    def test_missing_root_blocks(self):
        manager = SyncManager([str(self.a), str(self.b / "missing")], date_latest_only=True)
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[1], 1)
        self.assertEqual(len(res.held), 0)
        self.assertTrue(any("Folder unavailable" in err for err in res[2]))

    def test_copy_failure_preserves_old(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        manager = self.manager()
        actions = manager.analyze_sync()
        with patch("src.core.date_sync.shutil.copyfileobj", side_effect=OSError("injected")):
            res = manager.execute_sync(actions)
            self.assertEqual(res[1], 1)
            self.assertEqual(len(res.held), 0)
        self.assertEqual(old.read_bytes(), b"old")
        self.assertEqual((self.a / "r_v20260201.txt").read_bytes(), b"new")
        self.assertFalse((self.b / "r_v20260201.txt").exists())

    def test_copy_and_temporary_cleanup_failure_count_one_action(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        manager = self.manager()
        actions = manager.analyze_sync()
        with (patch("src.core.date_sync.shutil.copyfileobj", side_effect=OSError("copy failed")),
              patch("src.core.date_sync.os.unlink", side_effect=OSError("cleanup failed"))):
            res = manager.execute_sync(actions)
        self.assertEqual(res[:2], (0, 1))
        self.assertEqual(len(res.errors), 2)
        self.assertTrue(any("copy failed" in error for error in res.errors))
        self.assertTrue(any("cleanup failed" in error for error in res.errors))
        self.assertEqual(old.read_bytes(), b"old")
        self.assertFalse((self.b / "r_v20260201.txt").exists())

    def test_archive_failure_preserves_both(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        manager = self.manager()
        actions = manager.analyze_sync()
        from src.core import date_sync
        real_move = date_sync._exclusive_move
        def fail_archive(source, target):
            if "to be deleted" in target:
                raise OSError("injected")
            return real_move(source, target)
        with patch("src.core.date_sync._exclusive_move", side_effect=fail_archive):
            res = manager.execute_sync(actions)
            self.assertEqual(res[1], 1)
            self.assertEqual(len(res.held), 0)
        self.assertEqual(old.read_bytes(), b"old")
        self.assertEqual((self.b / "r_v20260201.txt").read_bytes(), b"new")
        self.assertEqual((self.a / "r_v20260201.txt").read_bytes(), b"new")

    def test_subfolders_and_exclusion(self):
        (self.a / "sub").mkdir()
        (self.a / "sub" / "r_V20260201.txt").write_bytes(b"new")
        (self.a / "sub" / "skip_v20260201.txt").write_bytes(b"skip")
        manager = self.manager(include_subfolders=True, exclude_patterns=["skip*"])
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[1], 0)
        self.assertEqual(len(res.held), 0)
        self.assertEqual((self.b / "sub" / "r_V20260201.txt").read_bytes(), b"new")
        self.assertFalse((self.b / "sub" / "skip_v20260201.txt").exists())

    def test_unverified_recycle_bin_is_blocked_before_any_change(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        manager = self.manager(date_archive_mode="trash")
        (self.a / "s_v20260201.txt").write_bytes(b"other")
        actions = manager.analyze_sync()
        actions.append({"action": "날짜 보류", "filename": "held_v20260101.txt", "reason": "Target has a newer date"})
        actions.append({"action": "오류", "filename": "err_v20260101.txt", "reason": "Scan error"})
        with (patch("src.core.date_sync._recycle_old_file") as recycle,
              patch("src.core.date_sync._exclusive_move") as move):
            res = manager.execute_sync(actions)
            self.assertEqual(res[0], 0)
            self.assertEqual(res[1], sum(a["action"] == "날짜 동기화" for a in actions) + 1)
            self.assertEqual(len(res.held), 1)
            recycle.assert_not_called()
            move.assert_not_called()
        self.assertTrue(any("Recycle Bin operation disabled" in err for err in res[2]))
        self.assertTrue(any("Scan error" in err for err in res[2]))
        self.assertTrue(any("Target has a newer date" in h for h in res.held))
        # 휴지통 실패 시 영구 삭제 폴백 없이 원본 보존 확인
        self.assertTrue(old.exists())
        self.assertEqual(old.read_bytes(), b"old")
        self.assertEqual((self.a / "r_v20260201.txt").read_bytes(), b"new")
        self.assertFalse((self.b / "r_v20260201.txt").exists())
        self.assertFalse((self.b / "s_v20260201.txt").exists())

    def test_trash_mode_allows_copy_when_no_old_versions_exist(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        manager = self.manager(date_archive_mode="trash")
        res = manager.execute_sync(manager.analyze_sync())
        self.assertEqual(res[:2], (1, 0))
        self.assertEqual((self.b / "r_v20260201.txt").read_bytes(), b"new")

    def test_scan_permission_error_is_failure_not_held(self):
        sub = self.a / "locked"
        sub.mkdir()
        (sub / "r_v20260101.txt").write_bytes(b"data")
        manager = self.manager(include_subfolders=True)
        import src.core.date_sync as module
        orig_walk = module.os.walk
        def fake_walk(top, *args, **kwargs):
            if kwargs.get("onerror"):
                kwargs["onerror"](PermissionError(f"Permission denied: {sub}"))
            return orig_walk(top, *args, **kwargs)
        with patch("src.core.date_sync.os.walk", side_effect=fake_walk):
            actions = manager.analyze_sync()
            self.assertTrue(any(act.get("action") == "오류" for act in actions))
            res = manager.execute_sync(actions)
            self.assertEqual(res[1], 1)
            self.assertEqual(len(res.held), 0)
            self.assertTrue(any("Permission denied" in err for err in res[2]))

    def test_cancellation_during_execution_records_failure_and_preserves_files(self):
        (self.a / "r_v20260201.txt").write_bytes(b"new")
        old = self.b / "r_v20260101.txt"
        old.write_bytes(b"old")
        manager = self.manager()
        actions = manager.analyze_sync()
        def cancel_on_progress(*_args):
            manager.cancel()
        res = manager.execute_sync(actions, progress_callback=cancel_on_progress)
        self.assertEqual(res[1], 1)
        self.assertTrue(any("cancelled" in err.lower() for err in res[2]))
        self.assertTrue(old.exists())
        self.assertEqual(old.read_bytes(), b"old")

    def test_partial_cancellation_accounts_for_each_remaining_action(self):
        for name in ("a", "b", "c"):
            (self.a / f"{name}_v20260201.txt").write_bytes(name.encode())
        manager = self.manager()
        actions = sorted(manager.analyze_sync(), key=lambda action: action["filename"])
        actions.append({"action": "날짜 보류", "filename": "held", "reason": "conflict"})
        actions.append({"action": "오류", "filename": "bad", "reason": "scan error"})

        def cancel_after_first(index, *_args):
            if index == 1:
                manager.cancel()

        res = manager.execute_sync(actions, progress_callback=cancel_after_first)
        self.assertEqual(res[:2], (1, 3))
        self.assertEqual(len(res.held), 1)
        self.assertTrue(any("b_v20260201.txt" in error and "cancelled" in error for error in res[2]))
        self.assertTrue(any("c_v20260201.txt" in error and "cancelled" in error for error in res[2]))
        self.assertTrue(any("scan error" in error for error in res[2]))
        self.assertEqual((self.b / "a_v20260201.txt").read_bytes(), b"a")
        self.assertFalse((self.b / "b_v20260201.txt").exists())
        self.assertFalse((self.b / "c_v20260201.txt").exists())

    def test_cancellation_during_copy_accounts_for_current_and_remaining(self):
        for name in ("a", "b"):
            (self.a / f"{name}_v20260201.txt").write_bytes(name.encode())
        manager = self.manager()
        actions = sorted(manager.analyze_sync(), key=lambda action: action["filename"])
        from src.core import date_sync
        copy = date_sync.shutil.copyfileobj

        def cancel_during_copy(source, target):
            copy(source, target)
            manager.cancel()

        with patch("src.core.date_sync.shutil.copyfileobj", side_effect=cancel_during_copy):
            res = manager.execute_sync(actions)
        self.assertEqual(res[:2], (0, 2))
        self.assertTrue(all("cancelled" in error.lower() for error in res[2]))
        self.assertFalse((self.b / "a_v20260201.txt").exists())
        self.assertFalse((self.b / "b_v20260201.txt").exists())


if __name__ == "__main__":
    unittest.main()
