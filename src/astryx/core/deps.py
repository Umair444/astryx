#!/usr/bin/env python3
"""astryx · the ONE Python-dependency authority (plan-19).

The missing declaration (plan-17 materialize-first, lifted from units to deps):
src/astryx/data/deps.conf lists every third-party package the repo needs, grouped. install
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
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
import ast
import sys
from pathlib import Path

REPO = repo_root(__file__)
MANIFEST = repo_root(__file__) / "src/astryx/data/deps.conf"


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
        # rglob, not glob: a package dir whose python lives only in SUBdirs is still
        # first-party. `triggers/` holds no top-level .py (every body is triggers/<agent>/),
        # so a non-recursive probe missed it and steward's `from triggers.steward.bands`
        # read as an undeclared third-party dep. Only bites where the ignored trigger
        # bodies exist on disk — i.e. locally, never in a fresh CI checkout — which is
        # exactly the drift that makes a local run disagree with CI.
        if p.is_dir() and p.name not in (".git", "venv") and any(p.rglob("*.py")):
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


_OPS = ("==", ">=", "<=", "!=", ">", "<")      # the operators judged; anything else is UNJUDGEABLE, never satisfied


def _vtuple(v: str) -> tuple | None:
    """'1.28.1' -> (1, 28, 1); a release segment that isn't plain digits (1.0rc1, a local +tag) -> None."""
    parts = v.split("+")[0].split(".")
    return tuple(int(x) for x in parts) if all(x.isdigit() for x in parts) else None


def _cmp(a: tuple, b: tuple) -> int:
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def spec_problem(pip_spec: str, version_of=None) -> str | None:
    """None when the INSTALLED distribution satisfies pip_spec's version constraints (a spec with none is satisfied
    by presence, which _import_ok judges); else why not. Presence alone can't see a wrong major: mcp 2.x is
    importable as `mcp` yet removed mcp.server.fastmcp (a2 #54114). Compared without `packaging`, which core doesn't
    carry. Fail-closed (a2 #54126): an operator, marker or version this reader can't judge is a problem, never a pass."""
    import importlib.metadata as md
    import re
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?(.*)$", pip_spec.strip())
    if not m:
        return f"unjudgeable spec {pip_spec!r}"
    dist, rest = m.group(1), m.group(3).strip()
    if not rest:
        return None
    if ";" in rest or "@" in rest:
        return f"unjudgeable spec {pip_spec!r} (a marker or URL)"
    try:
        have = (version_of or md.version)(dist)
    except Exception:                                   # noqa: BLE001
        return f"{dist}: no installed distribution metadata to judge {rest}"
    hv = _vtuple(have)
    if hv is None:
        return f"{dist} {have}: a version this reader can't compare against {rest}"
    for clause in rest.split(","):
        clause = clause.strip()
        op = next((o for o in _OPS if clause.startswith(o)), None)
        if op is None or clause.startswith(("~=", "===")):
            return f"unjudgeable clause {clause!r} in {pip_spec!r}"
        want = _vtuple(clause[len(op):].strip())
        if want is None:
            return f"unjudgeable version in {clause!r} of {pip_spec!r}"
        c = _cmp(hv, want)
        ok = {"==": c == 0, "!=": c != 0, ">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0}[op]
        if not ok:
            return f"{dist} {have} does not satisfy {clause}"
    return None


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
        wrong = [(pip, why) for g in want for (pip, imp) in groups.get(g, [])
                 if _import_ok(imp) and (why := spec_problem(pip))]
        for pip, imp in missing:
            print(f"missing: {imp} (pip install {pip})", file=sys.stderr)
        for pip, why in wrong:
            print(f"wrong version: {why} (pip install '{pip}')", file=sys.stderr)
        return 1 if missing or wrong else 0

    if verb == "coverage":
        gaps = coverage_gaps()
        if gaps:
            print("UNDECLARED third-party imports (add to src/astryx/data/deps.conf):",
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
