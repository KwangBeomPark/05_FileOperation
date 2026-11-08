"""Conservative opt-in synchronization of date-suffixed file families."""

import hashlib
import os
import re
import shutil
import stat
import tempfile
from datetime import date
from pathlib import Path

_DATE = re.compile(r"^(.*?)[_-]?[vV]([0-9]{8})$")


def _family(name):
    stem, ext = os.path.splitext(name)
    match = _DATE.fullmatch(stem)
    if not match or not match.group(1).rstrip("_-"):
        return None
    try:
        value = match.group(2)
        date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError:
        return None
    return match.group(1).rstrip("_-").casefold(), ext.casefold(), match.group(2)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _unsafe(path):
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _check_path(root, path):
    root, path = os.path.abspath(root), os.path.abspath(path)
    if os.path.commonpath([root, path]) != root:
        raise OSError(f"Path outside root: {path}")
    for ancestor in (Path(root), *Path(root).parents):
        if _unsafe(ancestor):
            raise OSError(f"Link or reparse point: {ancestor}")
    current = root
    for part in os.path.relpath(path, root).split(os.sep):
        if part == ".":
            continue
        current = os.path.join(current, part)
        try:
            unsafe = _unsafe(current)
        except FileNotFoundError:
            continue
        if unsafe:
            raise OSError(f"Link or reparse point: {current}")


def _validate_archive(manager):
    name = manager.date_archive_name
    stem = name.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if (not name or name in (".", "..") or name[0] in ". " or name[-1] in ". " or
            any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name) or stem in reserved):
        raise OSError(f"Invalid archive folder name: {name!r}")
    for folder in manager.folders:
        archive = os.path.join(folder, name)
        try:
            os.lstat(archive)
        except FileNotFoundError:
            continue
        else:
            _check_path(folder, archive)
            matches = [entry for entry in os.listdir(folder) if os.path.samefile(os.path.join(folder, entry), archive)]
            if len(matches) != 1 or matches[0].casefold() != name.casefold():
                raise OSError(f"Archive folder alias is ambiguous: {archive}")


def _digest(path):
    before = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or _unsafe(path):
        raise OSError(f"Not a regular file: {path}")
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = os.stat(path, follow_symlinks=False)
    if _identity(before) != _identity(after):
        raise OSError(f"File changed while reading: {path}")
    return _identity(after), digest.hexdigest()


def _scan(manager):
    groups = {}
    _validate_archive(manager)
    if len(manager.folders) < 2 or len(set(map(os.path.normcase, manager.folders))) != len(manager.folders):
        raise OSError("At least two distinct folders are required")
    roots = [os.path.realpath(p) for p in manager.folders]
    for i, root in enumerate(roots):
        for other in roots[i + 1:]:
            try:
                common = os.path.commonpath([root, other])
            except ValueError:  # Different Windows drives are independent.
                continue
            if os.path.normcase(common) in (os.path.normcase(root), os.path.normcase(other)):
                raise OSError("Overlapping folders are not supported")
    for folder in manager.folders:
        if manager.is_cancelled:
            raise OSError("Synchronization cancelled")
        if not os.path.isdir(folder):
            raise OSError(f"Folder unavailable: {folder}")
        _check_path(folder, folder)
        def onerror(error):
            raise error
        for root, dirs, files in os.walk(folder, onerror=onerror, followlinks=False):
            if manager.is_cancelled:
                raise OSError("Synchronization cancelled")
            _check_path(folder, root)
            if manager.observe_scan:
                manager._observe_path(root)
            dirs[:] = [d for d in dirs if d.casefold() not in {"to be deleted", manager.archive_folder_name.casefold()} and not manager.is_excluded(os.path.relpath(os.path.join(root, d), folder))]
            for directory in dirs:
                _check_path(folder, os.path.join(root, directory))
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), folder)
                if manager.is_excluded(rel):
                    continue
                parsed = _family(name)
                if not parsed:
                    continue
                path = os.path.join(folder, rel)
                _check_path(folder, path)
                identity, digest = _digest(path)
                if manager.observe_scan:
                    manager._observe_path(path)
                key = (os.path.dirname(rel).casefold(), parsed[0], parsed[1])
                groups.setdefault(key, []).append({"folder": folder, "filename": rel, "date": parsed[2], "identity": identity, "digest": digest})
            if not manager.include_subfolders:
                break
    return groups


