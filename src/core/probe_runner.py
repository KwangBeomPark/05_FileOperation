from __future__ import annotations

import multiprocessing
import os
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from threading import Event
from typing import Any


PATH_TIMEOUT_SECONDS = 8.0
SMTP_TIMEOUT_SECONDS = 5.0
DEPENDENCY_TIMEOUT_SECONDS = 15.0
OFFICE_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    value: Any = None
    error: str = ""
    timed_out: bool = False
    cancelled: bool = False
    elapsed_seconds: float = 0.0


class _ConfigView:
    def __init__(self, values: dict[str, Any]):
        self.values = values

    def get(self, key: str, default=None):
        return self.values.get(key, default)


def _path_access(payload: dict[str, Any]) -> dict[str, Any]:
    files = sorted(set(payload.get("files") or []))
    read_folders = sorted(set(payload.get("read_folders") or []))
    write_folders = sorted(set(payload.get("write_folders") or []))
    failures: list[dict[str, str]] = []

    for path in files:
        if not os.path.isfile(path):
            failures.append({"kind": "missing_file", "path": path})
        elif not os.access(path, os.R_OK):
            failures.append({"kind": "unreadable_file", "path": path})

    for path in sorted(set(read_folders + write_folders)):
        if not os.path.isdir(path):
            failures.append({"kind": "missing_folder", "path": path})
            continue
        try:
            with os.scandir(path):
                pass
        except OSError as exc:
            failures.append({"kind": "unavailable_folder", "path": path, "error": str(exc)})
            continue
        if path in write_folders and not os.access(path, os.W_OK):
            failures.append({"kind": "unwritable_folder", "path": path})

    return {
        "failures": failures,
        "checked_count": len(files) + len(set(read_folders + write_folders)),
    }


def _run_registered_probe(probe_name: str, payload: dict[str, Any]) -> Any:
    if probe_name == "path_access":
        return _path_access(payload)
    if probe_name == "office_apps":
        from src.core.preflight import check_office_apps

        ok, errors = check_office_apps(list(payload.get("apps") or []))
        return {"ok": ok, "errors": errors}
    if probe_name == "playwright_browser":
        from src.core.preflight import check_playwright_driver

        ok, detail = check_playwright_driver(check_browser=True)
        return {"ok": ok, "detail": detail}
    if probe_name == "ocr_engine":
        from src.core.preflight import check_ocr_engines

        ok, detail, using_fallback = check_ocr_engines(_ConfigView(payload))
        return {"ok": ok, "detail": detail, "using_fallback": using_fallback}
    if probe_name == "smtp_connect":
        server = str(payload["server"])
        port = int(payload["port"])
        socket_timeout = float(payload.get("socket_timeout", SMTP_TIMEOUT_SECONDS))
        with socket.create_connection((server, port), timeout=socket_timeout):
            pass
        return {"server": server, "port": port}
    if probe_name == "backup_list":
        from src.core.backup_recovery import list_backup_entries

        return [asdict(entry) for entry in list_backup_entries(str(payload.get("source_folder", "")))]
    if probe_name == "test_sleep":
        time.sleep(float(payload.get("seconds", 0)))
        return {"slept": True}
    raise ValueError(f"Unsupported probe: {probe_name}")


def _worker_entry(probe_name: str, payload: dict[str, Any], sender) -> None:
    try:
        value = _run_registered_probe(probe_name, payload)
        sender.send({"ok": True, "value": value})
    except BaseException as exc:
        try:
            sender.send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            pass
    finally:
        sender.close()


def _terminate_process_tree(process) -> None:
    if process is None or process.pid is None:
        return
    if sys.platform == "win32" and process.is_alive():
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=5,
                creationflags=creation_flags,
            )
        except Exception:
            pass
    if process.is_alive():
        process.terminate()
    process.join(timeout=2)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(timeout=1)


def run_probe(
    probe_name: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float,
    cancel_event: Event | None = None,
    context=None,
) -> ProbeResult:
    """Run one allow-listed, non-destructive probe in a disposable process."""
    started = time.monotonic()
    ctx = context or multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_worker_entry, args=(probe_name, dict(payload or {}), sender))
    process.daemon = False
    try:
        process.start()
        sender.close()
        while True:
            elapsed = time.monotonic() - started
            if cancel_event is not None and cancel_event.is_set():
                _terminate_process_tree(process)
                return ProbeResult(False, error="Probe cancelled.", cancelled=True, elapsed_seconds=elapsed)
            if receiver.poll(0.05):
                message = receiver.recv()
                process.join(timeout=1)
                return ProbeResult(
                    bool(message.get("ok")),
                    value=message.get("value"),
                    error=str(message.get("error", "")),
                    elapsed_seconds=time.monotonic() - started,
                )
            if elapsed >= timeout_seconds:
                _terminate_process_tree(process)
                return ProbeResult(
                    False,
                    error=f"Probe exceeded {timeout_seconds:g} seconds.",
                    timed_out=True,
                    elapsed_seconds=elapsed,
                )
            if not process.is_alive():
                return ProbeResult(
                    False,
                    error=f"Probe process exited without a result (exit code {process.exitcode}).",
                    elapsed_seconds=elapsed,
                )
    except Exception as exc:
        _terminate_process_tree(process)
        return ProbeResult(False, error=f"Could not start probe: {exc}", elapsed_seconds=time.monotonic() - started)
    finally:
        receiver.close()
