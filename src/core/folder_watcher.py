"""Folder Watcher module with debounce and file write-lock safety checks."""

import fnmatch
import os
import threading
import time
from typing import Callable


def is_file_ready(file_path: str, check_duration: float = 0.2) -> bool:
    """Check if a file is completely written and not locked by another process."""
    if not os.path.exists(file_path):
        return False
    try:
        # Check if size is stable
        size1 = os.path.getsize(file_path)
        time.sleep(check_duration)
        size2 = os.path.getsize(file_path)
        if size1 != size2:
            return False

        # Attempt to open file for read access
        with open(file_path, "rb") as f:
            f.read(1)
        return True
    except (PermissionError, OSError):
        return False


class FolderWatcher:
    """Monitors one or more directories for added, modified, or stabilized files.

    Features:
    - Debounce timer: Waits for file writing activity to settle before notifying.
    - Write-lock readiness: Verifies that files can be read without permission errors.
    - Pattern filtering: Supports wildcard patterns like ['*.png', '*.pdf'].
    - Thread-safe: Operates in a background daemon thread without GUI dependencies.
    """

    def __init__(
        self,
        watch_folders: list[str],
        callback: Callable[[list[str]], None],
        debounce_seconds: float = 3.0,
        poll_interval: float = 1.0,
        patterns: list[str] | None = None,
        recursive: bool = False,
    ):
        self.watch_folders = [os.path.normpath(f) for f in watch_folders if f]
        self.callback = callback
        self.debounce_seconds = max(0.5, float(debounce_seconds))
        self.poll_interval = max(0.2, float(poll_interval))
        self.patterns = patterns or []
        self.recursive = bool(recursive)

        self._is_running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._known_snapshot: dict[str, tuple[float, int]] = {}  # path -> (mtime, size)
        self._pending_changes: set[str] = set()
        self._last_change_time: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _matches_pattern(self, filename: str) -> bool:
        if not self.patterns:
            return True
        return any(fnmatch.fnmatch(filename.lower(), p.lower()) for p in self.patterns)

    def _scan_folder(self, folder: str) -> dict[str, tuple[float, int]]:
        snapshot: dict[str, tuple[float, int]] = {}
        if not os.path.isdir(folder):
            return snapshot

        if self.recursive:
            for root, _dirs, files in os.walk(folder):
                for f in files:
                    if self._matches_pattern(f):
                        full_path = os.path.join(root, f)
                        try:
                            st = os.stat(full_path)
                            snapshot[full_path] = (st.st_mtime, st.st_size)
                        except OSError:
                            pass
        else:
            try:
                for entry in os.scandir(folder):
                    if entry.is_file() and self._matches_pattern(entry.name):
                        try:
                            st = entry.stat()
                            snapshot[entry.path] = (st.st_mtime, st.st_size)
                        except OSError:
                            pass
            except OSError:
                pass
        return snapshot

    def _poll_cycle(self) -> None:
        current_snapshot: dict[str, tuple[float, int]] = {}
        for folder in self.watch_folders:
            current_snapshot.update(self._scan_folder(folder))

        now = time.monotonic()
        new_or_modified: list[str] = []

        with self._lock:
            for path, (mtime, size) in current_snapshot.items():
                prev = self._known_snapshot.get(path)
                if prev is None:
                    # New file
                    new_or_modified.append(path)
                elif prev != (mtime, size):
                    # Modified file
                    new_or_modified.append(path)

            if new_or_modified:
                self._pending_changes.update(new_or_modified)
                self._last_change_time = now

            self._known_snapshot = current_snapshot

            # Check debounce readiness
            if self._pending_changes and (now - self._last_change_time) >= self.debounce_seconds:
                # Check write readiness for all pending files
                ready_files = [p for p in self._pending_changes if is_file_ready(p)]
                if ready_files:
                    triggered = list(ready_files)
                    self._pending_changes.difference_update(ready_files)
                    try:
                        self.callback(triggered)
                    except Exception:
                        pass

    def start(self, initial_snapshot: bool = True) -> None:
        """Start monitoring directories in the background."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            if initial_snapshot:
                # Prime known snapshot so existing files aren't immediately considered new
                for folder in self.watch_folders:
                    self._known_snapshot.update(self._scan_folder(folder))

            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def _run_loop(self) -> None:
        while self._is_running:
            self._poll_cycle()
            time.sleep(self.poll_interval)

    def stop(self) -> None:
        """Stop background monitoring."""
        with self._lock:
            self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
