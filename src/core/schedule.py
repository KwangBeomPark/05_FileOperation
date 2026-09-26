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


def evaluate_flexible_schedule(
    *,
    now: datetime,
    schedule_time: object = "18:00",
    schedule_mode: str = "daily",
    interval_minutes: int = 60,
    weekdays: list[int] | None = None,
    last_started_at: object = "",
    legacy_last_run_date: object = "",
    attempt_date: object = "",
    attempt_count: object = 0,
    last_attempt_at: object = "",
    retry_minutes: int = 10,
    max_start_attempts: int = 3,
) -> ScheduleDecision:
    """Return whether a scheduled run may start under flexible rules (daily or interval).

    Supports:
    - schedule_mode="daily": Daily scheduled time with optional weekday filter (0=Mon, 6=Sun)
    - schedule_mode="interval": Periodic interval execution every N minutes
    """
    mode = str(schedule_mode or "daily").strip().lower()

    if mode == "interval":
        interval = max(1, int(interval_minutes))
        started = parse_timestamp(last_started_at)
        last_attempt = parse_timestamp(last_attempt_at)

        try:
            attempts = max(0, int(attempt_count))
        except (TypeError, ValueError):
            attempts = 0

        if started is None and last_attempt is None:
            return ScheduleDecision(True, "due", now, attempts)

        ref_time = started or last_attempt
        next_at = ref_time + timedelta(minutes=interval)

        if now < next_at:
            return ScheduleDecision(False, "interval_waiting", next_at, attempts)

        if attempts >= max_start_attempts and last_attempt:
            cycle_next = last_attempt + timedelta(minutes=interval)
            if now < cycle_next:
                return ScheduleDecision(False, "attempts_exhausted", cycle_next, attempts)

        if last_attempt and attempts > 0:
            retry_at = last_attempt + timedelta(minutes=retry_minutes)
            if now < retry_at:
                return ScheduleDecision(False, "retry_wait", retry_at, attempts)

        status = "retry_due" if attempts else "due"
        return ScheduleDecision(True, status, now, attempts)

    # Default "daily" mode
    scheduled_clock = parse_schedule_time(schedule_time)
    scheduled_today = datetime.combine(now.date(), scheduled_clock)

    if weekdays is not None and len(weekdays) > 0:
        valid_days = {int(d) % 7 for d in weekdays}
        if now.weekday() not in valid_days:
            days_ahead = 1
            while (now.weekday() + days_ahead) % 7 not in valid_days:
                days_ahead += 1
            next_date = (now + timedelta(days=days_ahead)).date()
            next_at = datetime.combine(next_date, scheduled_clock)
            return ScheduleDecision(False, "not_scheduled_day", next_at, 0)

        days_ahead = 1
        while (now.weekday() + days_ahead) % 7 not in valid_days:
            days_ahead += 1
        next_occurrence = datetime.combine((now + timedelta(days=days_ahead)).date(), scheduled_clock)
    else:
        next_occurrence = scheduled_today + timedelta(days=1)

    today = now.date().isoformat()
    started = parse_timestamp(last_started_at)
    if (started and started.date() == now.date()) or str(legacy_last_run_date or "") == today:
        return ScheduleDecision(False, "already_started", next_occurrence, 0)

    if now < scheduled_today:
        return ScheduleDecision(False, "waiting", scheduled_today, 0)

    try:
        attempts = max(0, int(attempt_count)) if str(attempt_date or "") == today else 0
    except (TypeError, ValueError):
        attempts = 0

    if attempts >= max_start_attempts:
        return ScheduleDecision(False, "attempts_exhausted", next_occurrence, attempts)

    last_attempt = parse_timestamp(last_attempt_at)
    if last_attempt and last_attempt.date() == now.date():
        retry_at = last_attempt + timedelta(minutes=retry_minutes)
        if now < retry_at:
            return ScheduleDecision(False, "retry_wait", retry_at, attempts)

    status = "retry_due" if attempts else "due"
    return ScheduleDecision(True, status, now, attempts)


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
    return evaluate_flexible_schedule(
        now=now,
        schedule_time=schedule_time,
        schedule_mode="daily",
        last_started_at=last_started_at,
        legacy_last_run_date=legacy_last_run_date,
        attempt_date=attempt_date,
        attempt_count=attempt_count,
        last_attempt_at=last_attempt_at,
        retry_minutes=retry_minutes,
        max_start_attempts=max_start_attempts,
    )
