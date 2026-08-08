from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BACKUP_FOLDER_NAME = "Original Backup"


@dataclass(frozen=True)
class BackupEntry:
    backup_path: str
    restore_target: str
    size: int
    modified_time: float

    @property
    def file_name(self) -> str:
        return os.path.basename(self.backup_path)


@dataclass(frozen=True)
class RestoreResult:
    backup_path: str
    success: bool
    restored_path: str = ""
    error: str = ""


def backup_directory(source_folder: str) -> str:
    return os.path.join(os.path.abspath(source_folder), BACKUP_FOLDER_NAME)


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

    entries: list[BackupEntry] = []
    with os.scandir(backup_folder) as iterator:
        for item in iterator:
            if item.is_symlink() or not item.is_file(follow_symlinks=False):
                continue
            stat = item.stat(follow_symlinks=False)
            entries.append(
                BackupEntry(
                    backup_path=os.path.abspath(item.path),
                    restore_target=_safe_restore_target(source_folder, item.name),
                    size=stat.st_size,
                    modified_time=stat.st_mtime,
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

    for requested_path in backup_paths:
        backup_path = os.path.abspath(requested_path)
        if not _is_direct_backup_file(source_folder, backup_path):
            results.append(RestoreResult(backup_path, False, error="File is outside the expected backup folder."))
            continue
        if os.path.islink(backup_path) or not os.path.isfile(backup_path):
            results.append(RestoreResult(backup_path, False, error="Backup file no longer exists or is not a regular file."))
            continue

        restore_target = _safe_restore_target(source_folder, os.path.basename(backup_path))
        try:
            shutil.move(backup_path, restore_target)
        except Exception as exc:
            results.append(RestoreResult(backup_path, False, error=str(exc)))
        else:
            results.append(RestoreResult(backup_path, True, restored_path=restore_target))

    return results
