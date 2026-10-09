import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.app_identity import APP_EXE, INSTALL_DIR, asset_path, installer_filenames, installer_names_for_tag, user_data_dir
from src.utils.config_manager import ConfigManager
from src.core.updater import installer_names_for_tag as updater_names
from src.utils import logger as app_logger
from src.ui.task_tab import TaskTab


class AppIdentityTests(unittest.TestCase):
    def test_fallback_report_does_not_write_outside_user_setting_when_unwritable(self):
        tab = Mock()
        tab._text.side_effect = lambda english, _korean, _polish: english
        with (
            patch("src.ui.task_tab.os.makedirs", side_effect=PermissionError("denied")) as mkdir,
            patch("builtins.open") as open_file,
        ):
            TaskTab.save_fallback_report(tab, "report")
            mkdir.assert_called_once_with(str(user_data_dir() / "logs"), exist_ok=True)
            open_file.assert_not_called()
            self.assertIn("Could not save", tab.log.call_args.args[0])

    def test_unwritable_settings_folder_does_not_fall_back_to_working_directory(self):
        with (
            patch.dict(os.environ, {"LOCALAPPDATA": "C:/user/local"}),
            patch("src.utils.config_manager.os.makedirs", side_effect=PermissionError("denied")) as mkdir,
        ):
            with self.assertRaisesRegex(OSError, "FileOps UserSetting folder"):
                ConfigManager()
            mkdir.assert_called_once_with(str(user_data_dir()), exist_ok=True)

    def test_unwritable_logs_folder_does_not_create_an_alternate_folder(self):
        log = Mock()
        with (
            patch.object(app_logger, "_logger_initialized", False),
            patch.object(app_logger.logging, "getLogger", return_value=log),
            patch.object(app_logger.logging, "StreamHandler"),
            patch.object(app_logger.logging, "FileHandler") as file_handler,
            patch.object(app_logger, "_configure_console_encoding"),
            patch.object(app_logger.os, "makedirs", side_effect=PermissionError("denied")) as mkdir,
        ):
            self.assertIs(app_logger.setup_logger(), log)
            mkdir.assert_called_once_with(str(user_data_dir() / "logs"), exist_ok=True)
            file_handler.assert_not_called()
            log.warning.assert_called_once()

    def test_legacy_settings_are_not_imported_into_the_new_data_store(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}):
            legacy_dir = Path(temp_dir) / "IntegratedDataTool"
            legacy_dir.mkdir()
            legacy_settings = {"task_schedule_enabled": True, "sync_groups": [{"name": "old"}], "ui_language": "ko"}
            (legacy_dir / "setting_integrated.json").write_text(json.dumps(legacy_settings), encoding="utf-8")
            (legacy_dir / "reports").mkdir()
            manager = ConfigManager()
            self.assertEqual(Path(manager.config_path), Path(temp_dir) / "Programs" / "FileOps" / "UserSetting" / "settings.json")
            self.assertFalse(manager.get("task_schedule_enabled"))
            self.assertEqual(manager.get("sync_groups"), [])
            self.assertEqual(manager.get("ui_language"), "auto")
            self.assertFalse((Path(manager.app_dir) / "reports").exists())
            self.assertTrue((legacy_dir / "setting_integrated.json").is_file())

    def test_approved_data_folder_is_inside_the_installation_folder(self):
        self.assertEqual(INSTALL_DIR, "FileOps")
        self.assertEqual(APP_EXE, "App05_FileOps.exe")
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:/user/local"}):
            self.assertEqual(user_data_dir(), Path("C:/user/local/Programs/FileOps/UserSetting"))

    def test_frozen_custom_installation_uses_its_own_user_setting_folder(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "D:/custom/FileOps/App005_FileOps.exe"),
        ):
            self.assertEqual(user_data_dir(), Path("D:/custom/FileOps/UserSetting"))

    def test_source_and_frozen_icon_resolution_use_one_assets_layout(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(asset_path("icon.ico"), root / "assets" / "icon.ico")
        self.assertTrue(asset_path("icon.ico").is_file())
        with patch.object(sys, "_MEIPASS", "C:/frozen/app", create=True):
            self.assertEqual(asset_path("icon.ico"), Path("C:/frozen/app/assets/icon.ico"))

    def test_single_generated_name_and_historical_reader_compatibility(self):
        self.assertEqual(installer_filenames("1.4.3"), ("App05_FileOps_Setup_v1.4.3.exe",))
        accepted = installer_names_for_tag("v1.4.3")
        self.assertEqual(accepted[0], "App05_FileOps_Setup_v1.4.3.exe")
        self.assertIn("App05_FileOps-Setup_v1.4.3.exe", accepted)
        self.assertIn("FileOps-Setup.v1.4.3.exe", accepted)
        self.assertEqual(len(accepted), len(set(accepted)))

    def test_update_contract_rejects_launcher_assets_and_invalid_tags(self):
        for tag in ("v1.3.0", "v1.4.1", "v1.4.2"):
            self.assertEqual(updater_names(tag), installer_names_for_tag(tag))
            self.assertFalse(any("Launcher" in name for name in updater_names(tag)))
        self.assertNotIn("App05_FileOps_v1.3.0.exe", installer_names_for_tag("v1.3.0"))
        for tag in ("v1.4.2/../bad", "v1.4.2-beta", "", "abc"):
            self.assertEqual(installer_names_for_tag(tag), [])


if __name__ == "__main__":
    unittest.main()
