"""Recovery-copy checks using disposable folders only; no Shell calls."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.recycle_backup import RECOVERY_PREFIX, _identity, prepare_recovery_copy


@unittest.skipUnless(os.name == "nt", "Windows Shell recovery experiment")
class RecoveryCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fileops-recovery-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()
        self.source = self.root / "old version.txt"
        self.data = b"example old version"
        self.source.write_bytes(self.data)
        self.identity = _identity(self.source.stat())
        self.digest = hashlib.sha256(self.data).hexdigest()

    def test_verified_copy_and_record_keep_source_untouched(self):
        copy = prepare_recovery_copy(self.root, self.source, self.identity, self.digest)
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(Path(copy.backup_path).read_bytes(), self.data)
        record = json.loads(Path(copy.record_path).read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "data_copy_verified")
        self.assertEqual(record["source_relative"], self.source.name)
        self.assertEqual(record["sha256"], self.digest)
        self.assertEqual(record["data_streams"]["::$DATA"]["sha256"], self.digest)
        self.assertTrue(Path(copy.directory).name.startswith(RECOVERY_PREFIX))

    def test_changed_source_is_rejected_before_creating_backup(self):
        self.source.write_bytes(b"changed source contents")
        with self.assertRaises(OSError):
            prepare_recovery_copy(self.root, self.source, self.identity, self.digest)
        self.assertEqual(self.source.read_bytes(), b"changed source contents")
        self.assertFalse(list(self.root.glob(f"{RECOVERY_PREFIX}*")))

    def test_wrong_hash_cannot_produce_ready_record(self):
        with self.assertRaises(OSError):
            prepare_recovery_copy(self.root, self.source, self.identity, "0" * 64)
        self.assertEqual(self.source.read_bytes(), self.data)
        record = next(self.root.glob(f"{RECOVERY_PREFIX}*/record.json"))
        self.assertEqual(json.loads(record.read_text(encoding="utf-8"))["state"], "preparing")

    def test_record_write_failure_never_removes_source(self):
        with (patch("src.core.recycle_backup.atomic_write_json", side_effect=OSError("disk full")),
              self.assertRaises(OSError)):
            prepare_recovery_copy(self.root, self.source, self.identity, self.digest)
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_source_outside_selected_root_is_rejected(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_bytes(b"outside")
        with self.assertRaises(ValueError):
            prepare_recovery_copy(self.root, outside, _identity(outside.stat()), hashlib.sha256(b"outside").hexdigest())
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_recovery_directory_is_not_accepted_as_a_source(self):
        recovery = self.root / f"{RECOVERY_PREFIX}existing"
        recovery.mkdir()
        source = recovery / "data.bin"
        source.write_bytes(b"protected")
        with self.assertRaises(ValueError):
            prepare_recovery_copy(self.root, source, _identity(source.stat()), hashlib.sha256(b"protected").hexdigest())
        self.assertEqual(source.read_bytes(), b"protected")

    def test_alternate_data_stream_is_copied_and_verified(self):
        try:
            with open(str(self.source) + ":fileops-test", "wb") as stream:
                stream.write(b"alternate stream contents")
        except OSError as exc:
            self.skipTest(f"Test volume does not support alternate streams: {exc}")
        identity = _identity(self.source.stat())
        copy = prepare_recovery_copy(self.root, self.source, identity, self.digest)
        with open(copy.backup_path + ":fileops-test", "rb") as stream:
            self.assertEqual(stream.read(), b"alternate stream contents")
        record = json.loads(Path(copy.record_path).read_text(encoding="utf-8"))
        self.assertEqual(record["data_streams"][":fileops-test:$DATA"]["sha256"],
                         hashlib.sha256(b"alternate stream contents").hexdigest())

    def test_nonfixed_volume_is_rejected_without_copy(self):
        import win32file

        with (patch.object(win32file, "GetDriveType", return_value=win32file.DRIVE_REMOTE),
              self.assertRaises(OSError)):
            prepare_recovery_copy(self.root, self.source, self.identity, self.digest)
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertFalse(list(self.root.glob(f"{RECOVERY_PREFIX}*")))

    def test_write_attempt_during_copy_is_blocked(self):
        real_fsync = os.fsync
        sync_count = 0
        blocked = []

        def modify_source(fd):
            nonlocal sync_count
            real_fsync(fd)
            sync_count += 1
            if sync_count == 2:  # First flush is the preparing record.
                try:
                    self.source.write_bytes(b"changed while copying")
                except PermissionError:
                    blocked.append(True)

        with patch("src.core.recycle_backup.os.fsync", side_effect=modify_source):
            copy = prepare_recovery_copy(self.root, self.source, self.identity, self.digest)
        self.assertEqual(blocked, [True])
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(Path(copy.backup_path).read_bytes(), self.data)

    def test_existing_alternate_stream_is_locked_during_copy(self):
        with open(str(self.source) + ":fileops-test", "wb") as stream:
            stream.write(b"original stream")
        identity = _identity(self.source.stat())
        real_fsync = os.fsync
        sync_count = 0
        blocked = []

        def modify_stream(fd):
            nonlocal sync_count
            real_fsync(fd)
            sync_count += 1
            if sync_count == 2:
                try:
                    with open(str(self.source) + ":fileops-test", "wb") as stream:
                        stream.write(b"changed stream")
                except PermissionError:
                    blocked.append(True)

        with patch("src.core.recycle_backup.os.fsync", side_effect=modify_stream):
            copy = prepare_recovery_copy(self.root, self.source, identity, self.digest)
        self.assertEqual(blocked, [True])
        with open(copy.backup_path + ":fileops-test", "rb") as stream:
            self.assertEqual(stream.read(), b"original stream")

    def test_new_alternate_stream_during_copy_prevents_confirmation(self):
        real_fsync = os.fsync
        sync_count = 0

        def add_stream(fd):
            nonlocal sync_count
            real_fsync(fd)
            sync_count += 1
            if sync_count == 2:
                with open(str(self.source) + ":fileops-new", "wb") as stream:
                    stream.write(b"new stream")

        with (patch("src.core.recycle_backup.os.fsync", side_effect=add_stream),
              self.assertRaises(OSError)):
            prepare_recovery_copy(self.root, self.source, self.identity, self.digest)
        self.assertEqual(self.source.read_bytes(), self.data)
        with open(str(self.source) + ":fileops-new", "rb") as stream:
            self.assertEqual(stream.read(), b"new stream")

    def test_cannot_lock_source_means_no_recycle_or_source_change(self):
        import win32file

        with (patch.object(win32file, "CreateFile", side_effect=OSError("locked")),
              self.assertRaises(OSError)):
            prepare_recovery_copy(self.root, self.source, self.identity, self.digest)
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_wrong_locked_handle_is_rejected(self):
        import win32file

        real_info = win32file.GetFileInformationByHandle

        def wrong_info(handle):
            info = list(real_info(handle))
            info[9] ^= 1
            return tuple(info)

        with (patch.object(win32file, "GetFileInformationByHandle", side_effect=wrong_info),
              self.assertRaises(OSError)):
            prepare_recovery_copy(self.root, self.source, self.identity, self.digest)
        self.assertEqual(self.source.read_bytes(), self.data)
