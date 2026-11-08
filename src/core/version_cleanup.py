"""Explicit, manual cleanup of older date-stamped files; independent of sync."""

import ctypes
import hashlib
import os
import re
import stat
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

from src.core.date_sync import (
    _check_path,
    _exclusive_move,
    _has_conflicts,
    _identity,
    _unsafe,
    _validate_archive,
)
from src.core.recycle_direct import _require_internal_physical_volume, recycle_file

_VERSION = re.compile(r'^(.*?)[_-]?[vV]([0-9]{8}|[0-9]+(?:\.[0-9]+)+)$')


class _Cancelled(OSError):
    pass


def _check_cancel(cancel_callback):
    if cancel_callback and cancel_callback():
        raise _Cancelled('Cancelled')


def _digest_cancellable(path, cancel_callback):
    _check_cancel(cancel_callback)
    before = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or _unsafe(path):
        raise OSError(f'Not a regular file: {path}')
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OSError(f'File replaced before reading: {path}')
        while True:
            _check_cancel(cancel_callback)
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        closed = os.fstat(stream.fileno())
        if _identity(opened) != _identity(closed):
            raise OSError(f'Open file changed while reading: {path}')
    _check_cancel(cancel_callback)
    after = os.stat(path, follow_symlinks=False)
    if (_identity(before) != _identity(after) or
            (closed.st_dev, closed.st_ino) != (after.st_dev, after.st_ino)):
        raise OSError(f'File changed while reading: {path}')
    return _identity(after), digest.hexdigest()


