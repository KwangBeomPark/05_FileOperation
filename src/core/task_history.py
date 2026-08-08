from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.task_contracts import RunReport, TaskStep


VALID_STATUS_KEYS = {
    "pending",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "skipped",
}


def normalize_step_history(value: object) -> dict[str, dict[str, Any]]:
    """Return only well-formed latest-result snapshots for known task steps."""
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    valid_steps = {step.value for step in TaskStep}
    for step, entry in value.items():
        if step not in valid_steps or not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "")).lower()
        timestamp = str(entry.get("timestamp", "")).strip()
        if status not in VALID_STATUS_KEYS or not timestamp:
            continue
        try:
            success_count = max(0, int(entry.get("success_count", 0)))
            total_count = max(0, int(entry.get("total_count", 0)))
        except (TypeError, ValueError):
            continue
        normalized[step] = {
            "status": status,
            "timestamp": timestamp,
            "success_count": min(success_count, total_count) if total_count else success_count,
            "total_count": total_count,
            "detail": str(entry.get("detail", "")).strip()[:500],
        }
    return normalized


def merge_run_report_history(
    existing: object,
    report: RunReport,
    finished_at: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge a completed run into a latest-result-per-feature history map."""
    history = normalize_step_history(existing)
    timestamp = (finished_at or datetime.now()).isoformat(timespec="seconds")
    for step, result in report.results.items():
        detail = result.error_message or (result.details[-1] if result.details else "")
        history[step.value] = {
            "status": result.status.name.lower(),
            "timestamp": timestamp,
            "success_count": max(0, int(result.success_count)),
            "total_count": max(0, int(result.total_count)),
            "detail": str(detail).strip()[:500],
        }
    return history
