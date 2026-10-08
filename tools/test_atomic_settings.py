"""Failure-injection tests never use the signed release or real UserSetting."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui.settings_dialog import SettingsDialog
from src.utils.config_manager import ConfigManager
from src.utils.atomic_write import atomic_write_json
from src.core.preset_manager import apply_workflow_preset


class AtomicSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local"), "APPDATA": str(self.root / "roaming")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.manager = ConfigManager()

    def test_failed_set_update_remove_preserve_memory_disk_and_foreign_temporary(self):
        self.assertTrue(self.manager.set("custom", "original"))
        original = Path(self.manager.config_path).read_bytes()
        memory = copy.deepcopy(self.manager.config)
        foreign = Path(self.manager.config_path + ".tmp")
        foreign.write_bytes(b"another writer")
        with patch("src.utils.atomic_write.os.replace", side_effect=PermissionError("locked")):
            self.assertFalse(self.manager.set("custom", "changed"))
            self.assertFalse(self.manager.update({"custom": "changed"}))
            self.assertFalse(self.manager.remove("custom"))
        self.assertEqual(self.manager.config, memory)
        self.assertEqual(Path(self.manager.config_path).read_bytes(), original)
        self.assertEqual(foreign.read_bytes(), b"another writer")
        self.assertEqual(list(foreign.parent.glob(".settings.json.*.tmp")), [])

    def test_batch_encryption_failure_preserves_all_settings(self):
        before = copy.deepcopy(self.manager.config)
        original = Path(self.manager.config_path).read_bytes()
        with patch("src.utils.config_manager.encrypt_data", side_effect=OSError("unavailable")):
            self.assertFalse(self.manager.set_many({"smtp_port": 25, "sender_password": "fixture-secret"}))
        self.assertEqual(self.manager.config, before)
        self.assertEqual(Path(self.manager.config_path).read_bytes(), original)

    def test_explicit_empty_and_port_25_values_survive_reload(self):
        self.assertTrue(self.manager.set_many({"smtp_server": "", "smtp_port": 25, "auto_check_update": "manual"}))
        other = ConfigManager()
        self.assertEqual(other.get("smtp_server"), "")
        self.assertEqual(other.get("smtp_port"), 25)
        self.assertEqual(other.get("auto_check_update"), "manual")

    def test_flush_failure_preserves_original(self):
        original = Path(self.manager.config_path).read_bytes()
        with patch("src.utils.atomic_write.os.fsync", side_effect=OSError("disk failure")):
            self.assertFalse(self.manager.set("custom", "new"))
        self.assertEqual(Path(self.manager.config_path).read_bytes(), original)

    def test_read_failure_does_not_treat_settings_as_corruption(self):
        original = Path(self.manager.config_path).read_bytes()
        with patch("builtins.open", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                ConfigManager()
        self.assertEqual(Path(self.manager.config_path).read_bytes(), original)
        self.assertEqual(list(Path(self.manager.app_dir).glob("*.bak")), [])

    def test_corrupt_backup_never_overwrites_previous_backup(self):
        path = Path(self.manager.config_path)
        path.write_bytes(b"invalid json")
        previous = Path(str(path) + ".bak")
        previous.write_bytes(b"previous backup")
        ConfigManager()
        self.assertEqual(previous.read_bytes(), b"previous backup")
        backups = list(path.parent.glob("settings.json.*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"invalid json")

    def test_bad_schema_version_does_not_reset_valid_user_values(self):
        path = Path(self.manager.config_path)
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update({"config_version": "invalid", "smtp_port": 25,
                      "bypass_output_mode": [], "bypass_source_disposition": {}})
        path.write_text(json.dumps(value), encoding="utf-8")
        loaded = ConfigManager()
        self.assertEqual(loaded.get("smtp_port"), 25)
        self.assertEqual(loaded.get("config_version"), 3)
        self.assertEqual(loaded.get("bypass_output_mode"), "inplace")
        self.assertEqual(loaded.get("bypass_source_disposition"), "keep")

    def test_dialog_failure_stays_open_and_does_not_accept(self):
        dialog = SettingsDialog(self.manager)
        self.addCleanup(dialog.close)
        with patch.object(self.manager, "set_many", return_value=False), patch.object(dialog, "accept") as accept, patch("src.ui.settings_dialog.QMessageBox.warning") as warning:
            dialog.save_settings()
        accept.assert_not_called()
        warning.assert_called_once()

    def test_invalid_webhook_does_not_save_any_other_setting(self):
        dialog = SettingsDialog(self.manager)
        self.addCleanup(dialog.close)
        dialog.webhook_url_input.setText("invalid://example")
        with patch.object(self.manager, "set_many") as save, patch("src.ui.settings_dialog.QMessageBox.warning"):
            dialog.save_settings()
        save.assert_not_called()

    def test_repeated_writes_use_unique_temporary_files(self):
        paths = []
        replace = os.replace
        with patch("src.utils.atomic_write.os.replace", side_effect=lambda source, target: (paths.append(source), replace(source, target))[-1]):
            atomic_write_json(self.root / "example.json", {"x": 1})
            atomic_write_json(self.root / "example.json", {"x": 2})
        self.assertEqual(len(set(paths)), 2)

    def test_running_settings_corruption_blocks_all_mutators(self):
        path = Path(self.manager.config_path)
        memory = copy.deepcopy(self.manager.config)
        for invalid in (b"broken json", b"[]", b"\xffinvalid utf8"):
            path.write_bytes(invalid)
            self.assertFalse(self.manager.set("custom", 25))
            self.assertFalse(self.manager.update({"custom": 25}))
            self.assertFalse(self.manager.set_many({"smtp_port": 25}))
            self.assertFalse(self.manager.remove("smtp_port"))
            self.assertEqual(path.read_bytes(), invalid)
            self.assertEqual(self.manager.config, memory)

    def test_preset_save_failure_is_not_reported_as_success(self):
        original = Path(self.manager.config_path).read_bytes()
        memory = copy.deepcopy(self.manager.config)
        with patch("src.utils.atomic_write.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                apply_workflow_preset(self.manager, {"sync_move_to_deleted": False})
        self.assertEqual(Path(self.manager.config_path).read_bytes(), original)
        self.assertEqual(self.manager.config, memory)

    def test_unverified_corruption_backup_cannot_replace_original(self):
        path = Path(self.manager.config_path)
        path.write_bytes(b"broken original")
        with patch("src.utils.config_manager.shutil.copy2", side_effect=lambda source, destination: Path(destination).write_bytes(b"wrong copy")):
            with self.assertRaises(OSError):
                ConfigManager()
        self.assertEqual(path.read_bytes(), b"broken original")


if __name__ == "__main__":
    unittest.main()
