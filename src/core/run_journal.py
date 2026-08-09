from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.task_contracts import RunReport, StepStatus, TaskStep


logger = logging.getLogger(__name__)

RUN_STATUSES = {
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "interrupted",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RunJournal:
    """Persist compact run metadata and one readable report per execution."""

    def __init__(self, app_dir: str | os.PathLike[str]):
        self.reports_dir = Path(app_dir) / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def recover_interrupted_runs(self) -> int:
        """Mark runs left active by an earlier process as interrupted."""
        recovered = 0
        with self._lock:
            for metadata_path in self.reports_dir.glob("run_*.json"):
                entry = self._read_json(metadata_path)
                if not entry or entry.get("status") != "running":
                    continue
                entry.update({
                    "status": "interrupted",
                    "finished_at": _now_iso(),
                    "possibly_stalled": False,
                    "message": entry.get("message") or "The application closed before this run finished.",
                })
                if self._write_json_atomic(metadata_path, entry):
                    recovered += 1
        return recovered

    def start_run(
        self,
        active_steps: list[TaskStep],
        *,
        scheduled: bool,
        language: str,
    ) -> str:
        started_at = _now_iso()
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        entry = {
            "schema_version": 1,
            "run_id": run_id,
            "status": "running",
            "scheduled": bool(scheduled),
            "language": str(language),
            "active_steps": [step.value for step in active_steps],
            "started_at": started_at,
            "last_progress_at": started_at,
            "finished_at": "",
            "current_step": "",
            "detail": "",
            "progress_current": 0,
            "progress_total": 0,
            "possibly_stalled": False,
            "message": "",
            "report_file": f"{run_id}.txt",
        }
        with self._lock:
            if not self._write_json_atomic(self._metadata_path(run_id), entry):
                raise OSError("Could not create the run journal entry.")
        return run_id

    def touch(
        self,
        run_id: str,
        *,
        current_step: TaskStep | str | None = None,
        detail: str | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> bool:
        with self._lock:
            entry = self._load_entry(run_id)
            if not entry or entry.get("status") != "running":
                return False
            entry["last_progress_at"] = _now_iso()
            entry["possibly_stalled"] = False
            if current_step is not None:
                entry["current_step"] = (
                    current_step.value if isinstance(current_step, TaskStep) else str(current_step)
                )
            if detail is not None:
                entry["detail"] = str(detail)[:1000]
            if current is not None:
                entry["progress_current"] = max(0, int(current))
            if total is not None:
                entry["progress_total"] = max(0, int(total))
            return self._write_json_atomic(self._metadata_path(run_id), entry)

    def mark_possibly_stalled(self, run_id: str) -> bool:
        with self._lock:
            entry = self._load_entry(run_id)
            if not entry or entry.get("status") != "running":
                return False
            entry["possibly_stalled"] = True
            return self._write_json_atomic(self._metadata_path(run_id), entry)

    def finish_run(self, run_id: str, report: RunReport) -> str:
        status = self._report_status(report)
        report_body = report.report_body.strip() or self._minimal_report(report)
        report_path = self._report_path(run_id)
        with self._lock:
            if not self._write_text_atomic(report_path, report_body + "\n"):
                raise OSError("Could not save the run report.")
            entry = self._load_entry(run_id) or {
                "schema_version": 1,
                "run_id": run_id,
                "started_at": _now_iso(),
                "active_steps": [step.value for step in report.results],
            }
            entry.update({
                "status": status,
                "last_progress_at": _now_iso(),
                "finished_at": _now_iso(),
                "possibly_stalled": False,
                "message": str(report.message)[:1000],
                "report_file": report_path.name,
                "results": {
                    step.value: {
                        "status": result.status.name.lower(),
                        "success_count": max(0, int(result.success_count)),
                        "total_count": max(0, int(result.total_count)),
                    }
                    for step, result in report.results.items()
                },
            })
            if not self._write_json_atomic(self._metadata_path(run_id), entry):
                raise OSError("Could not finalize the run journal entry.")
        return str(report_path)

    def finish_failed(self, run_id: str, message: str, report_body: str = "") -> str:
        body = report_body.strip() or f"# Task Result Report\n\n- Status: Failed\n- Details: {message}\n"
        report_path = self._report_path(run_id)
        with self._lock:
            if not self._write_text_atomic(report_path, body + "\n"):
                raise OSError("Could not save the failed run report.")
            entry = self._load_entry(run_id) or {
                "schema_version": 1,
                "run_id": run_id,
                "started_at": _now_iso(),
                "active_steps": [],
            }
            entry.update({
                "status": "failed",
                "last_progress_at": _now_iso(),
                "finished_at": _now_iso(),
                "possibly_stalled": False,
                "message": str(message)[:1000],
                "report_file": report_path.name,
            })
            if not self._write_json_atomic(self._metadata_path(run_id), entry):
                raise OSError("Could not finalize the failed run journal entry.")
        return str(report_path)

    def list_runs(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        selected_status = status if status in RUN_STATUSES else None
        entries: list[dict[str, Any]] = []
        with self._lock:
            paths = sorted(self.reports_dir.glob("run_*.json"), reverse=True)
            for path in paths:
                entry = self._read_json(path)
                if not self._valid_entry(entry):
                    continue
                if selected_status and entry.get("status") != selected_status:
                    continue
                normalized = dict(entry)
                normalized["report_path"] = str(self._report_path(str(entry["run_id"])))
                entries.append(normalized)
                if len(entries) >= max(1, int(limit)):
                    break
        return entries

    def report_path(self, run_id: str) -> str:
        return str(self._report_path(run_id))

    def _metadata_path(self, run_id: str) -> Path:
        return self.reports_dir / f"{self._safe_run_id(run_id)}.json"

    def _report_path(self, run_id: str) -> Path:
        return self.reports_dir / f"{self._safe_run_id(run_id)}.txt"

    @staticmethod
    def _safe_run_id(run_id: str) -> str:
        value = str(run_id)
        if not value.startswith("run_") or not all(ch.isalnum() or ch == "_" for ch in value):
            raise ValueError("Invalid run identifier.")
        return value

    def _load_entry(self, run_id: str) -> dict[str, Any] | None:
        return self._read_json(self._metadata_path(run_id))

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as file:
                value = json.load(file)
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not read run journal entry %s: %s", path, exc)
            return None

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> bool:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as file:
                json.dump(value, file, indent=2, ensure_ascii=False)
            os.replace(temp_path, path)
            return True
        except OSError:
            logger.exception("Could not write run journal entry: %s", path)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    @staticmethod
    def _write_text_atomic(path: Path, content: str) -> bool:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as file:
                file.write(content)
            os.replace(temp_path, path)
            return True
        except OSError:
            logger.exception("Could not write run report: %s", path)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    @staticmethod
    def _valid_entry(entry: object) -> bool:
        run_id = entry.get("run_id") if isinstance(entry, dict) else None
        return (
            isinstance(entry, dict)
            and isinstance(run_id, str)
            and run_id.startswith("run_")
            and all(ch.isalnum() or ch == "_" for ch in run_id)
            and entry.get("status") in RUN_STATUSES
            and bool(entry.get("started_at"))
        )

    @staticmethod
    def _report_status(report: RunReport) -> str:
        if report.cancelled:
            return "cancelled"
        if report.overall_success:
            return "completed"
        statuses = {result.status for result in report.results.values()}
        if statuses & {StepStatus.COMPLETED, StepStatus.PARTIAL}:
            return "partial"
        return "failed"

    @staticmethod
    def _minimal_report(report: RunReport) -> str:
        lines = ["# Task Result Report", "", f"- Details: {report.message}", "", "## Status summary"]
        for step, result in report.results.items():
            lines.append(
                f"- {step.value}: {result.status.name.lower()} "
                f"({result.success_count}/{result.total_count})"
            )
        return "\n".join(lines)
