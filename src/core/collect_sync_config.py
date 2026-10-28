"""Serializable collect groups and daily scheduling, without filesystem access."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from src.core.collect_sync import CollectConfigError, CollectGroup, normalize_keywords
from src.core.schedule import evaluate_daily_schedule, parse_timestamp


def local_now() -> datetime:
    """Return local wall time to match the existing daily scheduler's naive contract."""
    return datetime.now(timezone.utc).astimezone().replace(tzinfo=None)


def new_collect_group(name: str) -> dict:
    """Create an independent group with a stable identity for execution history."""
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "sources": [],
        "keywords": [],
        "target": "",
        "include_subfolders": False,
        "schedule_enabled": False,
        "schedule_time": "00:00",
    }


def build_collect_group(value: dict) -> CollectGroup:
    """Create the typed engine contract; disk validation belongs to the worker."""
    if not isinstance(value, dict):
        raise CollectConfigError("Invalid collect group")
    sources, keywords = value.get("sources", []), value.get("keywords", [])
    if (
        not isinstance(sources, (list, tuple))
        or not isinstance(keywords, (list, tuple))
        or not all(isinstance(item, str) for item in (*sources, *keywords))
        or not isinstance(value.get("target", ""), str)
        or not isinstance(value.get("name", ""), str)
        or not isinstance(value.get("include_subfolders", False), bool)
    ):
        raise CollectConfigError("Invalid collect group fields")
    return CollectGroup(
        str(value.get("name", "")),
        tuple(sources),
        normalize_keywords(keywords),
        value.get("target", "").strip(),
        bool(value.get("include_subfolders", False)),
    )


def collect_group_dict(group: CollectGroup) -> dict:
    """Return a JSON-friendly typed contract without schedule runtime history."""
    value = asdict(group)
    value["sources"] = list(group.sources)
    value["keywords"] = list(group.keywords)
    return value


def collect_schedule_decision(group: dict, now: datetime):
    """Use the existing once-daily catch-up and bounded prestart retry policy."""
    clock = group.get("schedule_time", "00:00")
    if not isinstance(clock, str) or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", clock
    ):
        raise CollectConfigError("Invalid daily time (HH:mm)")
    if not isinstance(group.get("schedule_enabled", False), bool):
        raise CollectConfigError("Invalid daily schedule flag")
    for key in ("schedule_last_started_at", "schedule_last_attempt_at"):
        raw = group.get(key, "")
        value = parse_timestamp(raw)
        if raw and (value is None or value.tzinfo is not None):
            raise CollectConfigError("Invalid local schedule timestamp")
    return evaluate_daily_schedule(
        now=now,
        schedule_time=clock,
        last_started_at=group.get("schedule_last_started_at", ""),
        attempt_date=group.get("schedule_attempt_date", ""),
        attempt_count=group.get("schedule_attempt_count", 0),
        last_attempt_at=group.get("schedule_last_attempt_at", ""),
        retry_minutes=10,
        max_start_attempts=3,
    )
