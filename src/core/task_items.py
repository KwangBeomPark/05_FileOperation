"""Stable identities and one-time migration to the master execution selection."""

import copy
import re
import uuid


def ensure_sync_ids(groups):
    seen = set()
    for group in groups:
        identity = group.get("id")
        if not isinstance(identity, str) or not identity or identity in seen:
            identity = uuid.uuid4().hex
            group["id"] = identity
        seen.add(identity)
    return groups


def migrate_task_selection(config):
    updates = {}
    initialized = bool(config.get("task_selection_migrated", False))
    legacy = config.get("task_enabled_steps", ["sync"])
    selected = dict(config.get("task_enabled_items", {}) or {})
    groups = copy.deepcopy(config.get("sync_groups", []))
    if isinstance(groups, list) and all(isinstance(g, dict) for g in groups):
        original = copy.deepcopy(groups)
        ensure_sync_ids(groups)
        for group in groups:
            selected.setdefault(f"sync:{group['id']}", not initialized and "sync" in legacy)
        if groups != original:
            updates["sync_groups"] = groups
    legacy_times = []
    collect = copy.deepcopy(config.get("collect_sync_groups", []))
    if isinstance(collect, list) and all(isinstance(g, dict) for g in collect):
        original = copy.deepcopy(collect)
        for group in collect:
            if not group.get("id"):
                group["id"] = uuid.uuid4().hex
            if group.get("schedule_enabled") is True:
                legacy_times.append(group.get("schedule_time", ""))
                selected[f"collect_sync:{group['id']}"] = True
                group["schedule_enabled"] = False
            selected.setdefault(f"collect_sync:{group['id']}", False)
        if collect != original:
            updates["collect_sync_groups"] = collect
    enabling_collect_schedule = legacy_times and not config.get("task_schedule_enabled", False)
    if enabling_collect_schedule:
        valid_times = [clock for clock in legacy_times if isinstance(clock, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock)]
        updates["task_schedule_enabled"] = True
        updates["task_schedule_time"] = min(valid_times) if valid_times else "18:00"
    for step in ("eml", "pdf", "ocr"):
        selected.setdefault(step, not initialized and step in legacy)
    if enabling_collect_schedule:
        # Legacy collection schedules do not grant consent to schedule other work.
        for key in selected:
            if not key.startswith("collect_sync:"):
                selected[key] = False
    if not initialized:
        updates["task_selection_migrated"] = True
    if selected != config.get("task_enabled_items", {}):
        updates["task_enabled_items"] = selected
    if updates:
        if callable(getattr(config, "update", None)):
            if config.update(updates) is False:
                raise OSError("Could not save master schedule migration.")
        else:
            for key, value in updates.items():
                if config.set(key, value) is False:
                    raise OSError("Could not save master schedule migration.")
