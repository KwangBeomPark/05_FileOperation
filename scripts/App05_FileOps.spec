# Compatibility entry point; use installer/App05_FileOps.spec for new builds.
from pathlib import Path

canonical_spec = Path(SPECPATH).parent / "installer" / "App05_FileOps.spec"
exec(compile(canonical_spec.read_text(encoding="utf-8"), str(canonical_spec), "exec"))