def analyze_date_sync(manager):
    manager.is_cancelled = False
    manager.scan_errors.clear()
    manager.scan_observations.clear()
    try:
        groups = _scan(manager)
        actions = []
        for key, entries in groups.items():
            candidates = [e for e in entries if manager.sync_mode != "one_way" or e["folder"] == manager.folders[0]]
            if not candidates:
                continue
            date = max(e["date"] for e in candidates)
            # Any conflicting same-date copies block the entire family.
            top = [e for e in entries if e["date"] == date]
            if _has_conflicts(entries):
                actions.append({"action": "날짜 보류", "filename": top[0]["filename"], "source_folder": top[0]["folder"], "target_folder": top[0]["folder"], "reason": "Conflicting content for the same date"})
                continue
            source = next(e for e in candidates if e["date"] == date)
            targets = manager.folders[1:] if manager.sync_mode == "one_way" else manager.folders
            for target in targets:
                local = [e for e in entries if e["folder"] == target]
                if any(e["date"] > date for e in local):
                    actions.append({"action": "날짜 보류", "filename": source["filename"], "source_folder": source["folder"], "target_folder": target, "reason": "Target has a newer date"})
                    continue
                old = [e for e in local if e["date"] < date]
                existing = next((e for e in local if e["date"] == date), None)
                if not existing or old:
                    actions.append({"action": "날짜 동기화", "filename": source["filename"], "source_folder": source["folder"], "target_folder": target, "source": source, "existing": existing, "old": old, "key": key, "local": local})
        return actions
    except (OSError, ValueError) as error:
        manager.scan_errors.append(error)
        return [{"action": "오류", "filename": "", "source_folder": manager.folders[0] if manager.folders else "", "target_folder": manager.folders[0] if manager.folders else "", "reason": str(error)}]


def _exclusive_move(source, target):
    if os.name == "nt":
        os.rename(source, target)
    else:
        os.link(source, target)
        os.unlink(source)


def _recycle_old_file(path: str) -> None:
    """Fail closed until recycle semantics can be verified for the destination."""
    raise OSError(f"Recycle Bin operation disabled: recoverability is not verified: {path}")


def _verify(root, entry):
    path = os.path.join(root, entry["filename"])
    _check_path(root, path)
    if _digest(path) != (entry["identity"], entry["digest"]):
        raise OSError(f"File changed since scan: {path}")
    return path


def _scan_family(manager, action):
    """Recheck names in the relevant directory and hash only this family."""
    result = []
    rel_dir = os.path.dirname(action["filename"])
    for folder in manager.folders:
        directory = os.path.join(folder, rel_dir)
        _check_path(folder, directory)
        if not os.path.isdir(directory):
            if not os.path.isdir(folder):
                raise OSError(f"Folder unavailable: {folder}")
            continue
        for name in os.listdir(directory):
            rel = os.path.join(rel_dir, name) if rel_dir else name
            parsed = _family(name)
            if not parsed or manager.is_excluded(rel):
                continue
            key = (os.path.dirname(rel).casefold(), parsed[0], parsed[1])
            if key != action["key"]:
                continue
            path = os.path.join(folder, rel)
            _check_path(folder, path)
            identity, digest = _digest(path)
            result.append({"folder": folder, "filename": rel, "date": parsed[2], "identity": identity, "digest": digest})
    return result


def _has_conflicts(entries):
    signatures = {}
    for entry in entries:
        signatures.setdefault(entry["date"], set()).add((entry["identity"][2], entry["digest"]))
    return any(len(values) > 1 for values in signatures.values())


def _revalidate(manager, action, expected_local):
    _validate_archive(manager)
    current = _scan_family(manager, action)
    local = [entry for entry in current if entry["folder"] == action["target_folder"]]
    def normalized(entries):
        return sorted((os.path.normcase(entry["filename"]), entry["date"], entry["identity"], entry["digest"]) for entry in entries)
    if normalized(local) != normalized(expected_local):
        raise OSError("Target family changed since preview")
    if _has_conflicts(current):
        raise OSError("Same date now has conflicting content")
    selected = action["source"]["date"]
    if manager.sync_mode == "two_way" and any(entry["date"] > selected for entry in current):
        raise OSError("A newer date appeared since preview")
    if manager.sync_mode == "one_way" and any(entry["folder"] == manager.folders[0] and entry["date"] > selected for entry in current):
        raise OSError("A newer source date appeared since preview")
    _verify(action["source_folder"], action["source"])


