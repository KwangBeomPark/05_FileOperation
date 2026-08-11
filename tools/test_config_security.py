import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.utils.config_manager import ConfigManager
from src.utils.security import encrypt_data


class ConfigSecurityTests(unittest.TestCase):
    def test_sender_password_is_managed_as_secure_key(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=False):
            manager = ConfigManager("settings.json")
            self.assertTrue(manager.set("sender_password", "plain-secret"))
            self.assertEqual(manager.get("sender_password"), "plain-secret")

            with open(manager.config_path, "r", encoding="utf-8") as file:
                raw = json.load(file)

            self.assertNotEqual(raw["sender_password"], "plain-secret")
            self.assertEqual(raw["config_version"], 3)

    def test_v1_sender_password_migrates_without_double_encryption(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=False):
            app_dir = os.path.join(temp_dir, "IntegratedDataTool")
            os.makedirs(app_dir, exist_ok=True)
            config_path = os.path.join(app_dir, "settings.json")
            encrypted = encrypt_data("legacy-secret")
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump({"sender_password": encrypted}, file)

            manager = ConfigManager("settings.json")
            self.assertEqual(manager.get("sender_password"), "legacy-secret")
            self.assertEqual(manager.get("config_version"), 3)

    def test_legacy_source_deletion_setting_migrates_to_keep(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=False):
            app_dir = os.path.join(temp_dir, "IntegratedDataTool")
            os.makedirs(app_dir, exist_ok=True)
            config_path = os.path.join(app_dir, "settings.json")
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump({"config_version": 2, "bypass_delete_original": True}, file)

            manager = ConfigManager("settings.json")

            self.assertFalse(manager.get("bypass_delete_original"))
            self.assertEqual(manager.get("bypass_source_disposition"), "keep")
            with open(config_path, "r", encoding="utf-8") as file:
                persisted = json.load(file)
            self.assertFalse(persisted["bypass_delete_original"])
            self.assertEqual(persisted["bypass_source_disposition"], "keep")

    def test_existing_target_path_migrates_to_non_destructive_custom_output(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=False):
            app_dir = os.path.join(temp_dir, "IntegratedDataTool")
            target_dir = os.path.join(temp_dir, "converted")
            os.makedirs(app_dir)
            os.makedirs(target_dir)
            config_path = os.path.join(app_dir, "settings.json")
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump({"config_version": 2, "last_bypass_target_directory": target_dir}, file)

            manager = ConfigManager("settings.json")

            self.assertEqual(manager.get("config_version"), 3)
            self.assertEqual(manager.get("bypass_output_mode"), "custom")


if __name__ == "__main__":
    unittest.main()
