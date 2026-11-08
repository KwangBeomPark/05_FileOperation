"""Classify Windows Shell evidence without moving or deleting files.

This module alone does not make recycling safe: callers must separately protect
the original data, enforce their path policy, and handle interrupted operations.
"""

import os
from dataclasses import dataclass
from enum import Enum


class RecycleOutcome(Enum):
    """What can be inferred from a single Shell operation."""

    SHELL_CONFIRMED_RECYCLE = "shell_confirmed_recycle"
    SOURCE_PATH_PRESENT = "source_path_present"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class DeleteCallback:
    """The Shell's per-item result, captured without storing COM objects."""

    source_path: str
    hresult: int
    has_recycle_item: bool


@dataclass(frozen=True)
class RecycleEvidence:
    """Evidence available after a single attempted Shell operation."""

    source_path: str
    callbacks: tuple[DeleteCallback, ...]
    operation_failed: bool
    operation_aborted: bool
    source_exists: bool | None


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def inspect_source_presence(path: str) -> bool | None:
    """Return unknown rather than absent when access to the path fails."""
    if not path:
        return None
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return None
    return True


def classify_recycle_evidence(evidence: RecycleEvidence) -> RecycleOutcome:
    """Classify Shell evidence without asserting file-content integrity.

    A successful HRESULT is not necessarily zero. This conservatively accepts
    S_OK and the success code observed during the local synthetic-file test.
    A missing, duplicate or unexpected callback is never treated as confirmation.
    """
    if not evidence.source_path:
        return RecycleOutcome.UNCERTAIN
    callback_ok = False
    if len(evidence.callbacks) == 1:
        callback = evidence.callbacks[0]
        callback_ok = bool(
            callback.source_path
            and _path_key(callback.source_path) == _path_key(evidence.source_path)
            and (int(callback.hresult) & 0xFFFFFFFF) in (0, 0x00270008)
            and callback.has_recycle_item
        )
    if (
        callback_ok
        and not evidence.operation_failed
        and not evidence.operation_aborted
        and evidence.source_exists is False
    ):
        return RecycleOutcome.SHELL_CONFIRMED_RECYCLE
    if evidence.source_exists is True:
        # Existence alone does not prove the original file is unchanged.
        return RecycleOutcome.SOURCE_PATH_PRESENT
    return RecycleOutcome.UNCERTAIN