def execute_date_sync(manager, actions, progress_callback=None):
    from src.core.sync_manager import SyncResult, check_approved_sync_action
    if getattr(manager, "date_archive_mode", "folder") == "trash" and any(
        action.get("action") == "날짜 동기화" and action.get("old") for action in actions
    ):
        errors = []
        held = []
        for action in actions:
            if action.get("action") == "날짜 보류":
                reason = action.get("reason", "Date family held")
                prefix = f"{action['filename']}: " if action.get("filename") else ""
                held.append(f"{prefix}{reason}")
            elif action.get("action") == "날짜 동기화":
                prefix = f"{action['filename']}: " if action.get("filename") else ""
                errors.append(f"{prefix}Recycle Bin operation disabled: recoverability is not verified; this group was not changed.")
            else:
                reason = action.get("reason", "Unsupported date action")
                prefix = f"{action['filename']}: " if action.get("filename") else ""
                errors.append(f"{prefix}{reason}")
        return SyncResult(fail=len(errors), errors=errors, held=held)
    success, failures, errors, held = 0, 0, [], []
    for index, action in enumerate(actions):
        if not manager.is_cancelled and progress_callback:
            progress_callback(index, len(actions), action.get("filename", ""))
        if manager.is_cancelled and action.get("action") == "날짜 동기화":
            prefix = f"{action['filename']}: " if action.get("filename") else ""
            errors.append(f"{prefix}Synchronization cancelled; action not completed")
            failures += 1
            continue
        if action["action"] != "날짜 동기화":
            if action["action"] == "날짜 보류":
                reason = action.get("reason", "Date family held")
                prefix = f"{action['filename']}: " if action.get("filename") else ""
                held.append(f"{prefix}{reason}")
            else:
                reason = action.get("reason", "Unsupported date action")
                prefix = f"{action['filename']}: " if action.get("filename") else ""
                errors.append(f"{prefix}{reason}")
                failures += 1
            continue
        temp = None
        try:
            # Re-scan before each target so additions and changed files cannot be overlooked.
            expected_local = list(action["local"])
            _revalidate(manager, action, expected_local)
            source = _verify(action["source_folder"], action["source"])
            target_root = action["target_folder"]
            group_name = getattr(manager, "group_name", "")

            if action["existing"]:
                final = _verify(target_root, action["existing"])
            else:
                # Approved actions verification for the copy step
                if getattr(manager, "approved_actions", None) is not None:
                    final_dest = os.path.join(target_root, action["filename"])
                    if not check_approved_sync_action(
                        manager.approved_actions,
                        "copy",
                        source,
                        final_dest,
                        group_name=group_name,
                    ):
                        raise OSError(f"Unapproved copy action blocked: {final_dest}")

                final = os.path.join(target_root, action["filename"])
                _check_path(target_root, final)
                os.makedirs(os.path.dirname(final), exist_ok=True)
                _check_path(target_root, final)
                fd, temp = tempfile.mkstemp(prefix=".fileops-date-", suffix=".tmp", dir=os.path.dirname(final))
                with os.fdopen(fd, "wb") as output, open(source, "rb") as input_file:
                    shutil.copyfileobj(input_file, output)
                    output.flush()
                    os.fsync(output.fileno())
                _verify(action["source_folder"], action["source"])
                if _digest(temp)[1] != action["source"]["digest"]:
                    raise OSError("Copied file failed verification")
                if manager.is_cancelled:
                    raise OSError("Synchronization cancelled")
                _revalidate(manager, action, expected_local)
                _exclusive_move(temp, final)
                temp = None
                identity, digest = _digest(final)
                expected_local.append({"folder": target_root, "filename": action["filename"], "date": action["source"]["date"], "identity": identity, "digest": digest})
            if _digest(final)[1] != action["source"]["digest"]:
                raise OSError("Installed file failed verification")
            for old in action["old"]:
                if manager.is_cancelled:
                    raise OSError("Synchronization cancelled")
                _revalidate(manager, action, expected_local)
                old_path = _verify(target_root, old)
                if _digest(final)[1] != action["source"]["digest"]:
                    raise OSError("Installed file changed before archive")

                archive_mode = getattr(manager, "date_archive_mode", "folder")
                # Approved actions verification for the old version handling
                if getattr(manager, "approved_actions", None) is not None:
                    action_type = "trash" if archive_mode == "trash" else "archive"
                    check_target = None if archive_mode == "trash" else os.path.join(target_root, manager.archive_folder_name, os.path.dirname(old["filename"]))
                    if not check_approved_sync_action(
                        manager.approved_actions,
                        action_type,
                        old_path,
                        check_target,
                        group_name=group_name,
                    ):
                        raise OSError(f"Unapproved {action_type} action blocked: {old_path}")

                if archive_mode == "trash":
                    _recycle_old_file(old_path)
                else:
                    archive_dir = os.path.join(target_root, manager.archive_folder_name, os.path.dirname(old["filename"]))
                    _check_path(target_root, archive_dir)
                    os.makedirs(archive_dir, exist_ok=True)
                    _check_path(target_root, archive_dir)
                    archive = manager.get_unique_deleted_path(target_root, old["filename"])
                    _check_path(target_root, archive)
                    _exclusive_move(old_path, archive)
                expected_local.remove(old)
            success += 1
        except (OSError, ValueError) as error:
            errors.append(f"{action['filename']}: {error}")
            failures += 1
        finally:
            if temp and os.path.exists(temp):
                try:
                    os.unlink(temp)
                except OSError as error:
                    errors.append(f"Temporary file cleanup failed: {temp}: {error}")
    return SyncResult(success, failures, errors, held=held)
