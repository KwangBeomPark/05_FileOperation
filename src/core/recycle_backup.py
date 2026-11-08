"""Prepare a Windows data-stream copy before considering recycling.

This module never deletes or recycles the source. It verifies data streams, but
does not establish full metadata or ACL recovery, crash durability, or safety of
a later Shell operation. Interrupted preparation directories are retained.
"""

import hashlib
import os
import stat
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from src.utils.atomic_write import atomic_write_json

RECOVERY_PREFIX = ".fileops-recycle-recovery-"
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class RecoveryCopy:
    """A verified data-stream copy; neither it nor its record is auto-removed."""

    directory: str
    backup_path: str
    record_path: str
    source_path: str
    sha256: str


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_identity_matches(info, expected):
    """Avoid unreliable Windows fstat ctime; path stat and content stay checked."""
    actual = _identity(info)
    expected = tuple(expected)
    return actual[:4] == expected[:4] if os.name == "nt" else actual == expected


def _check_no_links(path):
    """Reject symlinks and Windows reparse points on the entire existing path."""
    candidate = Path(path)
    for part in (candidate, *candidate.parents):
        info = os.lstat(part)
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise OSError(f"Link or reparse point is not supported: {part}")


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _enumerate_streams(path):
    """List named data streams without accepting path-like stream names."""
    import win32file

    streams = list(win32file.FindStreams(path))
    if not streams:
        raise OSError(f"Could not enumerate file streams: {path}")
    names = set()
    for _size, name in streams:
        if (not name.startswith(":") or not name.endswith(":$DATA")
                or "/" in name or "\\" in name or name in names):
            raise OSError(f"Unsupported or ambiguous file stream: {name}")
        names.add(name)
    if "::$DATA" not in names:
        raise OSError(f"Main data stream not found: {path}")
    return streams


def _stream_hashes(path):
    """Read and hash every data stream, failing if enumeration is unavailable."""
    result = {}
    for size, name in _enumerate_streams(path):
        stream_path = path if name == "::$DATA" else path + name
        result[name] = (size, _hash_file(stream_path))
    return result


def _require_local_fixed_volume(root):
    """Reject platforms and volumes not yet covered by this experiment."""
    if os.name != "nt":
        raise OSError("Recovery copy is currently supported on Windows only")
    import win32file

    drive, _ = os.path.splitdrive(root)
    if not drive or drive.startswith("\\\\"):
        raise OSError(f"Network or unsupported recovery volume: {root}")
    if win32file.GetDriveType(drive + "\\") != win32file.DRIVE_FIXED:
        raise OSError(f"Non-fixed or unsupported recovery volume: {root}")


def _check_guard_identity(handle, expected_identity):
    """Check the held Windows file handle, not just the reopened path."""
    import win32file

    info = win32file.GetFileInformationByHandle(handle)
    attributes, volume_serial, index_high, index_low = info[0], info[4], info[8], info[9]
    expected_device, expected_inode = expected_identity[:2]
    file_index = (index_high << 32) | index_low
    if (attributes & 0x400 or volume_serial != (expected_device & 0xFFFFFFFF)
            or file_index != expected_inode):
        raise OSError("Locked source handle does not match the expected file")


def prepare_recovery_copy(root, source, expected_identity, expected_sha256):
    """Create, flush and compare Windows data streams under the selected root.

    The caller must already have confirmed the source is an approved old
    version. On any failure the source is never removed, and any partial
    recovery directory remains available for diagnosis.
    """
    root = os.path.abspath(os.fspath(root))
    source = os.path.abspath(os.fspath(source))
    try:
        common = os.path.commonpath((root, source))
    except ValueError as exc:
        raise ValueError("Source is outside the selected folder") from exc
    if os.path.normcase(common) != os.path.normcase(root) or os.path.normcase(source) == os.path.normcase(root):
        raise ValueError("Source is outside the selected folder")
    relative_source = os.path.relpath(source, root)
    if any(part.casefold().startswith(RECOVERY_PREFIX.casefold()) for part in Path(relative_source).parts):
        raise ValueError("Recovery copies cannot be used as synchronization sources")
    _require_local_fixed_volume(root)
    _check_no_links(root)
    _check_no_links(source)
    info = os.stat(source, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or _identity(info) != tuple(expected_identity):
        raise OSError(f"Source changed before recovery copy: {source}")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("A SHA-256 digest is required")

    directory = tempfile.mkdtemp(prefix=RECOVERY_PREFIX, dir=root)
    record_path = os.path.join(directory, "record.json")
    backup_path = os.path.join(directory, "data.bin")
    record = {
        "version": 1,
        "state": "preparing",
        "source_relative": relative_source,
        "backup_name": "data.bin",
        "sha256": expected_sha256,
    }
    atomic_write_json(record_path, record)
    import win32con
    import win32file

    # The sharing mode denies ordinary write and rename of the main stream
    # during preparation. It is not a lock covering a future Shell operation.
    with ExitStack() as locks:
        guard = win32file.CreateFile(
            source, win32con.GENERIC_READ, win32con.FILE_SHARE_READ, None,
            win32con.OPEN_EXISTING, win32file.FILE_FLAG_OPEN_REPARSE_POINT, None,
        )
        locks.callback(guard.Close)
        _check_guard_identity(guard, expected_identity)
        _check_no_links(source)
        original_streams = _enumerate_streams(source)
        for _size, name in original_streams:
            if name == "::$DATA":
                continue
            stream_guard = win32file.CreateFile(
                source + name, win32con.GENERIC_READ, win32con.FILE_SHARE_READ, None,
                win32con.OPEN_EXISTING, win32file.FILE_FLAG_OPEN_REPARSE_POINT, None,
            )
            locks.callback(stream_guard.Close)
            _check_guard_identity(stream_guard, expected_identity)
        if sorted(_enumerate_streams(source)) != sorted(original_streams):
            raise OSError(f"Source streams changed during recovery preparation: {source}")
        with open(source, "rb") as original:
            if not _open_identity_matches(os.fstat(original.fileno()), expected_identity):
                raise OSError(f"Source changed while opening recovery copy: {source}")
            win32file.CopyFileEx(
                source, backup_path, None, Data=None, Cancel=False,
                CopyFlags=win32file.COPY_FILE_FAIL_IF_EXISTS, Transaction=None,
            )
            with open(backup_path, "r+b") as backup:
                backup.flush()
                os.fsync(backup.fileno())
            if not _open_identity_matches(os.fstat(original.fileno()), expected_identity):
                raise OSError(f"Source changed during recovery copy: {source}")
        _check_no_links(source)
        if _identity(os.stat(source, follow_symlinks=False)) != tuple(expected_identity):
            raise OSError(f"Source path changed during recovery copy: {source}")
        source_streams = _stream_hashes(source)
        backup_streams = _stream_hashes(backup_path)
        if sorted((size, name) for name, (size, _hash) in source_streams.items()) != sorted(original_streams):
            raise OSError(f"Source streams changed during recovery verification: {source}")
        _check_no_links(source)
        if _identity(os.stat(source, follow_symlinks=False)) != tuple(expected_identity):
            raise OSError(f"Source path changed while verifying recovery copy: {source}")
        if source_streams != backup_streams or source_streams["::$DATA"][1] != expected_sha256:
            raise OSError(f"Recovery copy verification failed: {source}")
    record["data_streams"] = {
        name: {"size": size, "sha256": digest}
        for name, (size, digest) in source_streams.items()
    }
    record["state"] = "data_copy_verified"
    atomic_write_json(record_path, record)
    return RecoveryCopy(directory, backup_path, record_path, source, expected_sha256)
