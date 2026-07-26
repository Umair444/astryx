#!/usr/bin/env python3
"""astryx · the ONE Python-dependency authority (plan-19).

The missing declaration (plan-17 materialize-first, lifted from units to deps):
nucleus/deps.conf lists every third-party package the repo needs, grouped. install
derives FROM it, doctor asserts FROM it — one authority, so the two hand-snapshots
that had drifted (init.sh install vs doctor check, which even disagreed with each
other and both missed av/faster_whisper) can't exist. Groups:
  core            — always installed.
  <optional-group> — installed only when its gating capability is present (media when
                     any channel routes voice; keyed on the SAME channels/grants
                     authority the units-generator uses).

deps.conf line:  <group> | <pip-spec> | <import-root>
(pip-spec is what pip installs — may carry extras/rename, e.g. `psycopg[binary]`,
`uvicorn[standard]`, `pynacl`; import-root is the top-level module — `psycopg`,
`uvicorn`, `nacl`. The two differ often; the manifest is where that mapping lives.)

CLI (init.sh shells here — one authority, no shell copy):
  deps.py install-list <group...>   pip-specs for the given groups (default: core)
  deps.py check <group...>          exit 0 iff every import-root imports; else lists
  deps.py coverage                  exit 0 iff every third-party import in the repo is
                                    declared in SOME group; else lists the undeclared
                                    (AST-derived, third-party = ∉ stdlib ∉ first-party)
  deps.py groups                    the group names in the manifest
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).resolve().parent / "deps.conf"


def parse() -> dict:
    """group -> list of (pip_spec, import_root)."""
    groups: dict = {}
    if not MANIFEST.exists():
        return groups
    for line in MANIFEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            continue
        grp, pip_spec, import_root = parts
        groups.setdefault(grp, []).append((pip_spec, import_root))
    return groups


def _first_party_roots(root: Path = REPO) -> set:
    """Import roots that resolve to a file INSIDE the repo — never a dependency. A
    module's own stem (bridges/transcribe.py → `transcribe`, imported as `transcribe`
    from within bridges/) and every top-level package dir count."""
    roots = set()
    for p in root.rglob("*.py"):
        if ".git" in p.parts or "venv" in p.parts:
            continue
        roots.add(p.stem)
    for p in root.iterdir():
        if p.is_dir() and p.name not in (".git", "venv") and any(p.glob("*.py")):
            roots.add(p.name)
    return roots


def _imported_roots(root: Path = REPO) -> set:
    """Every top-level module imported anywhere in the repo, by AST (NOT grep — a
    function-local `from faster_whisper import ...` is invisible to a `^import` grep;
    transcribe.py:33 is exactly that). Relative imports (level>0) are first-party."""
    roots = set()
    for p in root.rglob("*.py"):
        if ".git" in p.parts or "venv" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    roots.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    roots.add(node.module.split(".")[0])
    return roots


def declared_roots() -> set:
    return {imp for specs in parse().values() for (_, imp) in specs}


def coverage_gaps(root: Path = REPO, declared: set | None = None) -> list:
    """Third-party import roots used in `root` but declared in NO group. DERIVES
    third-party = imported ∧ ∉ stdlib ∧ ∉ first-party — never a hand-list, so the
    drift-catcher cannot itself drift."""
    stdlib = set(sys.stdlib_module_names)
    first_party = _first_party_roots(root)
    declared = declared_roots() if declared is None else declared
    gaps = set()
    for r in _imported_roots(root):
        if r in stdlib or r in first_party:
            continue                      # not a third-party dependency
        if r not in declared:
            gaps.add(r)                   # third-party, imported, undeclared
    return sorted(gaps)


def _import_ok(root: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(root) is not None
    except Exception:
        return False


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__.strip().splitlines()[0]); return 2
    verb, rest = args[0], args[1:]
    groups = parse()

    if verb == "install-list":
        want = rest or ["core"]
        specs = [pip for g in want for (pip, _) in groups.get(g, [])]
        print(" ".join(specs)); return 0

    if verb == "check":
        want = rest or ["core"]
        missing = [(pip, imp) for g in want for (pip, imp) in groups.get(g, [])
                   if not _import_ok(imp)]
        if missing:
            for pip, imp in missing:
                print(f"missing: {imp} (pip install {pip})", file=sys.stderr)
            return 1
        return 0

    if verb == "coverage":
        gaps = coverage_gaps()
        if gaps:
            print("UNDECLARED third-party imports (add to nucleus/deps.conf):",
                  file=sys.stderr)
            for g in gaps:
                print(f"  {g}", file=sys.stderr)
            return 1
        return 0

    if verb == "groups":
        print(" ".join(sorted(groups))); return 0

    print(f"unknown verb: {verb}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
