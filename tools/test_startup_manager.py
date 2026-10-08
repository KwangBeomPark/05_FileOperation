from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils.startup_manager import (
    STARTUP_SHORTCUT_NAME,
    get_startup_folder,
    get_startup_shortcut_path,
    clean_legacy_startup_shortcuts,
    is_startup_enabled,
    resolve_startup_target_and_arguments,
    set_startup_enabled,
    toggle_startup,
)


class StartupManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_appdata = Path(self.temp_dir.name)
        self.startup_folder = self.mock_appdata / r"Microsoft\Windows\Start Menu\Programs\Startup"
        self.startup_folder.mkdir(parents=True, exist_ok=True)
        self.env_patcher = patch.dict("os.environ", {"APPDATA": str(self.mock_appdata)})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def test_get_startup_folder_and_path(self):
        folder = get_startup_folder()
        self.assertEqual(folder, self.startup_folder)
        shortcut_path = get_startup_shortcut_path()
        self.assertEqual(shortcut_path, self.startup_folder / STARTUP_SHORTCUT_NAME)

    def test_clean_legacy_startup_shortcuts(self):
        # Create legacy shortcuts
        legacy_file = self.startup_folder / "FileOps.lnk"
        legacy_file.write_text("dummy", encoding="utf-8")
        another_legacy = self.startup_folder / "App05_FileOperation.lnk"
        another_legacy.write_text("dummy", encoding="utf-8")
        
        # Create canonical shortcut
        canonical_file = self.startup_folder / STARTUP_SHORTCUT_NAME
        canonical_file.write_text("canonical", encoding="utf-8")

        clean_legacy_startup_shortcuts()

        self.assertFalse(legacy_file.exists())
        self.assertFalse(another_legacy.exists())
        self.assertTrue(canonical_file.exists())

    def test_resolve_startup_target_and_arguments_non_frozen(self):
        with patch.object(sys, "frozen", False, create=True):
            target, arguments, working_dir = resolve_startup_target_and_arguments()
            self.assertTrue(target.endswith("python.exe") or target.endswith("pythonw.exe"))
            self.assertIn("main.py", arguments)
            self.assertIn("--tray", arguments)
            self.assertTrue(Path(working_dir).is_dir())

    def test_resolve_startup_target_and_arguments_frozen(self):
        mock_exe = r"C:\Program Files\FileOps Hub\App05_FileOps.exe"
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", mock_exe):
            target, arguments, working_dir = resolve_startup_target_and_arguments()
            self.assertEqual(target, str(Path(mock_exe).resolve()))
            self.assertEqual(arguments, "--tray")
            self.assertEqual(working_dir, str(Path(mock_exe).resolve().parent))

    def test_set_startup_enabled_and_toggle(self):
        canonical_file = get_startup_shortcut_path()
        self.assertFalse(is_startup_enabled())

        with patch("src.utils.startup_manager._create_shortcut_wscript") as mock_create:
            def side_effect(shortcut_path, target, arguments, working_dir, icon_location):
                Path(shortcut_path).write_text("mock shortcut content", encoding="utf-8")
            mock_create.side_effect = side_effect

            # 1. Enable startup
            result = set_startup_enabled(True)
            self.assertTrue(result)
            self.assertTrue(is_startup_enabled())
            self.assertTrue(canonical_file.is_file())
            mock_create.assert_called_once()

            # 2. Toggle to disabled
            new_state = toggle_startup()
            self.assertFalse(new_state)
            self.assertFalse(is_startup_enabled())
            self.assertFalse(canonical_file.exists())

            # 3. Toggle back to enabled
            new_state = toggle_startup()
            self.assertTrue(new_state)
            self.assertTrue(is_startup_enabled())
            self.assertTrue(canonical_file.is_file())

            # 4. Explicit disable
            result = set_startup_enabled(False)
            self.assertTrue(result)
            self.assertFalse(is_startup_enabled())
            self.assertFalse(canonical_file.exists())


if __name__ == "__main__":
    unittest.main()
