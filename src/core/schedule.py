"""Pure scheduling policy for the in-process daily task runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class ScheduleDecision:
    should_start: bool
    status: str
    next_at: datetime
    attempt_count: int


def parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_schedule_time(value: object, fallback: time = time(18, 0)) -> time:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return fallback


def evaluate_daily_schedule(
    *,
    now: datetime,
    schedule_time: object,
    last_started_at: object = "",
    legacy_last_run_date: object = "",
    attempt_date: object = "",
    attempt_count: object = 0,
    last_attempt_at: object = "",
    retry_minutes: int = 10,
    max_start_attempts: int = 3,
) -> ScheduleDecision:
    """Return whether a daily run may start without mutating persisted state.

    Retries apply only while a run has not started. Once a worker starts, the
    day is considered consumed so a partial file operation is never repeated
    automatically.
    """

    scheduled_clock = parse_schedule_time(schedule_time)
    scheduled_today = datetime.combine(now.date(), scheduled_clock)
    scheduled_tomorrow = scheduled_today + timedelta(days=1)
    today = now.date().isoformat()

    started = parse_timestamp(last_started_at)
    if (started and started.date() == now.date()) or str(legacy_last_run_date or "") == today:
        return ScheduleDecision(False, "already_started", scheduled_tomorrow, 0)

    if now < scheduled_today:
        return ScheduleDecision(False, "waiting", scheduled_today, 0)

    try:
        attempts = max(0, int(attempt_count)) if str(attempt_date or "") == today else 0
    except (TypeError, ValueError):
        attempts = 0

    if attempts >= max_start_attempts:
        return ScheduleDecision(False, "attempts_exhausted", scheduled_tomorrow, attempts)

    last_attempt = parse_timestamp(last_attempt_at)
    if last_attempt and last_attempt.date() == now.date():
        retry_at = last_attempt + timedelta(minutes=retry_minutes)
        if now < retry_at:
            return ScheduleDecision(False, "retry_wait", retry_at, attempts)

    status = "retry_due" if attempts else "due"
    return ScheduleDecision(True, status, now, attempts)
