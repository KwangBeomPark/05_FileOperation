"""Pending-copy recovery never deletes files or guesses their ownership."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.collect_recovery import (
    CollectRecoveryError,
    inspect_pending_copy,
    inspect_pending_release,
    recover_pending_copy,
)
from src.core.collect_sync import (
    ACTION_COPY,
    CollectGroup,
    CollectState,
    CollectStateError,
    run_collect_groups,
)


class CollectRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_dir, self.target_dir = self.root / "source", self.root / "target"
        self.source_dir.mkdir()
        self.target_dir.mkdir()
        self.source = self.source_dir / "report.txt"
        self.source.write_text("content", encoding="utf-8")
        self.target = self.target_dir / self.source.name
        self.path = self.root / "state.json"
        self.state = CollectState(self.path)
        self.state.pending = {
            "source": str(self.source),
            "target": str(self.target_dir),
            "name": self.target.name,
        }
        self.state.save()

    def tearDown(self):
        self.temporary.cleanup()

    def preview(self):
        return inspect_pending_copy(self.path)

    def test_preview_is_read_only_and_missing_file_can_be_retried(self):
        before = self.path.read_bytes()
        preview = self.preview()
        self.assertEqual(preview.status, "missing")
        self.assertEqual(self.path.read_bytes(), before)
        backup = recover_pending_copy(self.path, preview.fingerprint, "preserve")
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(CollectState.load(self.path).targets, {})
        group = CollectGroup(
            "g", (str(self.source_dir),), ("report",), str(self.target_dir)
        )
        self.assertEqual(run_collect_groups([group], self.path).count(ACTION_COPY), 1)

    def test_equal_contents_are_not_adopted_without_explicit_decision(self):
        self.target.write_text("content", encoding="utf-8")
        preview = self.preview()
        self.assertEqual(preview.status, "matching")
        with self.assertRaises(CollectStateError):
            CollectState.load(self.path)
        recover_pending_copy(self.path, preview.fingerprint, "preserve")
        self.assertEqual(CollectState.load(self.path).targets, {})
        self.assertEqual(self.target.read_text(encoding="utf-8"), "content")

    def test_matching_copy_can_be_explicitly_adopted(self):
        self.target.write_text("content", encoding="utf-8")
        recover_pending_copy(self.path, self.preview().fingerprint, "adopt")
        state = CollectState.load(self.path)
        self.assertEqual(
            state.targets[os.path.normcase(str(self.target_dir))][
                os.path.normcase(str(self.source))
            ],
            "report.txt",
        )
        self.assertEqual(self.target.read_text(encoding="utf-8"), "content")
        group = CollectGroup(
            "g", (str(self.source_dir),), ("report",), str(self.target_dir)
        )
        self.assertEqual(run_collect_groups([group], self.path).count(ACTION_COPY), 0)
        self.assertEqual(
            [path.name for path in self.target_dir.iterdir()], ["report.txt"]
        )

    def test_different_target_is_preserved_and_next_copy_gets_new_name(self):
        self.target.write_text("user file", encoding="utf-8")
        preview = self.preview()
        self.assertEqual(preview.status, "preserve")
        with self.assertRaises(CollectRecoveryError):
            recover_pending_copy(self.path, preview.fingerprint, "adopt")
        recover_pending_copy(self.path, preview.fingerprint, "preserve")
        group = CollectGroup(
            "g", (str(self.source_dir),), ("report",), str(self.target_dir)
        )
        report = run_collect_groups([group], self.path)
        self.assertEqual(report.actions[0].target_name, "report [source].txt")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "user file")

    def test_file_changed_after_preview_blocks_recovery(self):
        self.target.write_text("content", encoding="utf-8")
        preview = self.preview()
        self.target.write_text("changed", encoding="utf-8")
        with self.assertRaises(CollectRecoveryError) as raised:
            recover_pending_copy(self.path, preview.fingerprint, "adopt")
        self.assertEqual(raised.exception.code, "stale")
        self.assertTrue(CollectState.load(self.path, allow_pending=True).pending)

    def test_state_changed_after_preview_blocks_recovery(self):
        preview = self.preview()
        self.state.targets["other"] = {}
        self.state.save()
        with self.assertRaises(CollectRecoveryError):
            recover_pending_copy(self.path, preview.fingerprint, "preserve")
        self.assertTrue(CollectState.load(self.path, allow_pending=True).pending)

    def test_backup_failure_does_not_clear_pending(self):
        preview = self.preview()
        real_open = Path.open

        def fail_backup(path, *args, **kwargs):
            if ".recovery-" in path.name:
                raise PermissionError("backup denied")
            return real_open(path, *args, **kwargs)

        with (
            patch.object(Path, "open", fail_backup),
            self.assertRaises(CollectRecoveryError),
        ):
            recover_pending_copy(self.path, preview.fingerprint, "preserve")
        self.assertTrue(CollectState.load(self.path, allow_pending=True).pending)

    def test_atomic_commit_failure_keeps_pending_and_backup(self):
        preview = self.preview()
        with (
            patch(
                "src.core.collect_sync.atomic_write_json", side_effect=OSError("locked")
            ),
            self.assertRaises(CollectRecoveryError),
        ):
            recover_pending_copy(self.path, preview.fingerprint, "preserve")
        self.assertTrue(CollectState.load(self.path, allow_pending=True).pending)
        self.assertEqual(len(list(self.root.glob("*.recovery-*.bak"))), 1)

    def test_cancel_does_not_write(self):
        before = self.path.read_bytes()
        with self.assertRaises(CollectRecoveryError):
            inspect_pending_copy(self.path, should_cancel=lambda: True)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_source_does_not_allow_adoption(self):
        self.target.write_text("content", encoding="utf-8")
        self.source.unlink()
        self.assertEqual(self.preview().status, "preserve")
        recover_pending_copy(self.path, self.preview().fingerprint, "preserve")
        self.assertTrue(self.target.exists())

    def test_invalid_pending_cannot_escape_target(self):
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw["pending"]["name"] = "../escape"
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(CollectRecoveryError):
            self.preview()

    def test_no_pending_including_no_state_is_not_an_error(self):
        self.state.pending = {}
        self.state.save()
        self.assertEqual(self.preview().status, "none")
        self.path.unlink()
        self.assertEqual(self.preview().status, "none")

    def test_source_unavailable_still_allows_preserve_but_not_adopt(self):
        self.target.write_text("user file", encoding="utf-8")
        real_lstat = Path.lstat

        def unavailable(path, *args, **kwargs):
            if path == self.source:
                raise OSError("share unavailable")
            return real_lstat(path, *args, **kwargs)

        with patch.object(Path, "lstat", unavailable):
            preview = self.preview()
            self.assertEqual(preview.status, "preserve")
            with self.assertRaises(CollectRecoveryError):
                recover_pending_copy(self.path, preview.fingerprint, "adopt")
            recover_pending_copy(self.path, preview.fingerprint, "preserve")
        self.assertFalse(CollectState.load(self.path).pending)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "user file")

    def test_cancel_after_backup_keeps_original_pending_state(self):
        preview = self.preview()
        cancelled = False
        real_read = Path.read_bytes

        def read(path):
            nonlocal cancelled
            value = real_read(path)
            if ".recovery-" in path.name:
                cancelled = True
            return value

        with (
            patch.object(Path, "read_bytes", read),
            self.assertRaises(CollectRecoveryError),
        ):
            recover_pending_copy(
                self.path, preview.fingerprint, "preserve", lambda: cancelled
            )
        self.assertTrue(CollectState.load(self.path, allow_pending=True).pending)

    def test_conflicting_committed_ownership_cannot_be_recovered_by_guessing(self):
        self.state.targets[str(self.target_dir)] = {str(self.source): self.target.name}
        self.state.save()
        with self.assertRaises(CollectRecoveryError):
            self.preview()

    def test_linked_target_parent_is_refused_without_writing(self):
        from src.core.collect_sync import _is_link

        before = self.path.read_bytes()

        def junction(path):
            return Path(path) == self.target_dir.parent or _is_link(path)

        with (
            patch("src.core.collect_sync._is_link", side_effect=junction),
            self.assertRaises(CollectRecoveryError),
        ):
            self.preview()
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_target_requires_explicit_metadata_release_and_backup(self):
        self.target_dir.rename(self.root / "renamed")
        before = self.path.read_bytes()
        with self.assertRaises(CollectRecoveryError):
            self.preview()
        preview = inspect_pending_release(self.path)
        self.assertEqual(preview.status, "unverified")
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(CollectRecoveryError):
            recover_pending_copy(self.path, preview.fingerprint, "adopt")
        backup = recover_pending_copy(self.path, preview.fingerprint, "release")
        self.assertEqual(backup.read_bytes(), before)
        self.assertFalse(CollectState.load(self.path).pending)
        self.assertEqual(self.source.read_text(encoding="utf-8"), "content")
        other = self.root / "healthy-target"
        other.mkdir()
        healthy = CollectGroup(
            "healthy", (str(self.source_dir),), ("report",), str(other)
        )
        self.assertEqual(run_collect_groups([healthy], self.path).count(ACTION_COPY), 1)

    def test_old_invalid_names_can_be_released_without_traversing_paths(self):
        for name in ("report" * 50, r"report [\\nas\share].txt", "../outside.txt"):
            self.state.pending["name"] = name
            self.state.save()
            with self.assertRaises(CollectRecoveryError):
                self.preview()
            with patch(
                "src.core.collect_recovery._describe",
                side_effect=AssertionError("must not inspect target"),
            ):
                preview = inspect_pending_release(self.path)
                recover_pending_copy(self.path, preview.fingerprint, "release")
            self.assertFalse(CollectState.load(self.path).pending)

    def test_metadata_release_refuses_stale_state_and_cancellation(self):
        preview = inspect_pending_release(self.path)
        self.state.targets["other"] = {}
        self.state.save()
        with self.assertRaises(CollectRecoveryError):
            recover_pending_copy(self.path, preview.fingerprint, "release")
        with self.assertRaises(CollectRecoveryError):
            inspect_pending_release(self.path, lambda: True)
        self.assertTrue(CollectState.load(self.path, allow_pending=True).pending)

    def test_metadata_release_still_rejects_corrupt_mapping_and_pending_shape(self):
        original = json.loads(self.path.read_text(encoding="utf-8"))
        invalid_values = []
        for targets in (
            {"t": []},
            {"t": {"s": "../escape"}},
            {"t": {"a": "x", "b": "X"}},
            {str(self.target_dir): {str(self.source): "owned.txt"}},
        ):
            raw = copy.deepcopy(original)
            raw["targets"] = targets
            invalid_values.append(raw)
        for key, value in (
            ("source", "relative.txt"),
            ("target", "relative"),
            ("extra", "unexpected"),
        ):
            raw = copy.deepcopy(original)
            raw["pending"][key] = value
            invalid_values.append(raw)
        for raw in invalid_values:
            with self.subTest(raw=raw):
                self.path.write_text(json.dumps(raw), encoding="utf-8")
                before = self.path.read_bytes()
                with self.assertRaises(CollectRecoveryError):
                    inspect_pending_release(self.path)
                self.assertEqual(self.path.read_bytes(), before)

    def test_metadata_release_never_accesses_source_or_target_paths(self):
        real_open, real_lstat, real_os_lstat = Path.open, Path.lstat, os.lstat

        def guard(path):
            path = Path(path)
            if any(
                path == folder or folder in path.parents
                for folder in (self.source_dir, self.target_dir)
            ):
                raise AssertionError(f"Unverified file path accessed: {path}")

        def open_path(path, *args, **kwargs):
            guard(path)
            return real_open(path, *args, **kwargs)

        def lstat(path, *args, **kwargs):
            guard(path)
            return real_lstat(path, *args, **kwargs)

        def os_lstat(path, *args, **kwargs):
            guard(path)
            return real_os_lstat(path, *args, **kwargs)

        with (
            patch.object(Path, "open", open_path),
            patch.object(Path, "lstat", lstat),
            patch("os.lstat", side_effect=os_lstat),
            patch(
                "src.core.collect_recovery.has_link_ancestor",
                side_effect=AssertionError("No path probing allowed"),
            ),
        ):
            preview = inspect_pending_release(self.path)
            backup = recover_pending_copy(self.path, preview.fingerprint, "release")
            self.assertTrue(backup.exists())
        self.assertFalse(CollectState.load(self.path).pending)

    def test_metadata_release_backup_commit_and_postbackup_cancel_fail_closed(self):
        pending = dict(self.state.pending)
        for failure in ("backup", "commit", "cancel"):
            with self.subTest(failure=failure):
                self.state.pending = dict(pending)
                self.state.save()
                preview = inspect_pending_release(self.path)
                before = self.path.read_bytes()
                real_open, real_read = Path.open, Path.read_bytes
                cancelled = {"value": False}

                def open_path(
                    path, *args, _failure=failure, _real_open=real_open, **kwargs
                ):
                    if _failure == "backup" and ".recovery-" in path.name:
                        raise PermissionError("backup denied")
                    return _real_open(path, *args, **kwargs)

                def read(
                    path, _failure=failure, _real_read=real_read, _cancelled=cancelled
                ):
                    result = _real_read(path)
                    if _failure == "cancel" and ".recovery-" in path.name:
                        _cancelled["value"] = True
                    return result

                from src.core.collect_sync import atomic_write_json

                def write(*args, _failure=failure, **kwargs):
                    if _failure == "commit":
                        raise OSError("commit denied")
                    return atomic_write_json(*args, **kwargs)

                with (
                    patch.object(Path, "open", open_path),
                    patch.object(Path, "read_bytes", read),
                    patch("src.core.collect_sync.atomic_write_json", side_effect=write),
                    self.assertRaises(CollectRecoveryError),
                ):
                    recover_pending_copy(
                        self.path,
                        preview.fingerprint,
                        "release",
                        lambda flag=cancelled: flag["value"],
                    )
                self.assertEqual(self.path.read_bytes(), before)
                self.assertTrue(
                    CollectState.load(self.path, allow_pending=True).pending
                )
