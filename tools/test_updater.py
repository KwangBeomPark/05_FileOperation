import os
import hashlib
import tempfile
import unittest
from unittest.mock import patch

from src.core.release_config import (
    DEFAULT_GITHUB_OWNER,
    DEFAULT_GITHUB_REPOSITORY,
    latest_release_api_url,
    releases_page_url,
)
from src.core.updater import AutoUpdater, MAX_INSTALLER_BYTES, is_trusted_download_url


class FakeResponse:
    def __init__(self, payload=b"", total_size=None, chunks=None, final_url="https://github.com/example/setup.exe"):
        self.payload = payload
        self.total_size = total_size
        self.chunks = list(chunks or [])
        self.final_url = final_url

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
        size = self.total_size if self.total_size is not None else sum(len(chunk) for chunk in self.chunks) or len(self.payload)
        return {"Content-Length": str(size)}

    def geturl(self):
        return self.final_url


class FakeOpener:
    def __init__(self, response):
        self.response = response

    def open(self, _req, timeout=15):
        return self.response


class UpdaterTests(unittest.TestCase):
    def test_default_release_repository_is_the_canonical_repository(self):
        with patch("src.core.updater.ConfigManager") as config_manager:
            config_manager.return_value.get.return_value = ""
            updater = AutoUpdater()

        self.assertEqual(updater.repo_owner, DEFAULT_GITHUB_OWNER)
        self.assertEqual(updater.repo_name, DEFAULT_GITHUB_REPOSITORY)

    def test_release_url_helpers_keep_api_and_browser_routes_consistent(self):
        self.assertEqual(
            latest_release_api_url("owner", "repository"),
            "https://api.github.com/repos/owner/repository/releases/latest",
        )
        self.assertEqual(
            releases_page_url("owner", "repository", "v1.2.0"),
            "https://github.com/owner/repository/releases/tag/v1.2.0",
        )

    def test_version_comparison(self):
        updater = AutoUpdater(current_version="v1.0.0")

        self.assertTrue(updater.is_newer_version("v1.0.0", "v1.0.1"))
        self.assertFalse(updater.is_newer_version("v1.0.1", "v1.0.1"))
        self.assertTrue(updater.is_newer_version("v20260625", "v20260626"))

    def test_download_rejects_non_https(self):
        updater = AutoUpdater()
        with tempfile.NamedTemporaryFile() as file:
            with self.assertRaises(ValueError):
                updater.download_file("http://github.com/example/setup.exe", file.name, "a" * 64)

    def test_download_rejects_untrusted_domain(self):
        updater = AutoUpdater()
        with tempfile.NamedTemporaryFile() as file:
            with self.assertRaises(ValueError):
                updater.download_file("https://example.com/setup.exe", file.name, "a" * 64)

    def test_trusted_url_requires_an_exact_known_host_without_a_port(self):
        self.assertTrue(is_trusted_download_url("https://release-assets.githubusercontent.com/file"))
        self.assertFalse(is_trusted_download_url("https://mirror.release-assets.githubusercontent.com/file"))
        self.assertFalse(is_trusted_download_url("https://github.com:bad-port/file"))

    def test_release_asset_requires_the_expected_setup_exe_with_digest(self):
        payload = (
            b'{"tag_name":"v1.0.1","body":"notes","assets":['
            b'{"name":"source.zip","browser_download_url":"https://github.com/a/source.zip"},'
            b'{"name":"IntegratedDataTool.exe","browser_download_url":"https://github.com/a/app.exe"},'
            b'{"name":"IntegratedDataTool_Setup_v1.0.1.exe","browser_download_url":"https://github.com/a/setup.exe","digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
            b"]}"
        )
        updater = AutoUpdater(current_version="v1.0.0")

        with patch("urllib.request.urlopen", return_value=FakeResponse(payload=payload)):
            has_update, latest, download_url, notes = updater.check_for_updates()

        self.assertTrue(has_update)
        self.assertEqual(latest, "v1.0.1")
        self.assertEqual(download_url, "https://github.com/a/setup.exe")
        self.assertEqual(notes, "notes")
        self.assertEqual(updater.latest_asset.sha256, "a" * 64)

    def test_release_without_expected_installer_only_offers_release_page(self):
        payload = (
            b'{"tag_name":"v1.0.1","assets":['
            b'{"name":"App05_FileOps_v1.0.1.exe","browser_download_url":"https://github.com/a/launcher.exe"}'
            b"]}"
        )
        updater = AutoUpdater(current_version="v1.0.0")

        with patch("urllib.request.urlopen", return_value=FakeResponse(payload=payload)):
            has_update, latest, download_url, _notes = updater.check_for_updates()

        self.assertTrue(has_update)
        self.assertEqual(latest, "v1.0.1")
        self.assertIsNone(download_url)
        self.assertIsNone(updater.latest_asset)

    def test_release_with_duplicate_expected_installers_is_rejected(self):
        asset = (
            b'{"name":"IntegratedDataTool_Setup_v1.0.1.exe","browser_download_url":"https://github.com/a/setup.exe",'
            b'"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        )
        payload = b'{"tag_name":"v1.0.1","assets":[' + asset + b"," + asset + b"]}"
        updater = AutoUpdater(current_version="v1.0.0")

        with patch("urllib.request.urlopen", return_value=FakeResponse(payload=payload)):
            has_update, _latest, download_url, _notes = updater.check_for_updates()

        self.assertTrue(has_update)
        self.assertIsNone(download_url)
        self.assertIsNone(updater.latest_asset)

    def test_update_check_records_error(self):
        updater = AutoUpdater(current_version="v1.1.2")

        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            has_update, latest, download_url, notes = updater.check_for_updates()

        self.assertFalse(has_update)
        self.assertEqual(latest, "v1.1.2")
        self.assertIsNone(download_url)
        self.assertEqual(notes, "")
        self.assertIn("network down", updater.last_error)

    def test_incomplete_download_is_deleted(self):
        updater = AutoUpdater()
        response = FakeResponse(total_size=10, chunks=[b"abc", b""])

        with tempfile.TemporaryDirectory() as tmpdir:
            dest_path = f"{tmpdir}\\download.exe"
            with patch("urllib.request.build_opener", return_value=FakeOpener(response)):
                with self.assertRaises(OSError):
                    updater.download_file("https://github.com/example/setup.exe", dest_path, "a" * 64)

            self.assertFalse(os.path.exists(dest_path))

    def test_digest_mismatch_keeps_existing_complete_download(self):
        response = FakeResponse(chunks=[b"new", b""])
        updater = AutoUpdater()

        with tempfile.TemporaryDirectory() as tmpdir:
            dest_path = f"{tmpdir}\\download.exe"
            with open(dest_path, "wb") as file:
                file.write(b"existing")
            with patch("urllib.request.build_opener", return_value=FakeOpener(response)):
                with self.assertRaises(OSError):
                    updater.download_file("https://github.com/example/setup.exe", dest_path, hashlib.sha256(b"other").hexdigest())

            with open(dest_path, "rb") as file:
                self.assertEqual(file.read(), b"existing")

    def test_download_rejects_untrusted_final_redirect(self):
        response = FakeResponse(chunks=[b"data", b""], final_url="https://example.com/setup.exe")
        updater = AutoUpdater()

        with tempfile.TemporaryDirectory() as tmpdir:
            dest_path = f"{tmpdir}\\download.exe"
            with patch("urllib.request.build_opener", return_value=FakeOpener(response)):
                with self.assertRaises(ValueError):
                    updater.download_file("https://github.com/example/setup.exe", dest_path, hashlib.sha256(b"data").hexdigest())
            self.assertFalse(os.path.exists(dest_path))

    def test_download_rejects_oversized_content_length(self):
        response = FakeResponse(total_size=MAX_INSTALLER_BYTES + 1)
        updater = AutoUpdater()

        with tempfile.TemporaryDirectory() as tmpdir:
            dest_path = f"{tmpdir}\\download.exe"
            with patch("urllib.request.build_opener", return_value=FakeOpener(response)):
                with self.assertRaises(OSError):
                    updater.download_file("https://github.com/example/setup.exe", dest_path, "a" * 64)
            self.assertFalse(os.path.exists(dest_path))


if __name__ == "__main__":
    unittest.main()
