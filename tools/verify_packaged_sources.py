"""Inspect PyInstaller archives without executing the app or touching settings."""
from __future__ import annotations

import argparse
import marshal
import sys
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.app_identity import APP_EXE, LAUNCHER_BASENAME


def code_signature(code: types.CodeType) -> tuple:
    """Compare bytecode/metadata recursively, ignoring only build-machine filenames."""
    constants = tuple(code_signature(item) if isinstance(item, types.CodeType) else item
                      for item in code.co_consts)
    return (code.co_code, constants, code.co_names, code.co_varnames, code.co_freevars,
            code.co_cellvars, code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount,
            code.co_flags, code.co_stacksize, code.co_nlocals, code.co_name, code.co_qualname,
            code.co_firstlineno, code.co_linetable, code.co_exceptiontable)


def verify_code(code: types.CodeType, source: Path) -> None:
    compiled = compile(source.read_bytes(), str(source), "exec", dont_inherit=True, optimize=0)
    if code_signature(code) != code_signature(compiled):
        raise ValueError(f"Packaged source mismatch: {source.relative_to(ROOT)}")


def inspect_package(exe: Path, *, launcher: bool = False) -> int:
    archive = CArchiveReader(str(exe))
    pyz_name = next(name for name in archive.toc if name.endswith(".pyz"))
    pyz = archive.open_embedded_archive(pyz_name)
    count = 0
    for name in pyz.toc:
        if name != "src" and not name.startswith("src."):
            continue
        path = ROOT.joinpath(*name.split("."))
        source = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
        code = pyz.extract(name)
        if code is None and path.is_dir() and not source.exists():
            continue  # Namespace packages contain no executable source code.
        if not source.is_file():
            raise ValueError(f"Packaged project module has no current source: {name}")
        verify_code(code, source)
        count += 1
    main_name = LAUNCHER_BASENAME if launcher else "main"
    main_source = ROOT / "scripts" / f"{LAUNCHER_BASENAME}.pyw" if launcher else ROOT / "src" / "main.py"
    verify_code(marshal.loads(archive.extract(main_name)), main_source)
    count += 1
    if not launcher:
        for filename in ("icon.ico", "icon.png"):
            entry = next(name for name in archive.toc if name.replace("\\", "/") == f"assets/{filename}")
            if archive.extract(entry) != (ROOT / "assets" / filename).read_bytes():
                raise ValueError(f"Bundled icon mismatch: {filename}")
    print(f"Package sources match ({count} modules), icons checked={not launcher}: {exe.name}")
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path, nargs="?", default=ROOT / "dist" / APP_EXE)
    parser.add_argument("--launcher", action="store_true")
    args = parser.parse_args()
    inspect_package(args.exe, launcher=args.launcher)
