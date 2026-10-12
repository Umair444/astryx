"""A throwaway repo tree for the plan-9853 oracles (tests/test_trigger_names.py, tests/test_init_trigger_names.py).

It holds what the shipped triggers' import closures reach (astryx.py, nucleus/, mcp/phone/surface.py), the helper under
test (the caller's helper_src: a mutant under the probe) as nucleus/trigger_names.py, the pulse as nucleus/pulse.py (so
`pulse.py --names` discovers THIS tree, the parity oracle), venv/bin/python execing this interpreter, and an empty
triggers/.
No .env: the helper must be import-safe without one (a4 #49617); a caller wanting a database sets ASTRYX_DSN.
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def build(root: Path, helper_src: str | None = None) -> Path:
    """helper_src: the trigger_names.py to place (the oracle passes its TRIGGER_NAMES_SRC seam); default the repo's."""
    shutil.copy(REPO / "astryx.py", root / "astryx.py")
    shutil.copytree(REPO / "nucleus", root / "nucleus", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy(helper_src or REPO / "nucleus/trigger_names.py", root / "nucleus" / "trigger_names.py")
    (root / "mcp" / "phone").mkdir(parents=True)
    shutil.copy(REPO / "mcp/phone/surface.py", root / "mcp/phone/surface.py")
    (root / "venv" / "bin").mkdir(parents=True)
    py = root / "venv" / "bin" / "python"             # a wrapper, not a symlink: a symlinked venv python with no
    py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')   # pyvenv.cfg beside it runs as the bare base python
    py.chmod(0o755)
    (root / "triggers").mkdir()
    return root


def shim(module: str) -> str:
    """The init.sh shim's import line for a shipped trigger."""
    return f"from nucleus.shipped_triggers.{module} import {module}  # noqa: F401\n"
