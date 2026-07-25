import hashlib
import importlib.util
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT / "App05_FileOps.pyw"
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
