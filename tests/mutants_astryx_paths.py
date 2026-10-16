"""Mutants for src/astryx/paths.py's rung 1 (a2 #52637, plan-10224 BC-A). The oracle is test_astryx_paths: a checkout
honours ASTRYX_HOME only when it names that checkout, a wheel always does."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "src" / "astryx" / "paths.py"
ORACLE = REPO / "tests" / "test_astryx_paths.py"
ENV = "PATHS_SRC"
MUTANTS = {
    "H1 rung 1 unconditional (a worktree in a live shell resolves to the live org)":
        ("        if root is None or root.resolve() == h:\n            return h, \"env\"",
         "        return h, \"env\""),
    "H2 env honoured only for a matching checkout (a wheel install loses its only authority)":
        ("        if root is None or root.resolve() == h:", "        if root is not None and root.resolve() == h:"),
    "H3 env honoured only for a wheel (the live checkout's own ASTRYX_HOME is ignored)":
        ("        if root is None or root.resolve() == h:", "        if root is None:"),
}
