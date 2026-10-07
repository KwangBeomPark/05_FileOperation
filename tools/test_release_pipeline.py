"""Isolated release gates: no certificates, services, GitHub, or user data touched."""
import json
import tempfile
import unittest
from types import SimpleNamespace
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from scripts import build_all as build
from scripts import publish_release as publish
from src.app_identity import APP_EXE, PRODUCT_ID, installer_filenames


class ReleasePipelineTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.root = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.folder = self.root / "dist" / "packaging"
        self.folder.mkdir(parents=True)
        self.app = self.root / "dist" / APP_EXE
        self.app.write_bytes(b"app fixture")
        self.version = "1.4.2"
        self.context.enter_context(patch.object(build, "ROOT", self.root))
        self.context.enter_context(patch.object(build, "APP_EXE", self.app))
        self.context.enter_context(patch.object(build, "RELEASE_DIR", self.folder))
        self.context.enter_context(patch.object(build, "LOCAL_BUILD_DIR", self.root / "tools" / "_local"))
        self.enterprise = self.folder / installer_filenames(self.version)[0]
        self.enterprise.write_bytes(b"signed installer fixture")
        self.public = build.prepare_public_alias(self.version, self.enterprise)
        result = type("Result", (), {"returncode": 0, "stdout": ""})
        with patch.object(build.subprocess, "run", side_effect=[result(), result()]):
            build.write_build_manifest(self.version, self.enterprise, None, signed=True)
        self.manifest = json.loads((self.folder / "build-manifest.json").read_text())
        self.manifest.update(git_commit="abc123", worktree_dirty=False,
                             signing_certificate_sha1="A" * 40)
        self.save_manifest()

    def save_manifest(self):
        (self.folder / "build-manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        build.write_checksum_manifest(self.version, self.enterprise)

    def test_complete_dual_alias_set_and_manifest_checksum(self):
        manifest, paths = publish.validate_release(self.folder, self.version, "abc123")
        self.assertEqual(manifest["product_id"], PRODUCT_ID)
        self.assertEqual(len(paths), 4)
        self.assertEqual(self.enterprise.read_bytes(), self.public.read_bytes())
        self.assertIn("build-manifest.json", (self.folder / "SHA256SUMS.txt").read_text())

    def test_unsigned_dirty_stale_wrong_product_and_alias_only_rejected(self):
        for key, value in (("authenticode_verified", False), ("worktree_dirty", True),
                           ("git_commit", "stale"), ("version", "1.1.0"),
                           ("product_id", "wrong"), ("alias_only", True)):
            with self.subTest(key=key):
                original = self.manifest.copy()
                self.manifest[key] = value
                self.save_manifest()
                with self.assertRaises(ValueError):
                    publish.validate_release(self.folder, self.version, "abc123")
                self.manifest = original
                self.save_manifest()

    def test_missing_alias_and_extra_old_binary_rejected(self):
        self.public.unlink()
        with self.assertRaises(ValueError):
            publish.validate_release(self.folder, self.version, "abc123")
        build.prepare_public_alias(self.version, self.enterprise)
        (self.folder / "obsolete.exe").write_bytes(b"old")
        with self.assertRaises(ValueError):
            publish.validate_release(self.folder, self.version, "abc123")

    def test_tampered_manifest_installer_and_app_rejected(self):
        for path in (self.folder / "build-manifest.json", self.enterprise, self.app):
            with self.subTest(name=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaises(ValueError):
                    publish.validate_release(self.folder, self.version, "abc123")
                path.write_bytes(original)

    def test_duplicate_and_incomplete_checksums_rejected(self):
        checksum = self.folder / "SHA256SUMS.txt"
        original = checksum.read_text()
        for content in (original + original.splitlines()[0] + "\n",
                        "\n".join(original.splitlines()[:-1]), original.replace("  ", " ", 1)):
            checksum.write_text(content)
            with self.assertRaises(ValueError):
                publish.validate_release(self.folder, self.version, "abc123")

    def test_divergent_aliases_rejected_even_when_hashes_refreshed(self):
        self.public.write_bytes(b"different installer")
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "identical"):
            publish.validate_release(self.folder, self.version, "abc123")

    def test_duplicate_manifest_entries_rejected(self):
        self.manifest["artifacts"].append(self.manifest["artifacts"][0])
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "exactly"):
            publish.validate_release(self.folder, self.version, "abc123")

    def test_signature_flag_is_not_enough_to_promote(self):
        official = self.root / "release"
        official.mkdir()
        (official / "previous.exe").write_bytes(b"preserved")
        with patch.object(build, "verify_signed_payload", side_effect=ValueError("Not signed")):
            with self.assertRaises(ValueError):
                build.promote_verified_release(self.version, None, overwrite=True)
        self.assertEqual((official / "previous.exe").read_bytes(), b"preserved")

    def test_promotion_preserves_previous_release_outside_active_folder(self):
        official = self.root / "release"
        official.mkdir()
        (official / "previous.exe").write_bytes(b"preserved")
        (official / "SHA256SUMS.txt").write_text("old checksums", encoding="utf-8")
        (official / "build-manifest.json").write_text("old manifest", encoding="utf-8")
        with patch.object(build, "verify_signed_payload") as verify:
            build.promote_verified_release(self.version, None, overwrite=False)
        verify.assert_called_once()
        self.assertEqual(len(list(official.iterdir())), 4)
        backups = list((self.root / "tools" / "_local").glob("previous-release-*"))
        self.assertEqual((backups[0] / "previous.exe").read_bytes(), b"preserved")
        self.assertEqual((backups[0] / "SHA256SUMS.txt").read_text(), "old checksums")

    def test_same_version_promotion_still_requires_explicit_overwrite(self):
        official = self.root / "release"
        official.mkdir()
        previous = official / self.enterprise.name
        previous.write_bytes(b"previous signed version")
        with patch.object(build, "verify_signed_payload"):
            with self.assertRaises(SystemExit):
                build.promote_verified_release(self.version, None, overwrite=False)
        self.assertEqual(previous.read_bytes(), b"previous signed version")

    def test_old_version_tag_stops_signing_before_building(self):
        result = lambda output: SimpleNamespace(returncode=0, stdout=output)
        with patch.object(build.subprocess, "run", side_effect=[result("v1.4.2"), result("new"), result("old")]):
            with self.assertRaisesRegex(SystemExit, "new APP_VERSION"):
                build.ensure_version_not_reused(self.version)

    def test_verification_shell_is_absolute_and_drops_powershell7_module_paths(self):
        command = build.authenticode_verification_command(self.app, "A" * 40)
        self.assertTrue(Path(command[0]).is_absolute())
        with (patch.dict(build.os.environ, {"PSModulePath": "wrong modules"}),
              patch.object(build.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run):
            build.run(command)
        self.assertNotIn("PSModulePath", run.call_args.kwargs["env"])

    def test_missing_explicit_sign_tool_never_falls_back_to_path(self):
        with patch.dict(build.os.environ, {"FILEOPS_SIGNTOOL_PATH": str(self.root / "missing.exe")}):
            with self.assertRaisesRegex(SystemExit, "no fallback"):
                build.find_signtool()

    def test_obsolete_executable_cleanup_is_leaf_only_and_excludes_user_setting(self):
        entries = build.legacy_shortcut_entries()
        self.assertIn('Type: files; Name: "{app}\\App005_FileOps.exe"', entries)
        self.assertNotIn("UserSetting", entries)
        self.assertNotIn("filesandordirs", entries)
        self.assertNotIn('"{app}\\App05_FileOps.exe"', entries)

    def test_failed_promotion_restores_previous_release(self):
        official = self.root / "release"
        official.mkdir()
        (official / "previous.exe").write_bytes(b"preserved")
        rename = Path.rename

        def fail_prepared(path, target):
            if path.name.startswith("verified-release-"):
                raise OSError("simulated promotion failure")
            return rename(path, target)

        with patch.object(build, "verify_signed_payload"), patch.object(Path, "rename", fail_prepared):
            with self.assertRaises(OSError):
                build.promote_verified_release(self.version, None, overwrite=False)
        self.assertEqual((official / "previous.exe").read_bytes(), b"preserved")

    def test_remote_assets_must_match_local_digests(self):
        _, paths = publish.validate_release(self.folder, self.version, "abc123")
        payload = {"tagName": "v1.4.2", "isDraft": True, "isPrerelease": False,
                   "assets": [{"name": p.name, "size": p.stat().st_size, "state": "uploaded",
                               "digest": "sha256:" + build.sha256(p).lower()} for p in paths]}
        publish.validate_remote_assets(payload, paths, "v1.4.2", draft=True)
        payload["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValueError):
            publish.validate_remote_assets(payload, paths, "v1.4.2", draft=True)

    def test_release_verification_checks_app_and_both_installer_names(self):
        manifest, paths = publish.validate_release(self.folder, self.version, "abc123")
        with (patch.object(build, "find_signtool", return_value="signtool.exe"),
              patch.object(build, "verify_signtool"), patch.object(build, "run") as run):
            build.verify_signed_payload(manifest, paths)
        self.assertEqual(run.call_count, 6)

    def test_signing_checks_tool_publisher_before_any_tool_execution(self):
        with patch.object(build, "run") as run:
            build.verify_signtool("C:/O'Brien/signtool.exe")
        script = run.call_args.args[0][-1]
        self.assertIn("O''Brien", script)
        self.assertIn("CN=Microsoft Corporation", script)
        self.assertIn("$PSHOME", script)

    def test_checksum_symlink_rejected_before_read(self):
        is_symlink = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda p: p.name == "SHA256SUMS.txt" or is_symlink(p)):
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                publish.validate_release(self.folder, self.version, "abc123")

    def test_signed_build_cannot_reuse_stale_exe_or_skip_tests(self):
        for skip_pyinstaller, skip_tests in ((True, False), (False, True)):
            args = SimpleNamespace(sign=False, require_signature=True,
                                   skip_pyinstaller=skip_pyinstaller, skip_tests=skip_tests)
            with (patch.object(build, "parse_args", return_value=args),
                  patch.object(build, "verify_source_tree"),
                  patch.object(build, "require_signing_configuration") as configure):
                with self.assertRaisesRegex(SystemExit, "rebuild current sources"):
                    build.main()
                configure.assert_not_called()

    def test_user_setting_is_never_in_installer_payload_or_uninstall_cleanup(self):
        setup = (Path(__file__).resolve().parents[1] / "installer" / "setup.iss").read_text()
        self.assertIn('Name: "{app}\\UserSetting"; Flags: uninsneveruninstall', setup)
        self.assertNotIn('Type: filesandordirs; Name: "{app}\\UserSetting', setup)


if __name__ == "__main__":
    unittest.main()
