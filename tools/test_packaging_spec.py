"""Compile both spec entry points without building or touching release assets."""

import os
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PackagingSpecTests(unittest.TestCase):
    def test_canonical_and_compatibility_specs_resolve_identical_inputs(self):
        results = []
        with tempfile.TemporaryDirectory() as temporary:
            resource = Path(temporary) / "version.txt"
            resource.write_text("fixture", encoding="utf-8")
            for relative in ("installer/App05_FileOps.spec", "scripts/App05_FileOps.spec"):
                calls = {}

                def analysis(inputs, _calls=calls, **kwargs):
                    _calls["inputs"] = inputs
                    _calls["analysis"] = kwargs
                    return SimpleNamespace(pure=[], zipped_data=[], scripts=[], binaries=[], zipfiles=[], datas=[])

                def exe(*args, _calls=calls, **kwargs):
                    _calls["exe"] = kwargs

                hooks = SimpleNamespace(collect_all=lambda name: ([], [], []))
                with patch.dict(os.environ, {"FILEOPS_VERSION_FILE": str(resource)}), patch.dict(
                    "sys.modules", {"PyInstaller.utils.hooks": hooks},
                ):
                    spec = ROOT / relative
                    runpy.run_path(str(spec), init_globals={
                        "SPECPATH": str(spec.parent), "Analysis": analysis,
                        "PYZ": lambda *a, **kw: None, "EXE": exe,
                    })
                self.assertEqual(calls["inputs"], [str(ROOT / "src" / "main.py")])
                self.assertEqual(calls["analysis"]["pathex"], [str(ROOT)])
                self.assertEqual(calls["exe"]["name"], "App05_FileOps")
                self.assertEqual(calls["exe"]["icon"], str(ROOT / "assets" / "icon.ico"))
                self.assertEqual(calls["exe"]["version"], str(resource))
                results.append(calls)
        self.assertEqual(results[0], results[1])
