import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

from src.core.release_config import DEFAULT_GITHUB_OWNER, DEFAULT_GITHUB_REPOSITORY


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT / "scripts" / "App05_FileOps_Launcher.pyw"
loader = SourceFileLoader("app05_launcher", str(LAUNCHER_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
launcher = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = launcher
loader.exec_module(launcher)


class FakeResponse:
    def __init__(self, payload=b"", final_url="https://github.com/example", chunks=None, total_size=None):
        self.payload = payload
        self.final_url = final_url
        self.chunks = list(chunks or [])
        self.total_size = total_size

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def read(self, _size=-1):
        if self.chunks:
            return self.chunks.pop(0)
        payload, self.payload = self.payload, b""
        return payload

    def info(self):
        size = self.total_size if self.total_size is not None else (sum(len(chunk) for chunk in self.chunks) if self.chunks else len(self.payload))
        return {"Content-Length": str(size)}

    def geturl(self):
        return self.final_url


class FakeOpener:
    def __init__(self, response):
        self.response = response

    def open(self, _request, timeout=30):
        return self.response


class FakeProgress:
    def update(self, _downloaded, _total_size):
        return None


class App05LauncherTests(unittest.TestCase):
    def test_dual_installer_names_prefer_enterprise_and_allow_public_only(self):
        enterprise = {"name": "App05_FileOps-Setup_v1.4.2.exe",
                      "browser_download_url": "https://github.com/a/enterprise.exe", "digest": "sha256:" + "a" * 64}
        public = {"name": "FileOps-Setup.v1.4.2.exe",
                  "browser_download_url": "https://github.com/a/public.exe", "digest": "sha256:" + "a" * 64}
        for assets, expected in (([public, enterprise], enterprise), ([public], public)):
            payload = json.dumps({"tag_name": "v1.4.2", "assets": assets}).encode()
            with patch("urllib.request.urlopen", return_value=FakeResponse(payload=payload)):
                self.assertEqual(launcher.latest_setup_asset().name, expected["name"])
        duplicate = json.dumps({"tag_name": "v1.4.2", "assets": [enterprise, enterprise, public]}).encode()
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload=duplicate)):
            with self.assertRaises(launcher.LauncherError):
                launcher.latest_setup_asset()

    def test_true_legacy_paths_and_executable_names_remain_discoverable(self):
        for folder, exe_name in (
            ("App005_FileOps", "App005_FileOps.exe"),
            ("App05_FileOps", "App05_FileOps.exe"),
            ("IntegratedDataTool", "IntegratedDataTool.exe"),
            ("IntegratedDataTool", launcher.APP_EXE),
        ):
            for base in (Path("Programs"), Path(".")):
                with self.subTest(folder=folder, exe=exe_name, base=base), tempfile.TemporaryDirectory() as temp_dir:
                    installed_exe = Path(temp_dir) / base / folder / exe_name
                    installed_exe.parent.mkdir(parents=True)
                    installed_exe.touch()
                    with (
                        patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=True),
                        patch.object(launcher, "registry_candidates", return_value=[]),
                    ):
                        self.assertEqual(launcher.find_installed_exe(), installed_exe)

    def test_registered_legacy_executable_is_accepted(self):
        for exe_name in ("App005_FileOps.exe", "IntegratedDataTool.exe"):
            with self.subTest(exe=exe_name), tempfile.TemporaryDirectory() as temp_dir:
                installed_exe = Path(temp_dir) / exe_name
                installed_exe.touch()
                with (
                    patch.object(launcher, "registry_candidates", return_value=[installed_exe]),
                    patch.object(launcher, "default_candidates", return_value=[]),
                ):
                    self.assertEqual(launcher.find_installed_exe(), installed_exe)

    def test_new_installer_is_selected_and_pre_141_launcher_is_not(self):
        import json

        for version in ("1.2.3", "1.4.1", "1.4.2"):
            setup_name = f"App05_FileOps-Setup_v{version}.exe"
            payload = json.dumps({"tag_name": f"v{version}", "assets": [
                {"name": setup_name, "browser_download_url": "https://github.com/a/setup.exe", "digest": "sha256:" + "a" * 64},
                {"name": f"App05_FileOps_v{version}.exe", "browser_download_url": "https://github.com/a/old.exe", "digest": "sha256:" + "b" * 64},
            ]}).encode()
            with self.subTest(version=version), patch("urllib.request.urlopen", return_value=FakeResponse(payload=payload)):
                self.assertEqual(launcher.latest_setup_asset().name, setup_name)
        self.assertNotIn("App05_FileOps_v1.2.3.exe", launcher.installer_names_for_tag("v1.2.3"))
        self.assertIn("App05_FileOps_v1.4.1.exe", launcher.installer_names_for_tag("v1.4.1"))

    def test_finds_new_and_legacy_user_installations(self):
        for relative_dir in (Path("Programs") / launcher.INSTALL_DIR, Path(launcher.INSTALL_DIR)):
            with self.subTest(relative_dir=relative_dir), tempfile.TemporaryDirectory() as temp_dir:
                installed_exe = Path(temp_dir) / relative_dir / launcher.APP_EXE
                installed_exe.parent.mkdir(parents=True)
                installed_exe.touch()
                with (
                    patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=True),
                    patch.object(launcher, "registry_candidates", return_value=[]),
                ):
                    self.assertEqual(launcher.find_installed_exe(), installed_exe)

    def test_new_default_precedes_legacy_when_no_install_is_registered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            new_exe = Path(temp_dir) / "Programs" / launcher.INSTALL_DIR / launcher.APP_EXE
            legacy_exe = Path(temp_dir) / launcher.INSTALL_DIR / launcher.APP_EXE
            for installed_exe in (new_exe, legacy_exe):
                installed_exe.parent.mkdir(parents=True)
                installed_exe.touch()
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=True),
                patch.object(launcher, "registry_candidates", return_value=[]),
            ):
                self.assertEqual(launcher.find_installed_exe(), new_exe)

    def test_registered_custom_install_precedes_default_and_stale_entry_falls_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            new_exe = Path(temp_dir) / "Programs" / launcher.INSTALL_DIR / launcher.APP_EXE
            custom_exe = Path(temp_dir) / "custom" / launcher.APP_EXE
            for installed_exe in (new_exe, custom_exe):
                installed_exe.parent.mkdir(parents=True)
                installed_exe.touch()
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=True),
                patch.object(launcher, "registry_candidates", return_value=[custom_exe]),
            ):
                self.assertEqual(launcher.find_installed_exe(), custom_exe)
                custom_exe.unlink()
                self.assertEqual(launcher.find_installed_exe(), new_exe)

    def test_settings_folder_without_executable_is_not_an_installation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / launcher.INSTALL_DIR).mkdir()
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=True),
                patch.object(launcher, "registry_candidates", return_value=[]),
            ):
                self.assertIsNone(launcher.find_installed_exe())

    def test_default_release_repository_is_the_canonical_repository(self):
        self.assertEqual(launcher.REPO_OWNER, DEFAULT_GITHUB_OWNER)
        self.assertEqual(launcher.REPO_NAME, DEFAULT_GITHUB_REPOSITORY)

    def test_language_detection_supports_windows_ui_languages_and_english_fallback(self):
        self.assertEqual(launcher.detect_language(ui_language_id=0x0412), "ko")
        self.assertEqual(launcher.detect_language(ui_language_id=0x0409), "en")
        self.assertEqual(launcher.detect_language(ui_language_id=0x0415), "pl")
        self.assertEqual(launcher.detect_language(ui_language_id=0x0411), "en")
        self.assertEqual(launcher.detect_language(ui_language_id=0, locale_name="fr-FR"), "en")

    def test_language_override_and_translation_catalog(self):
        self.assertEqual(launcher.detect_language(override="en-US"), "en")
        self.assertEqual(launcher.detect_language(override="pl-PL"), "pl")
        self.assertEqual(set(launcher.TRANSLATIONS), {"en", "ko", "pl"})
        original_language = launcher.LAUNCHER_LANGUAGE
        try:
            launcher.LAUNCHER_LANGUAGE = "en"
            self.assertEqual(
                launcher.translate("download_progress", percent=25),
                "Downloading the latest installer. 25%",
            )
        finally:
            launcher.LAUNCHER_LANGUAGE = original_language

    def test_github_release_asset_uses_exact_setup_name_and_digest(self):
        payload = b'''{
            "tag_name": "v1.2.3",
            "assets": [
                {"name": "App05_FileOps_v1.2.3.exe", "browser_download_url": "https://github.com/a/launcher.exe", "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
                {"name": "IntegratedDataTool_Setup_v1.2.3.exe", "browser_download_url": "https://github.com/a/setup.exe", "digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
            ]
        }'''
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload=payload)):
            asset = launcher.latest_setup_asset()

        self.assertEqual(asset.name, "IntegratedDataTool_Setup_v1.2.3.exe")
        self.assertEqual(asset.sha256, "b" * 64)

    def test_release_asset_rejects_missing_digest(self):
        payload = b'''{
            "tag_name": "v1.2.3",
            "assets": [{"name": "IntegratedDataTool_Setup_v1.2.3.exe", "browser_download_url": "https://github.com/a/setup.exe"}]
        }'''
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload=payload)):
            with self.assertRaises(launcher.LauncherError):
                launcher.latest_setup_asset()

    def test_release_assets_redirect_domain_is_trusted(self):
        self.assertTrue(launcher.trusted_url("https://release-assets.githubusercontent.com/a/b"))
        self.assertFalse(launcher.trusted_url("https://release-assets.githubusercontent.com:443/a/b"))
        self.assertFalse(launcher.trusted_url("https://mirror.release-assets.githubusercontent.com/a/b"))
        self.assertFalse(launcher.trusted_url("https://github.com:bad-port/a/b"))
        self.assertFalse(launcher.trusted_url("https://example.com/a/b"))

    def test_release_asset_rejects_duplicate_expected_installers(self):
        asset = b'{"name":"IntegratedDataTool_Setup_v1.2.3.exe","browser_download_url":"https://github.com/a/setup.exe","digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        payload = b'{"tag_name":"v1.2.3","assets":[' + asset + b"," + asset + b"]}"
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload=payload)):
            with self.assertRaises(launcher.LauncherError):
                launcher.latest_setup_asset()

    def test_download_accepts_verified_github_redirect(self):
        data = b"verified-installer"
        response = FakeResponse(
            chunks=[data, b""],
            final_url="https://release-assets.githubusercontent.com/github-production-release-asset/file",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "IntegratedDataTool_Setup_v1.2.3.exe"
            with patch("urllib.request.build_opener", return_value=FakeOpener(response)):
                launcher.download_file(
                    "https://github.com/owner/repo/releases/download/v1.2.3/IntegratedDataTool_Setup_v1.2.3.exe",
                    destination,
                    FakeProgress(),
                    hashlib.sha256(data).hexdigest(),
                )
            self.assertEqual(destination.read_bytes(), data)

    def test_download_rejects_untrusted_redirect_and_removes_partial_file(self):
        response = FakeResponse(chunks=[b"unsafe", b""], final_url="https://example.com/file.exe")
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "IntegratedDataTool_Setup_v1.2.3.exe"
            with patch("urllib.request.build_opener", return_value=FakeOpener(response)):
                with self.assertRaises(launcher.LauncherError):
                    launcher.download_file(
                        "https://github.com/owner/repo/releases/download/v1.2.3/IntegratedDataTool_Setup_v1.2.3.exe",
                        destination,
                        FakeProgress(),
                        "a" * 64,
                    )
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix(destination.suffix + ".download").exists())

    def test_download_rejects_oversized_content_length(self):
        response = FakeResponse(total_size=launcher.MAX_INSTALLER_BYTES + 1)
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "IntegratedDataTool_Setup_v1.2.3.exe"
            with patch("urllib.request.build_opener", return_value=FakeOpener(response)):
                with self.assertRaises(launcher.LauncherError):
                    launcher.download_file(
                        "https://github.com/owner/repo/releases/download/v1.2.3/IntegratedDataTool_Setup_v1.2.3.exe",
                        destination,
                        FakeProgress(),
                        "a" * 64,
                    )
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
