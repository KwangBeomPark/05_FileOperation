"""Persistent collect settings and pure daily policy regression tests."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from src.core.collect_sync import CollectConfigError, CollectGroup
from src.core.collect_sync_config import (
    build_collect_group,
    collect_schedule_decision,
    new_collect_group,
)
from src.utils.config_manager import ConfigManager


def wall_time(*args):
    """Construct a local wall-clock fixture matching the existing daily policy."""
    return datetime(*args, tzinfo=timezone.utc).replace(tzinfo=None)


class CollectConfigTests(unittest.TestCase):
    def test_typed_contract_without_disk_access(self):
        value = new_collect_group("Daily")
        value.update(
            sources=["offline/source"],
            keywords=["report", "REPORT", "memo"],
            target="offline/target",
        )
        contract = build_collect_group(value)
        self.assertIsInstance(contract, CollectGroup)
        self.assertEqual(contract.keywords, ("report", "memo"))

    def test_malformed_fields_are_rejected(self):
        for value in ({"sources": "wrong"}, {"keywords": [None]}, {"target": None}):
            with self.assertRaises(CollectConfigError):
                build_collect_group(value)

    def test_real_atomic_config_roundtrip_and_failure_preserve_settings(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "src.utils.config_manager.user_data_dir", return_value=Path(temporary)
            ),
        ):
            config = ConfigManager()
            groups = [new_collect_group("Daily")]
            self.assertTrue(config.set("collect_sync_groups", groups))
            restored = ConfigManager()
            self.assertEqual(restored.get("collect_sync_groups"), groups)
            with patch(
                "src.utils.atomic_write.os.replace",
                side_effect=PermissionError("locked"),
            ):
                self.assertFalse(config.set("collect_sync_groups", []))
            self.assertEqual(config.get("collect_sync_groups"), groups)
            self.assertEqual(ConfigManager().get("collect_sync_groups"), groups)

    def test_daily_wait_catchup_and_no_replay_of_previous_days(self):
        group = new_collect_group("Daily")
        group["schedule_time"] = "12:00"
        now = wall_time(2026, 10, 27, 11, 59)
        self.assertFalse(collect_schedule_decision(group, now).should_start)
        self.assertTrue(
            collect_schedule_decision(group, now + timedelta(minutes=2)).should_start
        )
        group["schedule_last_started_at"] = "2026-10-27T12:01:00"
        self.assertFalse(
            collect_schedule_decision(group, now + timedelta(hours=5)).should_start
        )
        self.assertTrue(
            collect_schedule_decision(
                group, now + timedelta(days=3, hours=5)
            ).should_start
        )

    def test_prestart_retry_bound_and_bad_time(self):
        group = new_collect_group("Daily")
        group.update(
            schedule_attempt_date="2026-10-27",
            schedule_attempt_count=1,
            schedule_last_attempt_at="2026-10-27T12:00:00",
        )
        self.assertFalse(
            collect_schedule_decision(
                group, wall_time(2026, 10, 27, 12, 5)
            ).should_start
        )
        self.assertTrue(
            collect_schedule_decision(
                group, wall_time(2026, 10, 27, 12, 10)
            ).should_start
        )
        group["schedule_attempt_count"] = 3
        self.assertFalse(
            collect_schedule_decision(group, wall_time(2026, 10, 27, 13)).should_start
        )
        group["schedule_time"] = "99:00"
        with self.assertRaises(CollectConfigError):
            collect_schedule_decision(group, wall_time(2026, 10, 27, 13))

    def test_malformed_schedule_history_is_rejected_instead_of_crashing_tick(self):
        for value in ("not a date", "2026-10-27T12:00:00+02:00", {"bad": "timestamp"}):
            group = new_collect_group("Daily")
            group["schedule_last_attempt_at"] = value
            with self.assertRaises(CollectConfigError):
                collect_schedule_decision(group, wall_time(2026, 10, 27, 13))
        group = new_collect_group("Daily")
        group["schedule_enabled"] = "false"
        with self.assertRaises(CollectConfigError):
            collect_schedule_decision(group, wall_time(2026, 10, 27, 13))
