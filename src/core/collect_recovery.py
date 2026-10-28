"""Explicit pending-copy recovery; never change source or target file bytes."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from src.core.collect_sync import (
    CollectState,
    CollectStateError,
    _norm,
    has_link_ancestor,
)
from src.utils.logger import get_logger

logger = get_logger()


class CollectRecoveryError(RuntimeError):
    """A recovery cannot be completed without guessing about state or files."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RecoveryPreview:
    status: str
    source: str = ""
    target: str = ""
    fingerprint: str = ""


def _cancel_if_requested(should_cancel):
    if should_cancel and should_cancel():
        raise CollectRecoveryError("cancelled")


def _read_state(path: Path, *, metadata_only=False):
    before = path.read_bytes()
    state = CollectState.load(
        path, allow_pending=True, allow_invalid_pending_name=metadata_only
    )
    if path.read_bytes() != before:
        raise CollectRecoveryError("stale")
    return state, before


def _check_parents(path: Path):
    """Never traverse a symbolic link/junction in a recovery path."""
    if has_link_ancestor(path.parent):
        raise CollectRecoveryError("unavailable")


def inspect_pending_release(state_path: Path, should_cancel=None) -> RecoveryPreview:
    """Inspect only metadata; this never follows an unverified source/target path."""
    _cancel_if_requested(should_cancel)
    try:
        state, raw = _read_state(Path(state_path), metadata_only=True)
        if not state.pending:
            return RecoveryPreview("none")
        return RecoveryPreview(
            "unverified",
            state.pending["source"],
            state.pending["target"] + " / " + state.pending["name"],
            hashlib.sha256(b"explicit-pending-release\0" + raw).hexdigest(),
        )
    except (OSError, CollectStateError) as exc:
        raise CollectRecoveryError("unavailable") from exc


def _identity(info):
    """Track changes during a read without treating metadata as proof of ownership."""
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _describe(path: Path, should_cancel):
    _cancel_if_requested(should_cancel)
    _check_parents(path)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}
    if path.is_symlink() or path.is_junction():
        return {"kind": "link"}
    if not stat.S_ISREG(before.st_mode):
        return {"kind": "other"}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            _cancel_if_requested(should_cancel)
            digest.update(chunk)
    after = path.lstat()
    if _identity(before) != _identity(after) or path.is_symlink() or path.is_junction():
        raise CollectRecoveryError("stale")
    return {"kind": "file", "identity": _identity(after), "hash": digest.hexdigest()}


def inspect_pending_copy(state_path: Path, should_cancel=None) -> RecoveryPreview:
    """Read-only check; matching bytes never grant ownership automatically."""
    try:
        _cancel_if_requested(should_cancel)
        try:
            state, raw = _read_state(Path(state_path))
        except FileNotFoundError:
            return RecoveryPreview("none")
        if not state.pending:
            return RecoveryPreview("none")
        pending = state.pending
        root = Path(pending["target"])
        _check_parents(root)
        root_stat = root.lstat()
        if (
            root.is_symlink()
            or root.is_junction()
            or not stat.S_ISDIR(root_stat.st_mode)
        ):
            raise CollectRecoveryError("unavailable")
        source = Path(pending["source"])
        target = root / pending["name"]
        try:
            source_info = _describe(source, should_cancel)
        except OSError:
            logger.warning(
                "Recovery source unavailable; only preserve is possible: %s", source
            )
            source_info = {"kind": "unavailable"}
        except CollectRecoveryError as exc:
            if exc.code != "unavailable":
                raise
            source_info = {"kind": "unavailable"}
        target_info = _describe(target, should_cancel)
        matching = (
            source_info["kind"] == target_info["kind"] == "file"
            and source_info["hash"] == target_info["hash"]
        )
        status = (
            "missing"
            if target_info["kind"] == "missing"
            else "matching"
            if matching
            else "preserve"
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "state": hashlib.sha256(raw).hexdigest(),
                    "source": source_info,
                    "target": target_info,
                    "root": (root_stat.st_dev, root_stat.st_ino),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return RecoveryPreview(status, str(source), str(target), fingerprint)
    except (OSError, CollectStateError) as exc:
        logger.exception("Cannot inspect pending collection")
        raise CollectRecoveryError("unavailable") from exc


def recover_pending_copy(
    state_path: Path, fingerprint: str, decision: str, should_cancel=None
) -> Path:
    """Back up state then clear a pending copy only after an explicit fresh decision.

    preserve: leave all target files unowned and untouched; future scans reserve
    any existing names. adopt: user explicitly confirms this matching target is
    their collected copy. No automatic adoption, deletion or file rollback.
    release: explicitly clear only an unverified pending record after backup,
    without inspecting source/target paths; never an automatic retry decision.
    """
    if decision not in ("preserve", "adopt", "release"):
        raise CollectRecoveryError("invalid")
    path = Path(state_path)
    inspect = inspect_pending_release if decision == "release" else inspect_pending_copy
    preview = inspect(path, should_cancel)
    if (
        preview.status == "none"
        or not fingerprint
        or preview.fingerprint != fingerprint
    ):
        raise CollectRecoveryError("stale")
    if decision == "adopt" and preview.status != "matching":
        raise CollectRecoveryError("invalid")
    try:
        state, raw = _read_state(path, metadata_only=decision == "release")
        # A second full check covers file changes while the dialog was open.
        if inspect(path, should_cancel).fingerprint != fingerprint:
            raise CollectRecoveryError("stale")
        backup = path.with_name(f"{path.name}.recovery-{uuid.uuid4().hex}.bak")
        _cancel_if_requested(should_cancel)
        with backup.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if backup.read_bytes() != raw or path.read_bytes() != raw:
            raise CollectRecoveryError("stale")
        _cancel_if_requested(should_cancel)
        if decision == "adopt":
            state.record(
                _norm(state.pending["target"]),
                _norm(state.pending["source"]),
                state.pending["name"],
            )
        state.pending = {}
        state.save()
        logger.info(
            "Pending collection recovered: decision=%s backup=%s", decision, backup
        )
        return backup
    except (OSError, CollectStateError) as exc:
        logger.exception(
            "Pending collection recovery failed; no file ownership guessed"
        )
        raise CollectRecoveryError("unavailable") from exc
