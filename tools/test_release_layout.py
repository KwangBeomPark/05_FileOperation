import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_all = load_module("build_all_release_layout", ROOT / "scripts" / "build_all.py")
diagnose_install = load_module("diagnose_install_release_layout", ROOT / "tools" / "diagnose_install.py")


class ReleaseLayoutTests(unittest.TestCase):
    def test_release_tests_use_isolated_data_without_changing_signing_environment(self):
        before = build_all.os.environ.get("LOCALAPPDATA")
        calls = []
        with patch.object(build_all, "run", side_effect=lambda cmd, **kw: calls.append((cmd, kw))):
            build_all.run_static_checks(skip_ruff=True, skip_tests=False)
        test_call = next(kw for cmd, kw in calls if "unittest" in cmd)
        self.assertEqual(test_call["env"]["QT_QPA_PLATFORM"], "offscreen")
        self.assertNotEqual(test_call["env"]["LOCALAPPDATA"], before)
        self.assertEqual(build_all.os.environ.get("LOCALAPPDATA"), before)

    def test_signing_verifies_all_signatures_and_windows_trust_before_returning(self):
        commands = []
        with (
            patch.dict(build_all.os.environ, {"FILEOPS_SIGN_CERT_SHA1": "A" * 40}),
            patch.object(build_all, "find_signtool", return_value="signtool.exe"),
            patch.object(build_all, "verify_signtool"),
            patch.object(build_all, "run", side_effect=lambda command: commands.append(command)),
        ):
            build_all.sign_artifact(Path("app.exe"), required=True)
        self.assertEqual(commands[0][1], "sign")
        self.assertEqual(commands[1], ["signtool.exe", "verify", "/pa", "/all", "/v", "app.exe"])
        self.assertIn("Get-AuthenticodeSignature", commands[2][-1])
        self.assertIn("TimeStamperCertificate", commands[2][-1])
        self.assertIn("A" * 40, commands[2][-1])

    def test_authenticode_verification_escapes_literal_paths(self):
        command = build_all.authenticode_verification_command(Path("C:/O'Brien/app.exe"), "A" * 40)
        self.assertIn("O''Brien", command[-1])
        self.assertIn("-LiteralPath", command[-1])
        self.assertIn("[IO.Path]::Combine($PSHOME", command[-1])
        self.assertIn("$ErrorActionPreference = 'Stop'", command[-1])

    def test_required_signing_cannot_silently_skip_a_missing_tool(self):
        with (
            patch.dict(build_all.os.environ, {"FILEOPS_SIGN_CERT_SHA1": "A" * 40}),
            patch.object(build_all, "find_signtool", return_value=None),
            patch.object(build_all, "run") as run,
        ):
            with self.assertRaises(SystemExit):
                build_all.sign_artifact(Path("app.exe"), required=True)
            run.assert_not_called()

    def test_release_sources_and_artifacts_have_one_home(self):
        version = "1.2.3"
        self.assertEqual(build_all.LAUNCHER_SOURCE, ROOT / "scripts" / "App05_FileOps_Launcher.pyw")
        self.assertEqual(
            build_all.setup_exe_path(version),
            ROOT / "release" / "App05_FileOps-Setup_v1.2.3.exe",
        )
        self.assertEqual(
            build_all.launcher_exe_path(version),
            ROOT / "release" / "App05_FileOps_Launcher_v1.2.3.exe",
        )
        self.assertEqual(
            diagnose_install.setup_exe_path(),
            ROOT / "release" / f"App05_FileOps-Setup_v{diagnose_install.APP_VERSION}.exe",
        )
        self.assertEqual(
            diagnose_install.launcher_exe_path(),
            ROOT / "release" / f"App05_FileOps_Launcher_v{diagnose_install.APP_VERSION}.exe",
        )

    def test_launcher_builder_targets_release_directory(self):
        commands = []

        def record_command(command, **_kwargs):
            commands.append(command)
            output_dir = Path(command[command.index("--distpath") + 1])
            output_name = command[command.index("--name") + 1]
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / f"{output_name}.exe").write_bytes(b"test launcher")
            return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            release_dir = Path(temp_dir) / "release"
            with (
                patch.object(build_all, "RELEASE_DIR", release_dir),
                patch.object(build_all, "module_available", return_value=True),
                patch.object(build_all, "run", side_effect=record_command),
                patch.object(build_all, "require_file"),
                patch.object(build_all, "write_version_resource", return_value=Path(temp_dir) / "launcher.version"),
            ):
                build_all.build_launcher(skip_pyinstaller=False, app_version="1.2.3")

        command = commands[0]
        output_index = command.index("--distpath") + 1
        self.assertEqual(command[output_index], str(release_dir))
        self.assertEqual(command[command.index("--icon") + 1], str(build_all.APP_ICON))

    def test_requirements_are_utf8_text_without_null_bytes(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("\0", requirements)
        self.assertIn("qtawesome==1.4.2", requirements)

    def test_installer_can_start_one_hidden_instance_with_windows(self):
        setup_text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
        self.assertIn('{userstartup}\\FileOps Hub', setup_text)
        self.assertIn('Parameters: "--tray"', setup_text)
        self.assertIn('Tasks: startup', setup_text)

    def test_new_install_default_is_programs_and_upgrade_keeps_existing_data_location(self):
        setup_text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
        self.assertIn('DefaultDirName={localappdata}\\Programs\\{#AppInstallDir}', setup_text)
        self.assertIn('UsePreviousAppDir=yes', setup_text)
        self.assertIn('DisableDirPage=no', setup_text)
        self.assertIn('PrivilegesRequired=lowest', setup_text)
        self.assertIn('Filename: "{app}\\{#AppProductId}.exe"', setup_text)

    def test_installer_receives_stable_identity_and_legacy_process_filter(self):
        command = build_all.installer_command("iscc", "1.4.2")
        self.assertIn(f'/O{build_all.RELEASE_DIR}', command)
        self.assertIn('/DAppProductId=App05_FileOps', command)
        self.assertIn('/DAppInstallDir=FileOps', command)
        self.assertIn('/DAppVersion=1.4.2', command)
        self.assertIn('/DAppInstallerId={{2A0D58B7-8D1D-44B1-9C3A-2B33F4F3DF11}', command)
        self.assertIn(f'/DAppExeSource={build_all.APP_EXE}', command)
        setup_text = build_all.SETUP_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('/DAppCloseApplications=App05_FileOps.exe,App005_FileOps.exe,IntegratedDataTool.exe,FileOps.exe', command)
        self.assertIn('CloseApplicationsFilter={#AppCloseApplications}', setup_text)

    def test_frozen_probe_workers_are_diverted_before_qt_imports(self):
        main_text = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
        freeze_index = main_text.index("multiprocessing.freeze_support()")
        qt_index = main_text.index("from PyQt6.QtWidgets")
        self.assertLess(freeze_index, qt_index)

    def test_app_and_launcher_version_resources_have_distinct_names(self):
        resources = []
        with tempfile.TemporaryDirectory() as temp_dir:
            app = Path(temp_dir) / "App05_FileOps.exe"
            release = Path(temp_dir) / "release"
            release.mkdir()
            app.write_bytes(b"app")
            (release / "App05_FileOps_Launcher_v1.4.2.exe").write_bytes(b"launcher")
            with (
                patch.object(build_all, "APP_EXE", app),
                patch.object(build_all, "RELEASE_DIR", release),
                patch.object(build_all, "module_available", return_value=True),
                patch.object(build_all, "write_version_resource", side_effect=lambda _version, **kw: resources.append(kw["resource_name"]) or Path("version.txt")),
                patch.object(build_all, "run"),
                patch.object(build_all, "require_file"),
                patch.object(build_all, "sha256", return_value="A" * 64),
            ):
                build_all.build_app(False, "1.4.2")
                build_all.build_launcher(False, "1.4.2")
        self.assertEqual(resources, ["App05_FileOps.version", "App05_FileOps_Launcher.version"])

    def test_manifest_records_version_commit_and_every_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = root / "dist" / "App05_FileOps.exe"
            setup = root / "release" / "App05_FileOps-Setup_v1.4.2.exe"
            launcher = root / "release" / "App05_FileOps_Launcher_v1.4.2.exe"
            for artifact in (app, setup, launcher):
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(artifact.name.encode())
            with (
                patch.object(build_all, "ROOT", root),
                patch.object(build_all, "APP_EXE", app),
                patch.object(build_all, "RELEASE_DIR", root / "release"),
                patch.object(build_all.subprocess, "run", return_value=type("Result", (), {"returncode": 0, "stdout": "commit123\n"})()),
            ):
                build_all.write_checksum_manifest("1.4.2", setup, launcher)
                build_all.write_build_manifest("1.4.2", setup, launcher, signed=False)
            manifest = json.loads((root / "release" / "build-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["git_commit"], "commit123")
            self.assertEqual(manifest["version"], "1.4.2")
            self.assertFalse(manifest["authenticode_verified"])
            self.assertEqual(len(manifest["artifacts"]), 3)
            self.assertTrue(all(not Path(entry["path"]).is_absolute() for entry in manifest["artifacts"]))
            checksums = (root / "release" / "SHA256SUMS.txt").read_text(encoding="utf-8")
            self.assertIn(setup.name, checksums)
            self.assertIn(launcher.name, checksums)


if __name__ == "__main__":
    unittest.main()
