import importlib.util
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


build_all = load_module("build_all_release_layout", ROOT / "tools" / "build_all.py")
diagnose_install = load_module("diagnose_install_release_layout", ROOT / "tools" / "diagnose_install.py")


class ReleaseLayoutTests(unittest.TestCase):
    def test_release_sources_and_artifacts_have_one_home(self):
        version = "1.2.3"
        self.assertEqual(build_all.LAUNCHER_SOURCE, ROOT / "tools" / "App05_FileOps.pyw")
        self.assertEqual(
            build_all.setup_exe_path(version),
            ROOT / "release" / "IntegratedDataTool_Setup_v1.2.3.exe",
        )
        self.assertEqual(
            build_all.launcher_exe_path(version),
            ROOT / "release" / "App05_FileOps_v1.2.3.exe",
        )
        self.assertEqual(
            diagnose_install.setup_exe_path(),
            ROOT / "release" / f"IntegratedDataTool_Setup_v{diagnose_install.APP_VERSION}.exe",
        )
        self.assertEqual(
            diagnose_install.launcher_exe_path(),
            ROOT / "release" / f"App05_FileOps_v{diagnose_install.APP_VERSION}.exe",
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


if __name__ == "__main__":
    unittest.main()