@contextmanager
def _lock_versions(latest, selected):
    """Windows sharing locks reduce, but cannot eliminate, path replacement races."""
    if os.name != 'nt':
        raise OSError('Version cleanup requires Windows file-sharing protection')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handles = []
    try:
        for path, sharing in ((latest, 1), (selected, 1 | 4)):
            handle = create(path, 0x80000000, sharing, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
        yield
    finally:
        for handle in reversed(handles):
            close(handle)


def _parse_version(name):
    stem, ext = os.path.splitext(name)
    match = _VERSION.fullmatch(stem)
    if not match or not match.group(1).rstrip('_-'):
        return None
    family = (match.group(1).rstrip('_-').casefold(), ext.casefold())
    value = match.group(2)
    # A suffix such as .3 in an extensionless item_v1.2.3 is not
    # distinguishable from an extension. Require a nonnumeric extension for
    # dotted versions; numeric extensions fail closed rather than guessing.
    if '.' in value and not any(char.isalpha() for char in ext[1:]):
        return None
    if '.' not in value:
        try:
            date(int(value[:4]), int(value[4:6]), int(value[6:]))
        except ValueError:
            return family, 'invalid_date', value, ()
        return family, 'date', value, (int(value),)
    parts = tuple(int(part) for part in value.split('.'))
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return family, 'numeric', value, parts


def _snapshot(directory, family, cancel_callback=None):
    entries = []
    for name in os.listdir(directory):
        parsed = _parse_version(name)
        if not parsed or parsed[0] != family:
            continue
        path = os.path.join(directory, name)
        _check_path(directory, path)
        identity, digest = _digest_cancellable(path, cancel_callback)
        entries.append({'filename': name, 'date': parsed[2], 'version_type': parsed[1],
                        'version_key': parsed[3], 'identity': identity, 'digest': digest})
    return sorted(entries, key=lambda e: (e['filename'].casefold(), e['filename']))


def _validate_versions(entries, directory):
    kinds = {entry['version_type'] for entry in entries}
    if 'invalid_date' in kinds or len(kinds) != 1:
        raise OSError(f'Invalid or mixed version formats: {directory}')
    keys = [entry['version_key'] for entry in entries]
    if len(keys) != len(set(keys)):
        raise OSError(f'Equivalent version names require review: {directory}')


def _archive_destination(root, path, name):
    directory = os.path.dirname(path)
    _validate_archive(SimpleNamespace(date_archive_name=name, folders=[directory]))
    archive = os.path.join(directory, name)
    _check_path(root, archive)
    if os.path.lexists(archive) and not os.path.isdir(archive):
        raise OSError(f'Archive path is not a directory: {archive}')
    destination = os.path.join(archive, os.path.basename(path))
    _check_path(root, destination)
    if os.path.lexists(destination):
        raise OSError(f'Archive destination already exists: {destination}')
    return archive, destination


def scan_version_cleanup(folders, include_subfolders=False, cancel_callback=None, progress_callback=None,
                         archive_folder_name='Old Versions'):
    roots = [os.path.abspath(os.fspath(folder)) for folder in folders]
    if not roots:
        raise ValueError('Select at least one folder')
    for i, root in enumerate(roots):
        if not os.path.isdir(root):
            raise OSError(f'Folder unavailable: {root}')
        _check_path(root, root)
        for other in roots[:i]:
            try:
                common = os.path.normcase(os.path.commonpath([root, other]))
            except ValueError:
                continue
            if common in (os.path.normcase(root), os.path.normcase(other)):
                raise OSError('Duplicate or overlapping folders are not supported')
    candidates = []
    for root in roots:
        def onerror(error):
            raise error
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            if cancel_callback and cancel_callback():
                raise OSError('Scan cancelled')
            _check_path(root, directory)
            if progress_callback:
                progress_callback(directory)
            excluded = {'to be deleted', archive_folder_name.casefold()}
            dirs[:] = [name for name in dirs if name.casefold() not in excluded]
            for name in dirs:
                _check_path(root, os.path.join(directory, name))
            families = set()
            for name in files:
                parsed = _parse_version(name)
                if parsed:
                    families.add(parsed[0])
            for family in sorted(families):
                snapshot = _snapshot(directory, family, cancel_callback)
                _validate_versions(snapshot, directory)
                if _has_conflicts(snapshot):
                    raise OSError(f'Conflicting same-date files: {directory} / {family[0]}')
                latest_entry = max(snapshot, key=lambda entry: entry['version_key'])
                latest = latest_entry['date']
                for entry in snapshot:
                    if entry['version_key'] < latest_entry['version_key']:
                        path = os.path.join(directory, entry['filename'])
                        candidates.append({'path': path, 'folder': root,
                                           'filename': os.path.relpath(path, root),
                                           'date': entry['date'], 'latest_date': latest,
                                           'version_type': entry['version_type'],
                                           'family': family, 'family_snapshot': snapshot})
            if not include_subfolders:
                break
    return candidates


def execute_version_cleanup(candidates, method='trash', archive_folder_name='Old Versions',
                            cancel_callback=None, progress_callback=None):
    candidates = list(candidates)
    result = {'success': 0, 'fail': 0, 'cancelled': 0, 'not_processed': 0,
              'errors': [], 'error_details': []}
    # Check the entire approved selection before changing any item. The volume
    # gate is repeated inside recycle_file immediately before the Shell call.
    try:
        if method not in ('trash', 'folder'):
            raise ValueError('Unknown cleanup method')
        if method == 'folder':
            _validate_archive(SimpleNamespace(date_archive_name=archive_folder_name,
                                              folders=list({c['folder'] for c in candidates})))
        seen = set()
        for candidate in candidates:
            if cancel_callback and cancel_callback():
                result['cancelled'] = len(candidates)
                return result
            root = os.path.abspath(candidate['folder'])
            path = os.path.abspath(candidate['path'])
            if os.path.normcase(path) in seen:
                raise OSError('Duplicate selection')
            seen.add(os.path.normcase(path))
            if os.path.normcase(os.path.join(root, candidate['filename'])) != os.path.normcase(path):
                raise OSError('Candidate path does not match its folder')
            _check_path(root, path)
            family = tuple(candidate['family'])
            parsed = _parse_version(os.path.basename(path))
            snapshot = candidate['family_snapshot']
            if not parsed or parsed[0] != family or _snapshot(os.path.dirname(path), family, cancel_callback) != snapshot or _has_conflicts(snapshot):
                raise OSError(f'Family changed since preview: {path}')
            _validate_versions(snapshot, os.path.dirname(path))
            if parsed[3] >= max(entry['version_key'] for entry in snapshot):
                raise OSError(f'Selected file is no longer an older version: {path}')
            if method == 'trash':
                _require_internal_physical_volume(path)
            else:
                _archive_destination(root, path, archive_folder_name)
    except _Cancelled:
        result['cancelled'] = len(candidates)
        return result
    except Exception as error:  # noqa: BLE001 - fail closed on malformed inputs and callback failures
        result['fail'] = len(candidates)
        result['errors'].append(f'Preflight failed: {error}; no files were changed.')
        result['error_details'].append({'phase': 'preflight', 'path': '',
                                        'reason': str(error), 'uncertain': False})
        return result
    expected = {}
    processed = set()
    for index, candidate in enumerate(candidates):
        path = candidate['path']
        operation_started = False
        try:
            if cancel_callback and cancel_callback():
                result['cancelled'] += len(candidates) - index
                break
            if progress_callback:
                progress_callback(index, len(candidates), path)
            root = os.path.abspath(candidate['folder'])
            path = os.path.abspath(path)
            if os.path.normcase(path) in processed:
                raise OSError('Duplicate selection')
            if os.path.normcase(os.path.join(root, candidate['filename'])) != os.path.normcase(path):
                raise OSError('Candidate path does not match its folder')
            _check_path(root, path)
            directory = os.path.dirname(path)
            family = tuple(candidate['family'])
            parsed = _parse_version(os.path.basename(path))
            if not parsed or parsed[0] != family:
                raise OSError('Invalid candidate family')
            key = (os.path.normcase(directory), family)
            baseline = expected.setdefault(key, list(candidate['family_snapshot']))
            if _snapshot(directory, family, cancel_callback) != baseline or _has_conflicts(baseline):
                raise OSError('Family changed since preview')
            _validate_versions(baseline, directory)
            selected = next((e for e in baseline if e['filename'] == os.path.basename(path)), None)
            if not selected or selected['version_key'] >= max(e['version_key'] for e in baseline):
                raise OSError('Selected file is no longer an older version')
            if cancel_callback and cancel_callback():
                result['cancelled'] += len(candidates) - index
                break
            latest = max(baseline, key=lambda entry: entry['version_key'])
            latest_path = os.path.join(directory, latest['filename'])
            with _lock_versions(latest_path, path):
                _check_path(root, latest_path)
                _check_path(root, path)
                if _snapshot(directory, family, cancel_callback) != baseline:
                    raise OSError('Family changed immediately before processing')
                if method == 'trash':
                    operation_started = True
                    recycle_file(path)
                else:
                    archive, destination = _archive_destination(root, path, archive_folder_name)
                    os.makedirs(archive, exist_ok=True)
                    archive, destination = _archive_destination(root, path, archive_folder_name)
                    if _snapshot(directory, family, cancel_callback) != baseline:
                        raise OSError('Family changed immediately before processing')
                    operation_started = True
                    _exclusive_move(path, destination)
            baseline.remove(selected)
            processed.add(os.path.normcase(path))
            result['success'] += 1
        except _Cancelled:
            result['cancelled'] = len(candidates) - index
            break
        except Exception as error:  # noqa: BLE001 - stop after any uncertain filesystem or Shell failure
            result['fail'] += 1
            suffix = '; outcome may be uncertain.' if operation_started else '; file was not moved.'
            result['errors'].append(f'{path}: {error}{suffix}')
            result['error_details'].append({'phase': 'execution', 'path': path,
                                            'reason': str(error), 'uncertain': operation_started})
            # Shell calls and filesystem failures can leave an uncertain result.
            # Do not act on any later selection after such an error.
            result['not_processed'] = len(candidates) - index - 1
            break
    return result
