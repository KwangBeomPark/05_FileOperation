import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.collect_sync import (
    ACTION_COPY,
    ACTION_ERROR,
    ACTION_REPLACE,
    ACTION_TARGET_NEWER,
    ACTION_UNCHANGED,
    ARCHIVE_DIR_NAME,
    CollectGroup,
    CollectStateError,
    run_collect_groups,
)

BASE_TIME = 1_700_000_000
REAL_REPLACE = os.replace
REAL_RENAME = os.rename


class CollectSyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.src_a = self.root / "A"
        self.src_b = self.root / "B"
        self.target = self.root / "T"
        for folder in (self.src_a, self.src_b, self.target):
            folder.mkdir()
        self.state_path = self.root / "collect_state.json"

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, folder, name, text, mtime=BASE_TIME):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        os.utime(path, (mtime, mtime))
        return path

    def group(self, sources=None, keywords=("보고서",), subfolders=False):
        return CollectGroup(
            name="g",
            sources=tuple(str(s) for s in (sources or [self.src_a])),
            keywords=tuple(keywords),
            target=str(self.target),
            include_subfolders=subfolders,
        )

    def run_once(self, groups=None, dry_run=False):
        return run_collect_groups(
            groups or [self.group()], self.state_path, dry_run=dry_run
        )

    def read(self, path):
        return Path(path).read_bytes().decode("utf-8")

    def test_matching_files_are_copied_flat_with_case_insensitive_keywords(self):
        self.write(self.src_a, "2025 보고서 최종.xlsx", "one")
        self.write(self.src_a, "Report-REPORT.docx", "two")
        self.write(self.src_a, "메모.txt", "not matched")
        self.write(self.src_a, "~$보고서.xlsx", "office lock file")
        self.write(self.src_a / "sub", "보고서_sub.xlsx", "subfolder not included")

        report = self.run_once([self.group(keywords=("보고서", "report"))])

        self.assertEqual(report.count(ACTION_COPY), 2)
        self.assertEqual(
            sorted(entry.name for entry in self.target.iterdir()),
            ["2025 보고서 최종.xlsx", "Report-REPORT.docx"],
        )

    def test_subfolders_are_included_only_when_enabled(self):
        self.write(self.src_a / "sub", "보고서_sub.xlsx", "nested")

        self.run_once([self.group(subfolders=True)])

        self.assertEqual(
            [entry.name for entry in self.target.iterdir()], ["보고서_sub.xlsx"]
        )

    def test_unchanged_files_are_not_copied_again_on_repeated_runs(self):
        self.write(self.src_a, "보고서.xlsx", "same")
        self.run_once()

        second = self.run_once()
        third = self.run_once()

        self.assertEqual(second.count(ACTION_UNCHANGED), 1)
        self.assertEqual(third.count(ACTION_UNCHANGED), 1)
        self.assertFalse((self.target / ARCHIVE_DIR_NAME).exists())
        self.assertEqual(
            [entry.name for entry in self.target.iterdir()], ["보고서.xlsx"]
        )

    def test_changed_source_moves_previous_version_to_numbered_archive(self):
        self.write(self.src_a, "보고서.xlsx", "v1", mtime=BASE_TIME)
        self.run_once()

        self.write(self.src_a, "보고서.xlsx", "v2", mtime=BASE_TIME + 100)
        second = self.run_once()
        self.write(self.src_a, "보고서.xlsx", "v3", mtime=BASE_TIME + 200)
        third = self.run_once()

        self.assertEqual(second.count(ACTION_REPLACE), 1)
        self.assertEqual(third.count(ACTION_REPLACE), 1)
        archive = self.target / ARCHIVE_DIR_NAME
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "v3")
        self.assertEqual(self.read(archive / "보고서 (01).xlsx"), "v1")
        self.assertEqual(self.read(archive / "보고서 (02).xlsx"), "v2")

    def test_same_name_from_two_sources_keeps_both_and_does_not_churn(self):
        self.write(self.src_a, "보고서.xlsx", "from A", mtime=BASE_TIME)
        self.write(self.src_b, "보고서.xlsx", "from B", mtime=BASE_TIME + 10)
        group = self.group(sources=[self.src_a, self.src_b])

        first = self.run_once([group])
        second = self.run_once([group])
        third = self.run_once([group])

        self.assertEqual(first.count(ACTION_COPY), 2)
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "from A")
        self.assertEqual(self.read(self.target / "보고서 [B].xlsx"), "from B")
        for report in (second, third):
            self.assertEqual(report.count(ACTION_UNCHANGED), 2)
            self.assertEqual(report.count(ACTION_REPLACE), 0)
        self.assertFalse((self.target / ARCHIVE_DIR_NAME).exists())

    def test_target_copy_newer_than_source_is_kept_and_reported(self):
        self.write(self.src_a, "보고서.xlsx", "source v1", mtime=BASE_TIME)
        self.run_once()
        self.write(self.target, "보고서.xlsx", "edited by hand", mtime=BASE_TIME + 500)
        os.utime(self.target / "보고서.xlsx", (BASE_TIME + 500, BASE_TIME + 500))

        report = self.run_once()

        self.assertEqual(report.count(ACTION_TARGET_NEWER), 1)
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "edited by hand")
        self.assertFalse((self.target / ARCHIVE_DIR_NAME).exists())

    def test_existing_unmapped_target_file_is_never_overwritten(self):
        self.write(self.target, "보고서.xlsx", "made by hand")
        self.write(self.src_a, "보고서.xlsx", "from A")

        report = self.run_once()

        self.assertEqual(report.count(ACTION_COPY), 1)
        self.assertEqual(report.actions[0].target_name, "보고서 [A].xlsx")
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "made by hand")
        self.assertEqual(self.read(self.target / "보고서 [A].xlsx"), "from A")

    def test_dry_run_changes_nothing(self):
        self.write(self.src_a, "보고서.xlsx", "x")

        report = self.run_once(dry_run=True)

        self.assertEqual(report.count(ACTION_COPY), 1)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertFalse(self.state_path.exists())

    def test_deleted_source_keeps_target_file(self):
        source = self.write(self.src_a, "보고서.xlsx", "keep me")
        self.run_once()
        source.unlink()

        report = self.run_once()

        self.assertEqual(report.count(ACTION_ERROR), 0)
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "keep me")

    def test_locked_target_is_reported_and_other_files_still_run(self):
        self.write(self.src_a, "보고서1.xlsx", "old1")
        self.write(self.src_a, "보고서2.xlsx", "old2")
        self.run_once()
        self.write(self.src_a, "보고서1.xlsx", "new1", mtime=BASE_TIME + 100)
        self.write(self.src_a, "보고서2.xlsx", "new2", mtime=BASE_TIME + 100)

        def fake_replace(src, dst):
            if Path(src).name == "보고서1.xlsx":
                raise PermissionError(
                    32,
                    "The process cannot access the file because it is being used by another process",
                )
            return REAL_RENAME(src, dst)

        with patch("src.core.collect_sync.os.rename", side_effect=fake_replace):
            report = self.run_once()

        errors = [action for action in report.actions if action.kind == ACTION_ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("being used by another process", errors[0].message)
        self.assertEqual(self.read(self.target / "보고서1.xlsx"), "old1")
        self.assertEqual(self.read(self.target / "보고서2.xlsx"), "new2")

    def test_group_with_target_inside_source_is_rejected(self):
        nested_target = self.src_a / "out"
        nested_target.mkdir()
        group = CollectGroup(
            name="bad",
            sources=(str(self.src_a),),
            keywords=("보고서",),
            target=str(nested_target),
        )

        report = self.run_once([group])

        self.assertEqual(report.count(ACTION_ERROR), 1)
        self.assertIn("포함 관계", report.actions[0].message)

    def test_group_without_keywords_is_rejected(self):
        self.write(self.src_a, "보고서.xlsx", "x")

        report = self.run_once([self.group(keywords=("  ",))])

        self.assertEqual(report.count(ACTION_ERROR), 1)
        self.assertEqual(report.count(ACTION_COPY), 0)

    def test_cyclic_groups_are_blocked_without_growth_but_healthy_group_runs(self):
        self.write(self.src_a, "보고서.txt", "unchanged")
        forward = CollectGroup(
            "forward", (str(self.src_a),), ("보고서",), str(self.src_b)
        )
        backward = CollectGroup(
            "backward", (str(self.src_b),), ("보고서",), str(self.src_a)
        )
        for _ in range(3):
            result = self.run_once([forward, backward, self.group()])
            self.assertEqual(
                sum(action.message_code == "cycle" for action in result.actions), 2
            )
            self.assertEqual(list(self.src_b.iterdir()), [])
            self.assertEqual(len(list(self.src_a.iterdir())), 1)
        self.assertEqual(self.read(self.src_a / "보고서.txt"), "unchanged")
        self.assertEqual(self.read(self.target / "보고서.txt"), "unchanged")

    def test_three_group_loop_rejected_but_acyclic_chain_allowed(self):
        self.write(self.src_a, "보고서.txt", "data")
        first = CollectGroup("a-b", (str(self.src_a),), ("보고서",), str(self.src_b))
        second = CollectGroup("b-t", (str(self.src_b),), ("보고서",), str(self.target))
        third = CollectGroup("t-a", (str(self.target),), ("보고서",), str(self.src_a))
        self.assertEqual(self.run_once([first, second, third]).count(ACTION_ERROR), 3)
        self.assertEqual(list(self.src_b.iterdir()), [])
        result = self.run_once([first, second])
        self.assertEqual(result.count(ACTION_COPY), 2)
        self.assertEqual(self.read(self.target / "보고서.txt"), "data")

    def test_selected_group_is_checked_against_all_configured_groups(self):
        self.write(self.src_a, "보고서.txt", "data")
        forward = CollectGroup(
            "forward", (str(self.src_a),), ("보고서",), str(self.src_b)
        )
        backward = CollectGroup(
            "backward", (str(self.src_b),), ("보고서",), str(self.src_a)
        )
        result = run_collect_groups(
            [forward], self.state_path, configured_groups=[forward, backward]
        )
        self.assertEqual(result.actions[0].message_code, "cycle")
        self.assertEqual(list(self.src_b.iterdir()), [])

    def test_corrupt_state_file_stops_the_run_instead_of_duplicating(self):
        self.write(self.src_a, "보고서.xlsx", "x")
        self.state_path.write_text("{not json", encoding="utf-8")

        with self.assertRaises(CollectStateError):
            self.run_once()
        self.assertEqual(list(self.target.iterdir()), [])

    def test_progress_and_cancel_preserve_committed_mapping(self):
        self.write(self.src_a, "보고서1.xlsx", "one")
        self.write(self.src_a, "보고서2.xlsx", "two")
        progress = []
        report = run_collect_groups(
            [self.group()],
            self.state_path,
            progress_callback=lambda *args: progress.append(args),
            should_cancel=lambda: any(item[0] == 1 for item in progress),
        )
        self.assertTrue(report.cancelled)
        self.assertEqual(report.count(ACTION_COPY), 1)
        self.assertEqual(progress[-1][:2], (1, 2))
        resumed = self.run_once()
        self.assertEqual(resumed.count(ACTION_UNCHANGED), 1)
        self.assertEqual(resumed.count(ACTION_COPY), 1)
        self.assertFalse(any("[A]" in p.name for p in self.target.iterdir()))

    def test_cancel_before_scan_does_not_write(self):
        report = run_collect_groups(
            [self.group()], self.state_path, should_cancel=lambda: True
        )
        self.assertTrue(report.cancelled)
        self.assertFalse(self.state_path.exists())

    def test_read_only_source_success_and_replacement(self):
        source = self.write(self.src_a, "보고서.xlsx", "old")
        source.chmod(stat.S_IREAD)
        try:
            self.assertEqual(self.run_once().count(ACTION_COPY), 1)
            source.chmod(stat.S_IWRITE | stat.S_IREAD)
            self.write(self.src_a, source.name, "new", BASE_TIME + 100)
            source.chmod(stat.S_IREAD)
            self.assertEqual(self.run_once().count(ACTION_REPLACE), 1)
            self.assertEqual(self.read(self.target / source.name), "new")
            self.assertEqual(list(self.target.glob(".collect-tmp-*")), [])
        finally:
            source.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_read_only_temp_cleaned_on_new_copy_failure(self):
        source = self.write(self.src_a, "보고서.xlsx", "read only")
        source.chmod(stat.S_IREAD)

        def fail_install(src, dst):
            if Path(src).name.startswith(".collect-tmp-"):
                raise PermissionError("original install failure")
            return REAL_RENAME(src, dst)

        try:
            with patch("src.core.collect_sync.os.rename", side_effect=fail_install):
                report = self.run_once()
            self.assertIn("original install failure", report.actions[0].message)
            self.assertEqual(list(self.target.iterdir()), [])
        finally:
            source.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_read_only_temp_cleaned_and_old_target_restored_on_replace_failure(self):
        source = self.write(self.src_a, "보고서.xlsx", "old")
        self.run_once()
        self.write(self.src_a, source.name, "new", BASE_TIME + 100)
        source.chmod(stat.S_IREAD)

        def fail_install(src, dst):
            if Path(src).name.startswith(".collect-tmp-"):
                raise PermissionError("original replacement failure")
            return REAL_RENAME(src, dst)

        try:
            with patch("src.core.collect_sync.os.rename", side_effect=fail_install):
                report = self.run_once()
            self.assertIn("original replacement failure", report.actions[0].message)
            self.assertEqual(self.read(self.target / source.name), "old")
            self.assertEqual(list(self.target.glob(".collect-tmp-*")), [])
        finally:
            source.chmod(stat.S_IWRITE | stat.S_IREAD)

    @unittest.skipUnless(os.name == "nt", "Windows exclusive rename semantics")
    def test_archive_created_after_scan_is_preserved_and_number_retried(self):
        self.write(self.src_a, "보고서.xlsx", "old")
        self.run_once()
        self.write(self.src_a, "보고서.xlsx", "new", BASE_TIME + 100)
        collision = self.target / ARCHIVE_DIR_NAME / "보고서 (01).xlsx"

        def create_archive(src, dst):
            if Path(dst) == collision and not collision.exists():
                self.write(collision.parent, collision.name, "unrelated archive")
            return REAL_RENAME(src, dst)

        with patch("src.core.collect_sync.os.rename", side_effect=create_archive):
            result = self.run_once()
        self.assertEqual(result.count(ACTION_REPLACE), 1)
        self.assertEqual(result.actions[0].archived_name, "보고서 (02).xlsx")
        self.assertEqual(self.read(collision), "unrelated archive")
        self.assertEqual(self.read(collision.with_name("보고서 (02).xlsx")), "old")
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "new")

    @unittest.skipUnless(os.name == "nt", "Windows exclusive rename semantics")
    def test_install_and_rollback_never_overwrite_concurrent_target(self):
        self.write(self.src_a, "보고서.xlsx", "old")
        self.run_once()
        self.write(self.src_a, "보고서.xlsx", "new", BASE_TIME + 100)

        def create_target(src, dst):
            if Path(src).name.startswith(".collect-tmp-"):
                self.write(self.target, "보고서.xlsx", "concurrent user file")
            return REAL_RENAME(src, dst)

        with patch("src.core.collect_sync.os.rename", side_effect=create_target):
            result = self.run_once()
        self.assertEqual(result.count(ACTION_ERROR), 1)
        self.assertIn("previous copy preserved", result.actions[0].message)
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "concurrent user file")
        self.assertEqual(
            self.read(self.target / ARCHIVE_DIR_NAME / "보고서 (01).xlsx"), "old"
        )
        self.assertEqual(list(self.target.glob(".collect-tmp-*")), [])

    def test_unavailable_scan_records_error_and_continues_next_group(self):
        self.write(self.src_b, "보고서.xlsx", "ok")
        real_scandir = os.scandir

        def fail_first(path):
            if str(path) == str(self.src_a):
                raise OSError("network disconnected")
            return real_scandir(path)

        with patch("src.core.collect_sync.os.scandir", side_effect=fail_first):
            report = self.run_once([self.group(), self.group(sources=[self.src_b])])
        self.assertEqual(report.count(ACTION_ERROR), 1)
        self.assertEqual(report.count(ACTION_COPY), 1)

    def test_subfolder_error_then_root_scan_error_does_not_stop_healthy_group(self):
        self.write(self.src_a / "denied", "보고서.txt", "denied")
        healthy = self.root / "healthy"
        self.write(healthy, "보고서.txt", "ok")
        problem = self.group(sources=[self.src_a, self.src_b], subfolders=True)
        real_scan = os.scandir

        def scan(path):
            if Path(path) in (self.src_a / "denied", self.src_b):
                raise PermissionError("denied", str(path))
            return real_scan(path)

        with patch("src.core.collect_sync.os.scandir", side_effect=scan):
            result = self.run_once([problem, self.group(sources=[healthy])])
        self.assertEqual(result.count(ACTION_ERROR), 2)
        self.assertEqual(result.count(ACTION_COPY), 1)
        self.assertEqual(self.read(self.target / "보고서.txt"), "ok")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertFalse(state["pending"])
        self.assertEqual(
            state["targets"][os.path.normcase(str(self.target))],
            {os.path.normcase(str(healthy / "보고서.txt")): "보고서.txt"},
        )

    def test_malformed_mapping_stops_before_writing(self):
        for targets in (
            {"target": []},
            {"target": {"source": "../escape"}},
            {"target": None},
        ):
            self.state_path.write_text(
                json.dumps({"version": 1, "targets": targets}), encoding="utf-8"
            )
            with self.assertRaises(CollectStateError):
                self.run_once()

    def test_unreadable_subfolder_is_reported_without_losing_other_candidates(self):
        self.write(self.src_a, "보고서_root.xlsx", "root")
        denied = self.src_a / "denied"
        self.write(denied, "보고서_denied.xlsx", "denied")
        self.write(self.src_a / "allowed", "보고서_allowed.xlsx", "allowed")
        real_scandir = os.scandir

        def scan(path):
            if str(path) == str(denied):
                raise PermissionError("folder denied")
            return real_scandir(path)

        with patch("src.core.collect_sync.os.scandir", side_effect=scan):
            result = self.run_once([self.group(subfolders=True)])
        self.assertEqual(result.count(ACTION_COPY), 2)
        self.assertEqual(result.count(ACTION_ERROR), 1)
        self.assertEqual(
            next(a.source for a in result.actions if a.kind == ACTION_ERROR),
            str(denied),
        )

    def test_target_directory_name_is_reserved_and_source_gets_suffix(self):
        (self.target / "보고서.xlsx").mkdir()
        self.write(self.src_a, "보고서.xlsx", "data")
        result = self.run_once()
        self.assertEqual(result.count(ACTION_COPY), 1)
        self.assertEqual(result.actions[0].target_name, "보고서 [A].xlsx")
        self.assertTrue((self.target / "보고서.xlsx").is_dir())
        self.assertEqual(self.run_once().count(ACTION_UNCHANGED), 1)

    def test_archive_name_is_reserved_even_before_archive_is_created(self):
        self.write(self.src_a, ARCHIVE_DIR_NAME, "data")
        result = self.run_once([self.group(keywords=(ARCHIVE_DIR_NAME,))])
        self.assertEqual(result.count(ACTION_COPY), 1)
        self.assertEqual(result.actions[0].target_name, ARCHIVE_DIR_NAME + " [A]")

    def test_state_reservation_failure_does_not_copy_an_untracked_file(self):
        source = self.write(self.src_a, "보고서.xlsx", "one")
        with (
            patch(
                "src.core.collect_sync.atomic_write_json",
                side_effect=PermissionError("state locked"),
            ),
            self.assertRaises(CollectStateError),
        ):
            self.run_once()
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertTrue(source.exists())
        self.assertEqual(self.run_once().count(ACTION_COPY), 1)
        self.assertEqual([p.name for p in self.target.iterdir()], [source.name])

    def test_state_serialization_failure_is_safe_state_error(self):
        self.write(self.src_a, "보고서.txt", "data")
        with (
            patch(
                "src.core.collect_sync.atomic_write_json",
                side_effect=ValueError("serialization failed"),
            ),
            self.assertRaises(CollectStateError) as raised,
        ):
            self.run_once()
        self.assertEqual(raised.exception.report.count(ACTION_ERROR), 1)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_collection_state_escapes_unpaired_unicode_without_global_policy_change(
        self,
    ):
        from src.core.collect_sync import CollectState

        state = CollectState(self.state_path, {"target": {"source\ud800": "safe.txt"}})
        state.save()
        self.assertIn(
            "source\ud800", CollectState.load(self.state_path).targets["target"]
        )

    def test_later_reservation_failure_keeps_partial_report_and_prevents_duplicates(
        self,
    ):
        from src.core import collect_sync

        self.write(self.src_a, "보고서1.xlsx", "one")
        self.write(self.src_a, "보고서2.xlsx", "two")
        real_write = collect_sync.atomic_write_json
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise PermissionError("state disconnected")
            return real_write(*args, **kwargs)

        with (
            patch("src.core.collect_sync.atomic_write_json", side_effect=fail_second),
            self.assertRaises(CollectStateError) as raised,
        ):
            self.run_once()
        self.assertEqual(raised.exception.report.count(ACTION_COPY), 1)
        self.assertEqual(raised.exception.report.count(ACTION_ERROR), 1)
        self.assertEqual([p.name for p in self.target.iterdir()], ["보고서1.xlsx"])
        resumed = self.run_once()
        self.assertEqual(resumed.count(ACTION_UNCHANGED), 1)
        self.assertEqual(resumed.count(ACTION_COPY), 1)

    def test_interrupted_commit_blocks_retry_without_claiming_unknown_target(self):
        from src.core import collect_sync

        self.write(self.src_a, "보고서.xlsx", "one")
        real_write = collect_sync.atomic_write_json
        calls = 0

        def fail_commit(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PermissionError("commit disconnected")
            return real_write(*args, **kwargs)

        with (
            patch("src.core.collect_sync.atomic_write_json", side_effect=fail_commit),
            self.assertRaises(CollectStateError) as raised,
        ):
            self.run_once()
        self.assertEqual(raised.exception.report.count(ACTION_COPY), 1)
        self.assertEqual(raised.exception.report.count(ACTION_ERROR), 1)
        self.assertTrue(
            json.loads(self.state_path.read_text(encoding="utf-8"))["pending"]
        )
        before = [p.name for p in self.target.iterdir()]
        with self.assertRaises(CollectStateError):
            self.run_once()
        self.assertEqual([p.name for p in self.target.iterdir()], before)

    def test_failed_new_copy_does_not_claim_a_later_user_file(self):
        self.write(self.src_a, "보고서.xlsx", "from source")
        with patch(
            "src.core.collect_sync.shutil.copy2",
            side_effect=PermissionError("locked source"),
        ):
            self.assertEqual(self.run_once().count(ACTION_ERROR), 1)
        self.write(self.target, "보고서.xlsx", "user file")
        report = self.run_once()
        self.assertEqual(report.count(ACTION_COPY), 1)
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "user file")
        self.assertEqual(self.read(self.target / "보고서 [A].xlsx"), "from source")

    @unittest.skipUnless(os.name == "nt", "Windows exclusive rename semantics")
    def test_target_appearing_after_scan_is_not_overwritten(self):
        self.write(self.src_a, "보고서.xlsx", "from source")

        def race_create(src, dst):
            Path(dst).write_text("user file", encoding="utf-8")
            return REAL_RENAME(src, dst)

        with patch("src.core.collect_sync.os.rename", side_effect=race_create):
            result = self.run_once()
        self.assertEqual(result.count(ACTION_ERROR), 1)
        self.assertEqual(self.read(self.target / "보고서.xlsx"), "user file")
        self.assertEqual(self.run_once().count(ACTION_COPY), 1)

    def test_link_source_root_is_not_followed(self):
        from src.core.collect_sync import _is_link

        self.write(self.src_a, "보고서.xlsx", "one")
        with patch(
            "src.core.collect_sync._is_link",
            side_effect=lambda p: str(p) == str(self.src_a) or _is_link(p),
        ):
            result = self.run_once()
        self.assertEqual(result.count(ACTION_ERROR), 1)
        self.assertEqual(result.actions[0].message_code, "link")
        self.assertEqual(list(self.target.iterdir()), [])

    def test_unreadable_ancestor_is_not_assumed_safe(self):
        self.write(self.src_a, "보고서.txt", "data")
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            if Path(path) == self.root:
                raise PermissionError("ancestor metadata denied")
            return real_lstat(path, *args, **kwargs)

        with patch("src.core.collect_sync.os.lstat", side_effect=lstat):
            result = self.run_once()
        self.assertEqual(result.count(ACTION_ERROR), 1)
        self.assertEqual(result.count(ACTION_COPY), 0)
        self.assertFalse(self.state_path.exists())

    def test_long_collision_name_is_error_without_pending_and_other_files_run(self):
        name = "보고서" + "x" * 247 + ".txt"
        self.write(self.src_a, name, "source")
        self.write(self.target, name, "user")
        self.write(self.src_a, "보고서_ok.txt", "ok")
        result = self.run_once()
        self.assertEqual(result.count(ACTION_ERROR), 1)
        self.assertEqual(result.count(ACTION_COPY), 1)
        self.assertEqual(
            next(a for a in result.actions if a.kind == ACTION_ERROR).message_code,
            "name",
        )
        self.assertFalse(
            json.loads(self.state_path.read_text(encoding="utf-8"))["pending"]
        )
        self.assertEqual(self.read(self.target / name), "user")
        self.assertEqual(self.run_once().count(ACTION_UNCHANGED), 1)

    @unittest.skipUnless(os.name == "nt", "Windows UNC semantics")
    def test_unc_share_root_label_is_safe_component(self):
        from src.core.collect_sync import (
            _source_folder_label,
            unique_target_name,
            valid_target_name,
        )

        label = _source_folder_label(r"\\nas\총무")
        self.assertEqual(label, "총무")
        self.assertTrue(
            valid_target_name(unique_target_name("보고서.txt", label, {"보고서.txt"}))
        )

    def test_windows_filename_validation_includes_utf16_length(self):
        from src.core.collect_sync import valid_target_name

        for name in (
            "../escape",
            "CON.txt",
            "CON .txt",
            "COM¹.txt",
            "LPT³",
            "CONIN$",
            "CONOUT$.txt",
            "NUL",
            "x.",
            "a:b",
            "x" * 256,
            "😀" * 128,
            "\ud800.txt",
        ):
            self.assertFalse(valid_target_name(name), repr(name))
        self.assertTrue(valid_target_name("보고서.xlsx"))
        self.assertTrue(valid_target_name("x" * 255))
        self.assertTrue(valid_target_name("😀" * 127 + "x"))

    @unittest.skipUnless(os.name == "nt", "Windows junction safety")
    def test_target_under_real_junction_is_rejected_before_reservation(self):
        actual = self.root / "actual"
        (actual / "child").mkdir(parents=True)
        junction = self.root / "junction"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(actual)],
            check=True,
            capture_output=True,
        )
        self.write(self.src_a, "보고서.txt", "data")
        config = CollectGroup(
            "linked", (str(self.src_a),), ("보고서",), str(junction / "child")
        )
        try:
            for dry_run in (True, False):
                result = self.run_once([config], dry_run=dry_run)
                self.assertEqual(result.actions[0].message_code, "link")
                self.assertFalse(self.state_path.exists())
                self.assertEqual(list((actual / "child").iterdir()), [])
        finally:
            junction.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows directory junction safety")
    def test_real_junction_root_and_nested_source_are_not_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.write(outside, "보고서.xlsx", "outside")
        junction = self.src_a / "linked"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            check=True,
            capture_output=True,
        )
        try:
            report = self.run_once([self.group(sources=[junction])])
            self.assertEqual(report.count(ACTION_ERROR), 1)
            report = self.run_once([self.group(subfolders=True)])
            self.assertEqual(report.count(ACTION_COPY), 0)
            self.assertTrue((outside / "보고서.xlsx").exists())
        finally:
            # rmdir removes only this temporary junction, never its destination.
            junction.rmdir()


if __name__ == "__main__":
    unittest.main()
