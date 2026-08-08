from __future__ import annotations

import ctypes
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


BACKUP_FOLDER_NAME = "Original Backup"
MANIFEST_FILENAME = ".fileops-backup.jsonl"
MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BackupEntry:
    backup_path: str
    restore_target: str
    size: int
    modified_time: float
    original_name: str = ""
    manifest_recorded: bool = False

    @property
    def file_name(self) -> str:
        return os.path.basename(self.backup_path)


@dataclass(frozen=True)
class RestoreResult:
    backup_path: str
    success: bool
    restored_path: str = ""
    error: str = ""
    warning: str = ""


def backup_directory(source_folder: str) -> str:
    return os.path.join(os.path.abspath(source_folder), BACKUP_FOLDER_NAME)


def manifest_path(backup_folder: str) -> str:
    return os.path.join(os.path.abspath(backup_folder), MANIFEST_FILENAME)


def _valid_file_name(value: object) -> bool:
    if not isinstance(value, str) or not value or value in {".", ".."} or "\0" in value:
        return False
    return os.path.basename(value) == value


def _set_hidden_on_windows(path: str) -> None:
    if os.name != "nt":
        return
    try:
        get_attributes = ctypes.windll.kernel32.GetFileAttributesW
        set_attributes = ctypes.windll.kernel32.SetFileAttributesW
        attributes = get_attributes(path)
        if attributes != -1:
            set_attributes(path, attributes | 0x2)
    except Exception:
        pass


def _append_manifest_event(backup_folder: str, event: dict) -> tuple[bool, str]:
    try:
        os.makedirs(backup_folder, exist_ok=True)
        path = manifest_path(backup_folder)
        if os.path.lexists(path) and (os.path.islink(path) or not os.path.isfile(path)):
            return False, "Backup manifest path is not a regular file."
        with open(path, "a", encoding="utf-8", newline="\n") as manifest:
            manifest.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            manifest.flush()
            os.fsync(manifest.fileno())
        _set_hidden_on_windows(path)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def record_backup_move(original_path: str, backup_path: str) -> tuple[bool, str]:
    original_name = os.path.basename(original_path)
    stored_name = os.path.basename(backup_path)
    if not _valid_file_name(original_name) or not _valid_file_name(stored_name):
        return False, "Invalid backup or original file name."
    event = {
        "schema": MANIFEST_SCHEMA_VERSION,
        "event": "backup",
        "stored_name": stored_name,
        "original_name": original_name,
        "size": os.path.getsize(backup_path) if os.path.isfile(backup_path) else None,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return _append_manifest_event(os.path.dirname(backup_path), event)


def _record_restore(backup_path: str, original_name: str) -> tuple[bool, str]:
    event = {
        "schema": MANIFEST_SCHEMA_VERSION,
        "event": "restore",
        "stored_name": os.path.basename(backup_path),
        "original_name": original_name,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return _append_manifest_event(os.path.dirname(backup_path), event)


def _load_manifest(backup_folder: str) -> dict[str, str]:
    records: dict[str, str] = {}
    path = manifest_path(backup_folder)
    if os.path.islink(path) or not os.path.isfile(path):
        return records
    try:
        with open(path, "r", encoding="utf-8") as manifest:
            for line in manifest:
                try:
                    event = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if event.get("schema") != MANIFEST_SCHEMA_VERSION:
                    continue
                stored_name = event.get("stored_name")
                original_name = event.get("original_name")
                if not _valid_file_name(stored_name) or not _valid_file_name(original_name):
                    continue
                if event.get("event") == "backup":
                    records[stored_name.casefold()] = original_name
                elif event.get("event") == "restore":
                    records.pop(stored_name.casefold(), None)
    except OSError:
        return {}
    return records


def _safe_restore_target(source_folder: str, file_name: str) -> str:
    source_folder = os.path.abspath(source_folder)
    target = os.path.join(source_folder, file_name)
    if not os.path.exists(target):
        return target

    stem, suffix = os.path.splitext(file_name)
    counter = 1
    while True:
        candidate = os.path.join(source_folder, f"{stem}_restored_{counter}{suffix}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def list_backup_entries(source_folder: str) -> list[BackupEntry]:
    if not source_folder or not os.path.isdir(source_folder):
        return []

    backup_folder = backup_directory(source_folder)
    if not os.path.isdir(backup_folder):
        return []

    manifest = _load_manifest(backup_folder)
    entries: list[BackupEntry] = []
    with os.scandir(backup_folder) as iterator:
        for item in iterator:
            if item.name.casefold() == MANIFEST_FILENAME.casefold():
                continue
            if item.is_symlink() or not item.is_file(follow_symlinks=False):
                continue
            stat = item.stat(follow_symlinks=False)
            original_name = manifest.get(item.name.casefold(), item.name)
            recorded = item.name.casefold() in manifest
            entries.append(
                BackupEntry(
                    backup_path=os.path.abspath(item.path),
                    restore_target=_safe_restore_target(source_folder, original_name),
                    size=stat.st_size,
                    modified_time=stat.st_mtime,
                    original_name=original_name,
                    manifest_recorded=recorded,
                )
            )

    return sorted(entries, key=lambda entry: (-entry.modified_time, entry.file_name.casefold()))


def _is_direct_backup_file(source_folder: str, backup_path: str) -> bool:
    expected_parent = Path(backup_directory(source_folder)).resolve(strict=False)
    candidate = Path(backup_path).resolve(strict=False)
    return candidate.parent == expected_parent


def restore_backup_files(source_folder: str, backup_paths: Iterable[str]) -> list[RestoreResult]:
    results: list[RestoreResult] = []
    source_folder = os.path.abspath(source_folder)

    if not os.path.isdir(source_folder):
        error = f"Source folder does not exist: {source_folder}"
        return [RestoreResult(str(path), False, error=error) for path in backup_paths]

    manifest = _load_manifest(backup_directory(source_folder))
    for requested_path in backup_paths:
        backup_path = os.path.abspath(requested_path)
        if not _is_direct_backup_file(source_folder, backup_path):
            results.append(RestoreResult(backup_path, False, error="File is outside the expected backup folder."))
            continue
        if os.path.islink(backup_path) or not os.path.isfile(backup_path):
            results.append(RestoreResult(backup_path, False, error="Backup file no longer exists or is not a regular file."))
            continue

        stored_name = os.path.basename(backup_path)
        original_name = manifest.get(stored_name.casefold(), stored_name)
        restore_target = _safe_restore_target(source_folder, original_name)
        try:
            shutil.move(backup_path, restore_target)
        except Exception as exc:
            results.append(RestoreResult(backup_path, False, error=str(exc)))
        else:
            recorded, warning = _record_restore(backup_path, original_name)
            results.append(
                RestoreResult(
                    backup_path,
                    True,
                    restored_path=restore_target,
                    warning="" if recorded else f"Restore history could not be updated: {warning}",
                )
            )

    return results
