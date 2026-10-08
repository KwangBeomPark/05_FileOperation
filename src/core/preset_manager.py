"""Workflow preset manager for exporting and importing configuration profiles safely.

Ensures sensitive credentials (passwords, tokens, secrets) and transient runtime states
are excluded during export and import.
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime
from typing import Any

from src.utils.config_manager import ConfigManager

# Patterns for sensitive keys that must NEVER be exported in preset files
SENSITIVE_KEY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r".*token.*",
        r".*password.*",
        r".*secret.*",
        r".*credential.*",
        r".*api_key.*",
    ]
]

TRANSIENT_KEYS = {
    "task_schedule_last_run_date",
    "task_schedule_attempt_date",
    "task_schedule_attempt_count",
    "task_schedule_last_attempt_at",
    "task_schedule_last_started_at",
    "task_schedule_last_finished_at",
    "task_schedule_last_success_at",
    "task_schedule_last_failure_at",
    "task_schedule_last_failure_reason",
    "task_step_last_results",
    "recent_files",
    "window_size",
}


def is_sensitive_key(key: str) -> bool:
    """Check if a configuration key holds sensitive credentials."""
    if key in ConfigManager.SECURE_KEYS:
        return True
    return any(p.search(key) for p in SENSITIVE_KEY_PATTERNS)


def sanitize_config_for_export(config_data: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive credentials and ephemeral runtime state from configuration."""
    sanitized: dict[str, Any] = {}
    for key, val in config_data.items():
        if is_sensitive_key(key) or key in TRANSIENT_KEYS:
            continue
        sanitized[key] = copy.deepcopy(val)
    return sanitized


def export_workflow_preset(
    config_data: dict[str, Any],
    output_path: str,
    preset_name: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Export a sanitized configuration preset envelope to a JSON file."""
    sanitized_settings = sanitize_config_for_export(config_data)
    name = preset_name or os.path.splitext(os.path.basename(output_path))[0] or "Preset"

    envelope = {
        "preset_format": "fileops.workflow.v1",
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "settings": sanitized_settings,
    }

    dir_name = os.path.dirname(os.path.abspath(output_path))
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)

    from src.utils.atomic_write import atomic_write_json

    atomic_write_json(output_path, envelope)

    return envelope


def load_workflow_preset(input_path: str) -> dict[str, Any]:
    """Read and validate a preset file, returning the sanitized settings dict."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Preset file not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("Invalid preset file format: root must be a JSON object.")

    if "settings" in raw and isinstance(raw["settings"], dict):
        settings = raw["settings"]
    elif "config" in raw and isinstance(raw["config"], dict):
        settings = raw["config"]
    else:
        settings = raw

    return sanitize_config_for_export(settings)


def apply_workflow_preset(
    config_manager: Any,
    preset_settings: dict[str, Any],
    categories: list[str] | None = None,
) -> int:
    """Apply preset settings to config_manager.

    Returns the number of settings keys updated.
    """
    category_map = {
        "sync": {"sync_groups", "sync_folders", "sync_move_to_deleted"},
        "eml": {"eml_tasks", "eml_incremental", "eml_output_width", "offline_chromium_path"},
        "pdf": {"dpi_large", "dpi_small", "dpi_threshold", "document_types", "search_depth", "settlement_working_folder"},
        "ocr": {"ocr_rule_mode", "ocr_custom_pattern", "ocr_rename_template", "ocr_export_txt", "promotion_regex", "tesseract_path"},
        "bypass": {"bypass_excel_target", "bypass_ppt_target", "bypass_word_target", "bypass_pdf_target", "bypass_output_mode", "bypass_source_disposition", "bypass_preserve_meta"},
        "schedule": {"task_schedule_enabled", "task_schedule_time", "task_schedule_mode", "task_schedule_interval_minutes", "task_schedule_weekdays", "task_chain_outputs", "task_enabled_steps", "task_folder_watch_enabled", "task_watch_folders", "task_watch_debounce_seconds", "task_watch_patterns"},
    }

    allowed_keys: set[str] | None = None
    if categories is not None:
        allowed_keys = set()
        for cat in categories:
            allowed_keys.update(category_map.get(cat.lower(), set()))

    applied_count = 0
    updates: dict[str, Any] = {}

    for key, val in preset_settings.items():
        if is_sensitive_key(key) or key in TRANSIENT_KEYS:
            continue
        if allowed_keys is not None and key not in allowed_keys:
            continue
        updates[key] = copy.deepcopy(val)
        applied_count += 1

    if updates:
        update_fn = getattr(config_manager, "update", None)
        if callable(update_fn):
            if update_fn(updates) is False:
                raise OSError("Workflow preset settings could not be saved. Previous settings were retained.")
        else:
            for k, v in updates.items():
                if config_manager.set(k, v) is False:
                    raise OSError("Workflow preset settings could not be saved completely.")

    return applied_count
