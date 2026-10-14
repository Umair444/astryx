#!/usr/bin/env python3
"""Apply the goal 10224 S4 reorg: nucleus/ -> src/astryx/<sub>/, devtools/, scripts/, driven by devtools/reorg/map.tsv.

    python3 devtools/reorg/apply.py            # from the root of a clean checkout; idempotent (a second run changes nothing)
    python3 devtools/reorg/apply.py --check    # report what is still to do, change nothing (rc 1 if anything is)

What it does, in order (each step skips what is already done):
  1. `git mv` every mapped file to its new path, and adds the new subpackages' __init__.py.
  2. Rewrites every TRACKED text reference to a moved path (outside hooks/, channel/, mcp/, which keep reaching the old
     paths through the stubs): `nucleus/x.py` paths, `nucleus.x` dotted names, `from nucleus import x`, and
     `"nucleus" / "x.py"` path joins. The sqlguard ledger is re-serialized in its own canonical form.
  3. Routes each moved python module's repo root through astryx.paths.repo_root(), with a run-by-path bootstrap.
  4. Applies the PATCHES below: the hand-made edits a mechanical rewrite can't infer (data paths, unit generators,
     scanners that glob a directory). Each one is (file, old, new); a patch whose old text is gone and whose new
     text isn't there fails the run loudly, so a newer main that drifted under a patch is never patched blind.
  5. Writes a stub at every old path: python (a sys.modules alias; runpy as __main__), shell (exec, or source when
     sourced), and a relative symlink for a data file.
  6. `git add`s exactly the paths it touched, and prints a summary. It never commits.

It reads nothing gitignored, and needs only python3 and git.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAP = "devtools/reorg/map.tsv"
NEVER_REWRITE = ("hooks/", "channel/", "mcp/", "devtools/reorg/", "tests/test_reorg_roots.py",
                 "src/astryx/_reorg.py")
STAMP_DIR = "var/reorg_stubs"


# ── the map ──────────────────────────────────────────────────────────────────────────────────────────────────────

def load_map(root: Path):
    files, dirs = [], []
    for line in (root / MAP).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        old, new, mod = line.split("\t")
        (dirs if old.endswith("/") else files).append((old, new, None if mod == "-" else mod))
    return files, dirs


class Rewriter:
    def __init__(self, files, dirs):
        self.paths = {o[len("nucleus/"):].rstrip("/"): n.rstrip("/") for o, n, _ in files + dirs}
        self.mods = {}                                     # first dotted component under nucleus -> new dotted
        for o, n, m in files + dirs:
            rel = o[len("nucleus/"):].rstrip("/")
            if m and "/" not in rel:
                self.mods[rel[:-3] if rel.endswith(".py") else rel] = m
        alt = "|".join(re.escape(k) for k in sorted(self.paths, key=len, reverse=True))
        self.path_re = re.compile(r"(?<!\w)nucleus/(" + alt + r")(?![\w-]|\.\w)")
        malt = "|".join(re.escape(k) for k in sorted(self.mods, key=len, reverse=True))
        self.dot_re = re.compile(r"(?<![\w.])nucleus\.(" + malt + r")(?!\w)")
        name = r"\w+(?:[ \t]+as[ \t]+\w+)?"
        self.from_re = re.compile(r"\bfrom nucleus import (\([^)]*\)|" + name + r"(?:[ \t]*,[ \t]*" + name + r")*)")
        self.join_re = re.compile(r"""(["'])nucleus\1((?:\s*/\s*(["'])[\w.\-]+\3)+)""")
        self.unknown: set[str] = set()

    def _from(self, m):
        body = m.group(1)
        comment = ""
        if body.startswith("("):
            body = re.sub(r"#[^\n]*", "", body)
        names = [n.strip() for n in body.strip().strip("()").replace("\n", " ").split(",") if n.strip()]
        groups: dict[str, list[str]] = {}
        for n in names:
            base = n.split()[0]
            tgt = self.mods.get(base)
            if tgt is None:
                self.unknown.add(base)
                return m.group(0)
            pkg, leaf = tgt.rsplit(".", 1)
            groups.setdefault(pkg, []).append(leaf + n[len(base):])
        return "; ".join(f"from {p} import {', '.join(ns)}" for p, ns in groups.items()) + comment.rstrip()

    def _join(self, m):
        q = m.group(1)
        parts = re.findall(r"""(\s*/\s*)(["'])([\w.\-]+)\2""", m.group(2))
        names = [p[2] for p in parts]
        for k in range(len(names), 0, -1):
            new = self.paths.get("/".join(names[:k]))
            if new:
                segs = new.split("/") + names[k:]
                sep = parts[0][0]
                return q + (q + sep + q).join(segs) + q
        return m.group(0)

    MKDIR_RE = re.compile(r'^([ \t]*)\(((?:\w[\w.]*)(?:\([^()\n]*\))?) / "nucleus"\)\.mkdir\(([^)\n]*)\)[ \t]*$', re.M)

    def fake_tree_dirs(self, text: str) -> str:
        """An oracle that builds a fake repo makes `<tmp>/nucleus` and then writes files at their (rewritten) new
        paths: give it the new directories too, on the line after (only in tests/, only this exact statement shape)."""
        dirs = sorted({n.rsplit("/", 1)[0] for n in self.paths.values() if "/" in n})
        tup = "(" + ", ".join(f'"{d}"' for d in dirs) + ")"

        def add(m):
            if f'for _d in {tup}' in text[m.end():m.end() + 2 * len(tup) + 200]:
                return m.group(0)
            return (m.group(0) + f"\n{m.group(1)}for _d in {tup}:  # goal 10224 S4: the moved tree's dirs\n"
                    f"{m.group(1)}    ({m.group(2)} / _d).mkdir(parents=True, exist_ok=True)")
        return self.MKDIR_RE.sub(add, text)

    BARE_RE = re.compile(r"^([ \t]*)import nucleus([ \t]*#[^\n]*)?$", re.M)

    def bare_import(self, text: str) -> str:
        """`import nucleus` then `nucleus.x = mutant` (rewritten to `astryx.<sub>.x = mutant`): import the subpackages
        that the file then assigns into, so the attribute path exists."""
        subs = sorted(set(re.findall(r"\bastryx\.(\w+)\.\w+ = ", text)))
        if not subs:
            return text
        return self.BARE_RE.sub(lambda m: "; ".join(f"import astryx.{s}" for s in subs).join(
            (m.group(1), m.group(2) or "")), text)

    SH_MKDIR_RE = re.compile(r'^(.*\bmkdir -p .*?)"([^"\s]*)/nucleus"(?! "\2/scripts")', re.M)

    def shell_dirs(self, text: str) -> str:
        """A shell oracle's `mkdir -p "$T/root/nucleus"` gains the moved tree's top dirs (scripts/, devtools/)."""
        return self.SH_MKDIR_RE.sub(lambda m: f'{m.group(1)}"{m.group(2)}/nucleus" "{m.group(2)}/scripts" '
                                              f'"{m.group(2)}/devtools"', text)

    KEEP = "reorg: keep"          # a line carrying this marker names an OLD path on purpose (a stub's caller)

    def rewrite(self, text: str) -> str:
        if self.KEEP in text:
            lines = text.split("\n")
            kept = {i: ln for i, ln in enumerate(lines) if self.KEEP in ln}
            out = self._rewrite("\n".join("\0KEEP%d\0" % i if i in kept else ln for i, ln in enumerate(lines)))
            return re.sub("\0KEEP(\\d+)\0", lambda m: kept[int(m.group(1))], out)
        return self._rewrite(text)

    def _rewrite(self, text: str) -> str:
        text = self.from_re.sub(self._from, text)
        text = self.join_re.sub(self._join, text)
        text = self.path_re.sub(lambda m: self.paths[m.group(1)], text)
        text = self.dot_re.sub(lambda m: self.mods[m.group(1)], text)
        return self.bare_import(text)


# ── repo root routing for moved python modules ───────────────────────────────────────────────────────────────────

BOOT = ('if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)\n'
        '    import sys as _sys, os as _os\n'
        '    _sys.path.insert(0, {chain})\n'
        'from astryx.paths import repo_root  # noqa: E402\n')


def _chain(depth: int) -> str:
    s = "_os.path.realpath(__file__)"
    for _ in range(depth):
        s = f"_os.path.dirname({s})"
    return s


def _insert_at(text: str) -> int:
    """Offset just past the module docstring and any `from __future__` lines (and a shebang/encoding header)."""
    import ast
    tree = ast.parse(text)
    end_line = 0
    body = tree.body
    i = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        end_line = body[0].end_lineno
        i = 1
    while i < len(body) and isinstance(body[i], ast.ImportFrom) and body[i].module == "__future__":
        end_line = body[i].end_lineno
        i += 1
    lines = text.splitlines(keepends=True)
    if end_line == 0:
        n = 0
        while n < len(lines) and lines[n].startswith("#"):
            n += 1
        return sum(len(x) for x in lines[:n])
    return sum(len(x) for x in lines[:end_line])


def route_root(text: str, old_depth: int, new_depth: int) -> str:
    """Every `Path(__file__)...parents[old_depth-? ]` root expression -> repo_root(), plus the bootstrap import."""
    pats = [rf"Path\(__file__\)\.resolve\(\)\.parents\[{old_depth}\]"]
    if old_depth == 1:
        pats.append(r"Path\(__file__\)\.resolve\(\)\.parent\.parent(?!\.)")
    new = text
    for p in pats:
        new = re.sub(p, "repo_root(__file__)", new)
    if "repo_root(__file__)" in new and "from astryx.paths import repo_root" not in new:
        at = _insert_at(new)
        boot = BOOT.format(chain=_chain(new_depth + 1))
        sep = "" if at == 0 or new[at - 1] == "\n" else "\n"
        new = new[:at] + sep + boot + new[at:]
    return new


# Moved modules that must import NOTHING from the repo, so they keep their own root computation (unchanged depth).
ROOT_EXEMPT = {
    "devtools/branch_check_sandbox.py": "ships ITSELF into the sandbox as /run/bc_probe.py, alone",
}


# ── hand patches: (file AFTER the move, old text, new text) ──────────────────────────────────────────────────────
# Applied after the mechanical rewrite and root routing, so `old` is written in post-rewrite terms.

PATCHES: list[tuple[str, str, str]] = [
    # data files are read beside their reader today; they now live in astryx/data and astryx/sql
    ("src/astryx/core/copies.py",
     'Path(__file__).resolve().parent / "copies.json"', 'repo_root(__file__) / "src/astryx/data/copies.json"'),
    ("src/astryx/core/deps.py",
     'Path(__file__).resolve().parent / "deps.conf"', 'repo_root(__file__) / "src/astryx/data/deps.conf"'),
    ("src/astryx/security/secretset.py",
     'Path(__file__).resolve().parent / "secret_holders.json"', 'repo_root(__file__) / "src/astryx/data/secret_holders.json"'),
    # the sqlguard shim is loaded as `sitecustomize` before any import machinery: it walks to the root itself
    ("src/astryx/security/sqlguard/shim/sitecustomize.py",
     'os.path.join(os.path.dirname(__file__), "..", "..", "..")',
     'os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")'),
    # generated units run modules by name from the checkout root, with HOME explicit (plan-10224 S4)
    ("init.sh", "ExecStart=$PWD/venv/bin/python $PWD/src/astryx/pulse/pulse.py",
     "ExecStart=$PWD/venv/bin/python -m astryx.pulse.pulse"),
    ("init.sh", "ExecStart=$PWD/venv/bin/python $PWD/src/astryx/pulse/senses.py",
     "ExecStart=$PWD/venv/bin/python -m astryx.pulse.senses"),
    ("init.sh", "ExecStart=$PWD/venv/bin/python $PWD/src/astryx/contrib/growbot_body.py",
     "ExecStart=$PWD/venv/bin/python -m astryx.contrib.growbot_body"),
    # residents carry ASTRYX_HOME explicitly: the tmux body, the settings env, and the channel server's env
    ("scripts/spawn.sh", 'tmux new-session -d -s "$SESS" -c "$HOME_D"',
     'tmux new-session -d -s "$SESS" -c "$HOME_D" -e "ASTRYX_HOME=$ROOT"'),
    ("scripts/spawn.sh", '"env": { "ASTRYX_AGENT": "$AGENT"$TENV$RENV },',
     '"env": { "ASTRYX_AGENT": "$AGENT", "ASTRYX_HOME": "$ROOT"$TENV$RENV },'),
    ("scripts/spawn.sh", '    "env": { "ASTRYX_AGENT": "$AGENT" }\n',
     '    "env": { "ASTRYX_AGENT": "$AGENT", "ASTRYX_HOME": "$ROOT" }\n'),
    # the census of this reorg runs in the org's gate
    ("devtools/check.sh",
     'run "astryx config: the one .env reader, in-place 0600 writer" "$PY" tests/test_astryx_config.py\n',
     'run "astryx config: the one .env reader, in-place 0600 writer" "$PY" tests/test_astryx_config.py\n'
     'run "reorg census: moved roots are the repo root, every stub IS its module" "$PY" tests/test_reorg_roots.py\n'),
    # scanners that turn a dotted module into a file: astryx.* lives under src/, a moved nucleus.* where it went
    ("src/astryx/core/toolreg.py", 'TOOL_ROOTS = ("nucleus/", "skills/", "mcp/")',
     'TOOL_ROOTS = ("nucleus/", "src/astryx/", "scripts/", "devtools/", "skills/", "mcp/")'),
    ("src/astryx/core/toolreg.py", "from astryx.paths import repo_root  # noqa: E402",
     "from astryx.paths import repo_root, module_relpath  # noqa: E402\n"
     "try:\n"
     "    from astryx._reorg import MOVED as _MOVED   # a stub's id is its moved script's id (goal 10224 S4)\n"
     "except ImportError:\n"
     "    _MOVED = {}"),
    ("src/astryx/core/toolreg.py",
     "    p = os.path.normpath(p)\n    if p.startswith(\"..\") or not p.startswith(TOOL_ROOTS):",
     "    p = os.path.normpath(p)\n    p = _MOVED.get(p, p)\n    if p.startswith(\"..\") or not p.startswith(TOOL_ROOTS):"),
    ("src/astryx/core/toolreg.py", '        cand = tok.replace(".", "/") + ".py"',
     '        cand = module_relpath(tok)'),
    ("src/astryx/security/sqlguard/inventory.py", "from astryx.paths import repo_root  # noqa: E402",
     "from astryx.paths import repo_root  # noqa: E402\n"
     "try:\n"
     "    from astryx.paths import module_relpath as _modrel\n"
     "except ImportError:                       # a judge tree from before goal 10224 S4\n"
     "    def _modrel(d, package=False):\n"
     "        return d.replace('.', '/') + ('/__init__.py' if package else '.py')"),
    ("src/astryx/security/sqlguard/inventory.py", 'src = REPO / (st.module.replace(".", "/") + ".py")',
     'src = REPO / _modrel(st.module)'),
    ("src/astryx/security/sqlguard/inventory.py", 'src = REPO / (a.name.replace(".", "/") + ".py")',
     'src = REPO / _modrel(a.name)'),
    ("src/astryx/security/sqlguard/inventory.py",
     'src = REPO / (n.module.replace(".", "/") + "/" + a.name + ".py")',
     'src = REPO / _modrel(n.module + "." + a.name)'),
    ("devtools/branch_check.py", "def module_refs(tree) -> set:",
     "def _modfile(m: str, package: bool = False) -> str:\n"
     "    \"\"\"dotted -> repo-relative file: astryx.* lives under src/, a moved nucleus.* where it went (goal 10224 S4).\"\"\"\n"
     "    try:\n"
     "        from astryx.paths import module_relpath\n"
     "        return module_relpath(m, package)\n"
     "    except ImportError:\n"
     "        return m.replace(\".\", \"/\") + (\"/__init__.py\" if package else \".py\")\n\n\n"
     "def module_refs(tree) -> set:"),
    ("devtools/branch_check.py", 'f = repo / (mod.replace(".", "/") + ".py" if mod else path)',
     'f = repo / (_modfile(mod) if mod else path)'),
    ("devtools/branch_check.py", '    mod = site_path[:-3].replace("/", ".")',
     '    mod = site_path[:-3].replace("/", ".")\n'
     '    mod = mod[len("src."):] if mod.startswith("src.astryx.") else mod'),
    ("devtools/branch_check.py", 'files = {toks[i + 1].replace(".", "/") + ".py" for i, t in enumerate(toks[:-1]) if t == "-m"}',
     'files = {_modfile(toks[i + 1]) for i, t in enumerate(toks[:-1]) if t == "-m"}'),
    ("devtools/branch_check.py", 'for c in (m.replace(".", "/") + ".py", m.replace(".", "/") + "/__init__.py"):',
     'for c in (_modfile(m), _modfile(m, package=True)):'),
    ("devtools/branch_check.py", '        out |= {m.replace(".", "/") + ".py" for m in module_refs(tree)}',
     '        out |= {_modfile(m) for m in module_refs(tree)}'),
    ("tests/mutants_branch_check.py", '''('        out |= {m.replace(".", "/") + ".py" for m in module_refs(tree)}', "        pass"),''',
     '''('        out |= {_modfile(m) for m in module_refs(tree)}', "        pass"),'''),
    # fake trees: the astryx spine where a fake repo runs astryx.* modules
    ("tests/test_sqlguard.py",
     '    (tmp / "nucleus" / "__init__.py").write_text("")\n'
     '    for f in ("pulse_run.py", "schema.sql"):\n'
     '        shutil.copy2(REPO / "nucleus" / f, tmp / "nucleus" / f)\n',
     '    from _astryx_skel import skeleton                # goal 10224 S4: astryx.* needs its spine in the fake repo\n'
     '    skeleton(tmp, "src/astryx/security/__init__.py", "src/astryx/pulse/pulse_run.py", "src/astryx/sql/schema.sql")\n'),
    ("tests/test_sqlguard_rekey.py", '        (r / "nucleus" / "__init__.py").write_text("")\n',
     '        Path.mkdir(r / "nucleus")\n'
     '        from _astryx_skel import skeleton            # goal 10224 S4: astryx.* needs its spine in the fake repo\n'
     '        skeleton(r, "src/astryx/security/__init__.py")\n'),
    ("tests/test_branch_check.py", '    for d in ("nucleus", "tests", "channel"):',
     '    for d in ("nucleus", "tests", "channel", "devtools"):'),
    ("tests/test_branch_check.py", '    for d in ("nucleus", "tests", "units"):',
     '    for d in ("nucleus", "tests", "units", "devtools"):'),
    ("tests/test_sqlguard.py",
     '    shutil.copytree(tmp / "nucleus", bare / "nucleus", ignore=shutil.ignore_patterns("__pycache__"))\n',
     '    shutil.copytree(tmp / "src", bare / "src", ignore=shutil.ignore_patterns("__pycache__"))   # goal 10224 S4\n'
     '    shutil.copy2(tmp / "astryx.py", bare / "astryx.py")\n'),
    ("tests/test_branch_check_prep.py", '    (live / "nucleus" / "__init__.py").write_text("")\n',
     '    from _astryx_skel import skeleton                  # goal 10224 S4: the astryx spine in the fake repo\n'
     '    skeleton(live, "src/astryx/security/__init__.py")\n'
     '    Path.mkdir(live / "src" / "astryx" / "sql", parents=True, exist_ok=True)\n'),
    ("tests/test_astryx_cli.py",
     '    f = Fake()\n    rc, o = call(["federate"] + H, f)\n'
     '    arm("federate without src/astryx/federation/federate.py says it\'s coming, rc 0", rc == 0 and "coming" in o, o)\n'
     '    (h / "nucleus" / "__init__.py").write_text("")\n'
     '    (h / "src" / "astryx" / "federation" / "federate.py").write_text(\n'
     '        "import pathlib\\ndef main(argv):\\n    pathlib.Path(%r).write_text(repr(argv))\\n    return 0\\n"\n'
     '        % str(h / "fed.out"))\n'
     '    for k in [k for k in sys.modules if k == "nucleus" or k.startswith("nucleus.")]:\n'
     '        del sys.modules[k]\n',
     '    # goal 10224 S4: the wizard ships IN the package (astryx.federation.federate), so "not there yet" can\'t\n'
     '    # happen. The fake is a module object in its place, never the real wizard (it would knock on the live relay).\n'
     '    import types\n'
     '    fake = types.ModuleType("astryx.federation.federate")\n'
     '    fake.main = lambda argv: (h / "fed.out").write_text(repr(argv)) and 0\n'
     '    real_fed = sys.modules.get("astryx.federation.federate")\n'
     '    sys.modules["astryx.federation.federate"] = fake\n'),
    ("tests/test_astryx_cli.py",
     '    arm("an unknown flag on a NON-passthrough verb is still an error", rc != 0, (rc, o))\n'
     '    sys.path.remove(str(h))\n',
     '    arm("an unknown flag on a NON-passthrough verb is still an error", rc != 0, (rc, o))\n'
     '    sys.path.remove(str(h))\n'
     '    if real_fed is None:\n'
     '        sys.modules.pop("astryx.federation.federate", None)\n'
     '    else:\n'
     '        sys.modules["astryx.federation.federate"] = real_fed\n'),
    ("tests/test_tool_ledger.py",
     '    for e in (REPO / "nucleus").iterdir():\n'
     '        if e.name not in ("toolreg.py", "__pycache__"):\n'
     '            (t / "nucleus" / e.name).symlink_to(e)\n',
     '    from _astryx_skel import mirror                  # goal 10224 S4: the package linked, the stubs copied\n'
     '    mirror(t, skip=("src/astryx/core/toolreg.py",))\n'),
    ("tests/test_nudge.py",
     '    for e in (REPO / "nucleus").iterdir():\n'
     '        if e.name in ("charter.py", "tier.py"):\n'
     '            shutil.copy(e, t / "nucleus" / e.name)\n'
     '        elif e.name != "__pycache__":\n'
     '            (t / "nucleus" / e.name).symlink_to(e)\n',
     '    from _astryx_skel import mirror                  # goal 10224 S4: the package linked, the stubs copied\n'
     '    mirror(t, copy=("src/astryx/core/charter.py", "src/astryx/core/tier.py"))\n'),
    ("tests/test_spawn_wiring.py",
     '    for f in ("charter.py", "runtime_env.py"):          # both derive their paths from __file__\n'
     '        shutil.copy(REPO / "nucleus" / f, t / "nucleus" / f)\n',
     '    from _astryx_skel import mirror                     # goal 10224 S4: both derive their paths from __file__\n'
     '    mirror(t, copy=("src/astryx/core/charter.py", "src/astryx/core/runtime_env.py"), skip=("scripts/spawn.sh",))\n'),
    ("tests/test_git_env_isolation.py",
     '    shutil.copy(HOOK, main / "hooks" / "pre-push")\n    for rel, body in',
     '    shutil.copy(HOOK, main / "hooks" / "pre-push")\n'
     '    for s in ("pushed_tree_check.sh", "privacy_gate.sh"):   # hooks/pre-push still calls the nucleus/ stubs (S4)\n'
     '        shutil.copy2(REPO / "nucleus" / s, main / "nucleus" / s)\n'
     '    for rel, body in'),
    ("src/astryx/econ/legend_guard.py", 'SURFACE_ROOTS = ("mcp", "nucleus", "observatory/api")',
     'SURFACE_ROOTS = ("mcp", "nucleus", "src/astryx", "devtools", "observatory/api")'),
    ("src/astryx/econ/econ.py", 'K_ROOTS = ("nucleus", ',
     'K_ROOTS = ("nucleus", "src/astryx", "devtools", "scripts", '),
    ("tests/mutants_pre_push_contract.py",       # hooks/pre-push keeps calling the nucleus/ stub: its mutant too
     """        ('"$REPO/devtools/privacy_gate.sh" || exit 1',\n         '"$REPO/devtools/privacy_gate.sh" || true'),""",
     """        ('"$REPO/nucleus/privacy_gate.sh" || exit 1',  # reorg: keep (hooks/ calls the stub)\n"""
     """         '"$REPO/nucleus/privacy_gate.sh" || true'),  # reorg: keep"""),
    # reachability: its population is where the scripts live now, and a module's dotted name drops src/
    ("tests/test_reachability.py",
     '    return sorted(p for p in _git("ls-tree", "-r", "--name-only", "HEAD", "nucleus/")\n'
     '                  if p.endswith((".py", ".sh")))',
     '    # goal 10224 S4: nucleus/ moved into src/astryx/, devtools/ and scripts/. What stays in nucleus/ is the compat\n'
     '    # stubs, whose callers are gitignored or external by construction (their census: var/reorg_stubs/), so a\n'
     '    # stub is not a population member; nucleus/__init__.py still is.\n'
     '    return sorted(p for p in _git("ls-tree", "-r", "--name-only", "HEAD", "nucleus/", "src/astryx/", "devtools/",\n'
     '                                  "scripts/")\n'
     '                  if p.endswith((".py", ".sh")) and not _is_reorg_stub(p))\n\n\n'
     'def _is_reorg_stub(p):\n'
     '    try:\n'
     '        head = (REPO / p).read_text(errors="ignore")[:400]\n'
     '    except OSError:\n'
     '        return False\n'
     '    return p.startswith("nucleus/") and f"MOVED: {p} -> " in head'),
    ("tests/test_reachability.py",
     '    """-> (dotted module name, is_package_init), or (None, False) for a non-.py path."""\n'
     '    if path.endswith("/__init__.py"):',
     '    """-> (dotted module name, is_package_init), or (None, False) for a non-.py path."""\n'
     '    if path.startswith("src/astryx/"):              # goal 10224 S4: the package lives under src/\n'
     '        path = path[len("src/"):]\n'
     '    if path.endswith("/__init__.py"):'),
    ("tests/test_reachability.py",
     '    imp = (re.compile(rf"^\\s*(?:from\\s+(?:nucleus\\.)?{re.escape(stem)}\\s+import\\b"\n'
     '                      rf"|import\\s+(?:nucleus\\.)?{re.escape(stem)}\\b"\n'
     '                      rf"|from\\s+nucleus\\s+import\\s+(?:[\\w,\\s]*\\b){re.escape(stem)}\\b)")',
     '    imp = (re.compile(rf"^\\s*(?:from\\s+(?:nucleus\\.|astryx\\.[\\w.]+\\.)?{re.escape(stem)}\\s+import\\b"\n'
     '                      rf"|import\\s+(?:nucleus\\.|astryx\\.[\\w.]+\\.)?{re.escape(stem)}\\b"\n'
     '                      rf"|from\\s+(?:nucleus|astryx\\.[\\w.]+)\\s+import\\s+(?:[\\w,\\s]*\\b){re.escape(stem)}\\b)")'),
    ("tests/test_reachability.py",
     '     [("tests/test_x.py", "from astryx.core import charter\\n")], "nucleus/__init__.py"),',
     '     [("tests/test_x.py", "from astryx.core import charter\\n")], "src/astryx/core/__init__.py"),'),
    ("tests/test_reachability.py", "EXEMPT = {\n",
     "EXEMPT = {\n"
     '    "devtools/reorg/apply.py": "operator: the seed runs it by hand in the goal 10224 S4 reorg window",\n'
     '    "src/astryx/__main__.py": "`python -m astryx` runs it by the package\'s name (the console script\'s twin)",\n'),
    ("tests/test_reachability.py",
     '    for p in _git("ls-files"):\n        f = REPO / p\n        try:\n            texts.append((p, f.read_text(errors="ignore")))',
     '    for p in _git("ls-files"):\n        f = REPO / p\n'
     '        if _is_reorg_stub(p) or p.startswith("devtools/reorg/") or p in ("src/astryx/_reorg.py",\n'
     '                                                                         "tests/test_reorg_roots.py"):\n'
     '            continue              # a compat stub, and the reorg\'s own map/census, are not edges (goal 10224 S4)\n'
     '        try:\n            texts.append((p, f.read_text(errors="ignore")))'),
    ("tests/test_tool_ledger.py",
     '    sys.path.insert(0, str(root))\n    from astryx.core import toolreg  # noqa: E402',
     '    sys.path.insert(0, str(root))\n'
     '    for _k in [k for k in sys.modules if k == "astryx" or k.startswith("astryx.")]:\n'
     '        del sys.modules[_k]          # goal 10224 S4: fixture.py\'s import bound `astryx` to the REAL repo\n'
     '    from astryx.core import toolreg  # noqa: E402'),
    ("devtools/branch_check_sandbox.py",
     '    res["live_repo_visible"] = (lr / "devtools" / "check.sh").is_file()',
     '    res["live_repo_visible"] = ((lr / "devtools" / "check.sh").is_file()\n'
     '                                or (lr / "nucleus" / "check.sh").is_file())  # reorg: keep (either side of the move)'),
    ("tests/test_restore_drill.py", 'bash nucleus/restore_drill\\.sh', 'bash scripts/restore_drill\\.sh'),
    ("tests/test_tier.py",
     '    r"\\bfrom\\s+nucleus\\s+import\\s+people\\b",         # the people cache module\n',
     '    r"\\bfrom\\s+nucleus\\s+import\\s+people\\b",         # the people cache module\n'
     '    r"\\bfrom\\s+astryx\\.people\\s+import\\s+people\\b",  # ...where it lives since goal 10224 S4\n'
     '    r"\\bastryx\\.people\\.people\\b",\n'),
    ("tests/test_people_gate.py",
     '    spec = importlib.util.spec_from_file_location(f"nucleus.{mod}", src)\n'
     '    m = importlib.util.module_from_spec(spec)\n'
     '    sys.modules[f"nucleus.{mod}"] = m\n',
     '    from astryx._reorg import legacy_module           # goal 10224 S4: the mutant replaces the MOVED module too\n'
     '    spec = importlib.util.spec_from_file_location(legacy_module(f"nucleus.{mod}"), src)\n'
     '    m = importlib.util.module_from_spec(spec)\n'
     '    sys.modules[f"nucleus.{mod}"] = sys.modules[legacy_module(f"nucleus.{mod}")] = m\n'),
    # trigger_names reads a trigger's imports STATICALLY: astryx.* through the root shim's __path__ (src/astryx/),
    # and a moved nucleus.* name where it lives now (the stub has no @trigger defs to read)
    ("src/astryx/core/trigger_names.py",
     '    Not local at all (stdlib, site-packages) → Ellipsis: nothing to read."""\n'
     '    root = _root_of(dotted.split(".")[0], w)\n',
     '    Not local at all (stdlib, site-packages) → Ellipsis: nothing to read."""\n'
     '    try:\n'
     '        from astryx._reorg import legacy_module      # goal 10224 S4: a moved nucleus.* is read where it lives\n'
     '        dotted = legacy_module(dotted) or dotted\n'
     '    except ImportError:\n'
     '        pass\n'
     '    root = _root_of(dotted.split(".")[0], w)\n'),
    ("src/astryx/core/trigger_names.py",
     '    files = _module_files(dotted, root)\n    if files is None:\n',
     '    files = _module_files(dotted, root)\n'
     '    if files is None and dotted.split(".")[0] == "astryx" and (root / "src" / "astryx" / "__init__.py").is_file():\n'
     '        files = _module_files(dotted, root / "src")    # the root shim\'s __path__ is src/astryx/\n'
     '    if files is None:\n'),
    ("src/astryx/core/trigger_names.py",
     '    base = root.joinpath(*dotted.split("."))\n'
     '    return (base / f"{name}.py").is_file() or (base / name).is_dir()\n',
     '    return any((b / f"{name}.py").is_file() or (b / name).is_dir()\n'
     '               for b in (root.joinpath(*dotted.split(".")), root.joinpath("src", *dotted.split("."))))\n'),
    # the econ consumer scan reads both spellings: the moved module, and the legacy name hooks/ and triggers/ keep
    ("tests/test_econ_consumers.py",
     '        if isinstance(n, ast.ImportFrom) and n.module == "astryx.econ.econ":\n'
     '            why.add("import astryx.econ.econ")\n'
     '        elif isinstance(n, ast.ImportFrom) and n.module == "nucleus" \\\n'
     '                and any(a.name == "econ" for a in n.names):\n'
     '            why.add("import astryx.econ.econ")\n'
     '        elif isinstance(n, ast.Import) and any(a.name == "astryx.econ.econ" for a in n.names):\n',
     '        if isinstance(n, ast.ImportFrom) and n.module in ("astryx.econ.econ", "nucleus.econ"):  # reorg: keep\n'
     '            why.add("import astryx.econ.econ")\n'
     '        elif isinstance(n, ast.ImportFrom) and n.module in ("nucleus", "astryx.econ") \\\n'
     '                and any(a.name == "econ" for a in n.names):\n'
     '            why.add("import astryx.econ.econ")\n'
     '        elif isinstance(n, ast.Import) and any(a.name in ("astryx.econ.econ", "nucleus.econ")  # reorg: keep\n'
     '                                               for a in n.names):\n'),
    ("tests/test_econ_consumers.py",
     '                and b.value == "astryx.econ.econ" for a, b in zip(n.elts, n.elts[1:])):\n',
     '                and b.value in ("astryx.econ.econ", "nucleus.econ") for a, b in zip(n.elts, n.elts[1:])):  # reorg: keep\n'),
    # the wheel's runtime tree now carries scripts/ (operator shell); devtools/ stays out of it
    ("src/astryx/_data/manifest.py", '"mcp/", "nucleus/", "observatory/", "skills/", "src/astryx/",',
     '"mcp/", "nucleus/", "observatory/", "scripts/", "skills/", "src/astryx/",'),
]

# Every generated unit carries ASTRYX_HOME: a line added after each `User=$USER` inside init.sh's unit heredocs.
UNIT_ENV = ("User=$USER\n", "User=$USER\nEnvironment=ASTRYX_HOME=$PWD\n")


# ── stubs ────────────────────────────────────────────────────────────────────────────────────────────────────────

PY_STUB = '''"""MOVED: {old} -> {new} ({mod}), goal 10224 S4. A compat stub, kept for one release.

Imported, this IS the moved module (one object, aliased in sys.modules, never a copy), so a monkeypatch lands on the
real thing. Run as a script or with -m, it runs the moved module as __main__. Each use stamps {stamp}/ so a census
can find the callers still to migrate. Generated by devtools/reorg/apply.py from devtools/reorg/map.tsv.
"""
import os as _os
import sys as _sys

_ROOT = {chain}
if __name__ == "__main__" or "astryx" not in _sys.modules and _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from astryx._reorg import redirect as _redirect  # noqa: E402

_m = _redirect(__name__, "{old}", "{mod}", _ROOT)


def __getattr__(name):            # a by-file load (spec_from_file_location) still reaches the real module's names
    return getattr(_m, name)
'''

SITE_STUB = '''"""MOVED: {old} -> {new}, goal 10224 S4. A compat stub, kept for one release: loaded as `sitecustomize` (a
PYTHONPATH entry), it runs the moved shim in its place. Generated by devtools/reorg/apply.py."""
import os as _os
import runpy as _runpy

globals().update({{k: v for k, v in _runpy.run_path(_os.path.join({chain}, "{new}"), run_name=__name__).items()
                  if not k.startswith("__")}})
'''

SH_STUB = '''#!/usr/bin/env bash
# MOVED: {old} -> {new} (goal 10224 S4). A compat stub, kept for one release: it runs the moved script with the same
# arguments (or sources it, when it is sourced). Each use stamps {stamp}/ for the census. Generated by
# devtools/reorg/apply.py from devtools/reorg/map.tsv.
_astryx_stub_root=$(cd "$(dirname "$(readlink -f "${{BASH_SOURCE[0]:-$0}}")")/{up}" && pwd)
{{ mkdir -p "$_astryx_stub_root/{stamp}" && printf '%s\\t%s\\n' "$PPID" "$(tr '\\0' ' ' < /proc/$PPID/cmdline)" \\
    > "$_astryx_stub_root/{stamp}/{flat}"; }} 2>/dev/null || true
if [ "${{BASH_SOURCE[0]:-$0}}" != "$0" ]; then . "$_astryx_stub_root/{new}" "$@"; return $?; fi
exec "$_astryx_stub_root/{new}" "$@"
'''

REORG_PY = '''"""The goal 10224 S4 reorg's compat layer: where each old nucleus/ path went, and the redirect every stub calls.

MOVED maps an old path (nucleus/x.py) to its new one; MODULES maps an old dotted name (nucleus.x) to the new module.
Tools that resolve a legacy reference (a gitignored trigger's `from nucleus.x import ...`) read them here instead of
opening the stub. Generated by devtools/reorg/apply.py from devtools/reorg/map.tsv: edit the map, never this file.
"""
from __future__ import annotations

import importlib
import os
import sys
import time

MOVED = {moved}
MODULES = {modules}
STAMP_DIR = "{stamp}"
STAMP_EVERY = 3600          # a stamp is rewritten at most hourly per (stub, caller): cheap on the pulse's minute


def legacy_module(name: str) -> str | None:
    """`nucleus.x[.y]` -> its new dotted name, or None when it isn't a moved module."""
    parts = name.split(".")
    for k in range(len(parts), 1, -1):
        hit = MODULES.get(".".join(parts[:k]))
        if hit:
            return ".".join([hit] + parts[k:])
    return None


def legacy_path(rel: str) -> str | None:
    """`nucleus/x.py` -> its new repo-relative path, or None."""
    return MOVED.get(rel)


def _caller() -> str:
    f = sys._getframe(2)
    while f is not None and (f.f_code.co_filename.startswith("<frozen") or "/nucleus/" in f.f_code.co_filename
                             or f.f_code.co_filename.endswith("/_reorg.py")):
        f = f.f_back
    return f.f_code.co_filename if f is not None else (sys.argv[0] if sys.argv else "?")


def stamp(old: str, root: str) -> None:
    """Record that `old` was used, and by whom: {stamp}/<old>__<caller hash>. Never raises."""
    try:
        import hashlib
        who = _caller()
        d = os.path.join(root, STAMP_DIR)
        p = os.path.join(d, old.replace("/", "__") + "__" + hashlib.sha1(who.encode()).hexdigest()[:10])
        try:
            if time.time() - os.stat(p).st_mtime < STAMP_EVERY:
                return
        except OSError:
            pass
        os.makedirs(d, exist_ok=True)
        with open(p, "w") as fh:
            fh.write(f"{{old}}\\t{{who}}\\t{{' '.join(sys.argv)[:300]}}\\n")
    except Exception:
        pass


class _Alias:
    """Loader for a NESTED legacy name (nucleus.sqlguard.x): its parent is already aliased to the moved package, whose
    __path__ would otherwise load the real file a second time under the legacy name (two module objects)."""

    def __init__(self, target: str, old: str, root: str):
        self.target, self.old, self.root = target, old, root

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        stamp(self.old, self.root)
        sys.modules[module.__name__] = importlib.import_module(self.target)

    def get_code(self, name):    # `python -m nucleus.sqlguard.x`: run the moved module as __main__
        return compile(f"import runpy; runpy.run_module({{self.target!r}}, run_name='__main__', alter_sys=True)",
                       f"<moved: {{name}} -> {{self.target}}>", "exec")

    def is_package(self, name):
        return False


class _Finder:
    def __init__(self, root: str):
        self.root = root

    def find_spec(self, name, path=None, target=None):
        if not name.startswith("nucleus.") or name.count(".") < 2:
            return None              # a top-level nucleus.x has its own stub file
        t = legacy_module(name)
        if t is None:
            return None
        import importlib.machinery
        return importlib.machinery.ModuleSpec(name, _Alias(t, name.replace(".", "/") + ".py", self.root))


def install_finder(root: str) -> None:
    if not any(type(f).__name__ == "_Finder" and getattr(f, "root", None) is not None for f in sys.meta_path):
        sys.meta_path.insert(0, _Finder(root))


def redirect(name: str, old: str, target: str, root: str):
    """Imported as `name`: alias sys.modules[name] to `target` and return it. As __main__: run `target` as __main__."""
    stamp(old, root)
    install_finder(root)
    if name == "__main__":
        import runpy
        runpy.run_module(target, run_name="__main__", alter_sys=True)
        return None
    mod = importlib.import_module(target)
    sys.modules[name] = mod
    return mod
'''

NEW_PKG_INIT = '"""astryx.{sub}: {what} (goal 10224 S4 reorg; moved from nucleus/)."""\n'
SUB_WHAT = {
    "core": "the org's core library (charters, tiers, addresses, the tool registry, escalation, wakes)",
    "pg": "the postgres server's design, schema parity and run-scoped databases",
    "pulse": "the org's clock: the pulse, its isolated runner, the senses, and the shipped triggers",
    "econ": "the economy: its equations and the guards that keep its definitions honest",
    "memory": "the recall graph, the OKF estate, the ontology and the world model",
    "people": "the owner's people graph, its access gate and the personas",
    "hearing": "the Room: the ear's fetch/fence/lease/store, the hearing pool, wake word and voiceprints",
    "hands": "Hands: the browser lease, the agent's desktop, its seat and proxy, and the phone",
    "security": "secrets, the release door, log redaction, DSN/password tooling and sqlguard",
    "federation": "the internet of agents: introduce, federate, fedtest and the A2A card assert",
    "contrib": "owner-specific and hardware extras (growbot, the canopus poller); a private overlay later",
    "sql": "the declared schemas (package data)",
    "data": "the registries and manifests code reads by path (package data)",
}


# ── git helpers ──────────────────────────────────────────────────────────────────────────────────────────────────

def git(root: Path, *args, check=True) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise SystemExit(f"apply: git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True,
                         env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")}).stdout
    return [p for p in out.decode().split("\0") if p]


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=".", help="the checkout to apply in (default: cwd)")
    ap.add_argument("--check", action="store_true", help="report only; rc 1 when anything is still to do")
    ap.add_argument("--allow-dirty", action="store_true", help="skip the clean-tree precondition (tests)")
    a = ap.parse_args(argv)
    root = Path(a.repo).resolve()
    if not (root / ".git").exists() or not (root / MAP).is_file():
        print(f"apply: {root} is not a checkout holding {MAP}", file=sys.stderr)
        return 2
    files, dirs = load_map(root)
    rw = Rewriter(files, dirs)
    did: dict[str, list[str]] = {"moved": [], "rewritten": [], "rooted": [], "patched": [], "stubs": [], "inits": []}
    touched: set[str] = set()

    # 0. precondition: no tracked change pending, unless this is a re-run on our own applied (uncommitted) result
    dirty = git(root, "status", "--porcelain", "--untracked-files=no").strip()
    todo_moves = [(o, n, m) for o, n, m in files if not (root / n).exists()]
    if dirty and todo_moves and not a.allow_dirty and not a.check:
        print("apply: the tree has tracked changes; run from a pristine checkout:\n" + dirty, file=sys.stderr)
        return 2

    # 1. moves
    for o, n, m in files:
        src, dst = root / o, root / n
        if dst.exists() or dst.is_symlink():
            continue
        if not src.exists():
            print(f"apply: {o} is in the map but not in this tree (main moved on?)", file=sys.stderr)
            return 2
        did["moved"].append(f"{o} -> {n}")
        if a.check:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        git(root, "mv", o, n)
        touched.update((o, n))
    if a.check and did["moved"]:
        for k, v in did.items():
            if v:
                print(f"{k}: {len(v)} still to do")
        return 1

    # 1b. package markers for new subpackages
    subs = sorted({n.split("/")[2] for o, n, _ in files if n.startswith("src/astryx/") and n.count("/") >= 3
                   and n.endswith(".py")} - {"contrib"})
    # sql/ and data/ hold package data only, and contrib/ (owner-only extras bound for a private overlay) is a
    # namespace package: none of them gets an __init__.py.
    for sub in subs:
        p = root / "src/astryx" / sub / "__init__.py"
        if not p.exists():
            p.write_text(NEW_PKG_INIT.format(sub=sub, what=SUB_WHAT.get(sub, sub)))
            did["inits"].append(str(p.relative_to(root)))
            touched.add(str(p.relative_to(root)))
    dt = root / "devtools/__init__.py"
    if not dt.exists():
        dt.write_text('"""devtools: the org\'s internal review and CI tooling (goal 10224 S4). Never in the wheel."""\n')
        did["inits"].append("devtools/__init__.py")
        touched.add("devtools/__init__.py")

    # 1c. the compat layer
    moved = {o: n for o, n, _ in files}
    modules = {o[:-3].replace("/", ".") if o.endswith(".py") else o.rstrip("/").replace("/", "."): m
               for o, n, m in files + dirs if m}
    modules = {k.removesuffix(".__init__"): v for k, v in modules.items()}
    reorg = REORG_PY.format(moved=json.dumps(moved, indent=4, sort_keys=True),
                            modules=json.dumps(modules, indent=4, sort_keys=True), stamp=STAMP_DIR)
    rp = root / "src/astryx/_reorg.py"
    if not rp.exists() or rp.read_text() != reorg:
        rp.write_text(reorg)
        touched.add("src/astryx/_reorg.py")
        did["patched"].append("src/astryx/_reorg.py (generated)")

    # 2. rewrite tracked references (never inside the stubs we are about to write, nor hooks/channel/mcp)
    stub_paths = set(moved)
    for rel in tracked(root):
        if rel.startswith(NEVER_REWRITE) or rel in stub_paths or rel.startswith("nucleus/"):
            continue
        p = root / rel
        if p.is_symlink() or not p.is_file():
            continue
        raw = p.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode()
        except UnicodeDecodeError:
            continue
        new = rw.rewrite(text)
        if rel.startswith("tests/") and rel.endswith(".py"):
            new = rw.fake_tree_dirs(new)
        if rel.startswith("tests/") and rel.endswith(".sh"):
            new = rw.shell_dirs(new)
        if rel.endswith("sqlguard/ledger.json") and new != text:
            new = json.dumps(json.loads(new), indent=1, sort_keys=True) + "\n"
        if new != text:
            p.write_text(new)
            did["rewritten"].append(rel)
            touched.add(rel)

    # 3. repo roots of moved python modules
    for o, n, m in files:
        if not n.endswith(".py") or n.endswith("sitecustomize.py") or n in ROOT_EXEMPT:
            continue
        p = root / n
        text = p.read_text()
        new = route_root(text, o.count("/"), n.count("/"))
        if new != text:
            p.write_text(new)
            did["rooted"].append(n)
            touched.add(n)

    # 4. hand patches
    bad = []
    for rel, old, new in PATCHES:
        p = root / rel
        text = p.read_text()
        if new in text:
            continue
        if old not in text:
            bad.append(f"{rel}: neither the old nor the new text is there: {old[:80]!r}")
            continue
        p.write_text(text.replace(old, new))
        did["patched"].append(rel)
        touched.add(rel)
    init = root / "init.sh"
    t = init.read_text()
    if UNIT_ENV[1] not in t:
        init.write_text(t.replace(UNIT_ENV[0], UNIT_ENV[1]))
        did["patched"].append("init.sh (ASTRYX_HOME in every unit)")
        touched.add("init.sh")
    if bad:
        print("apply: PATCHES drifted (fix the patch against this main, then re-run):\n  " + "\n  ".join(bad),
              file=sys.stderr)
        return 1

    # 5. stubs at the old paths
    for o, n, m in files:
        p = root / o
        depth = o.count("/")
        if o.endswith(".py") and m:
            body = PY_STUB.format(old=o, new=n, mod=m, stamp=STAMP_DIR,
                                  chain=_chain(depth + 1).replace("_os.path.realpath(__file__)",
                                                                  "_os.path.realpath(__file__)"))
        elif o.endswith("sitecustomize.py"):
            body = SITE_STUB.format(old=o, new=n, chain=_chain(depth + 1))
        elif o.endswith(".sh"):
            body = SH_STUB.format(old=o, new=n, stamp=STAMP_DIR, up="/".join([".."] * depth),
                                  flat=o.replace("/", "__"))
        else:
            target = os.path.relpath(root / n, p.parent)
            if p.is_symlink() and os.readlink(p) == target:
                continue
            if p.exists() or p.is_symlink():
                print(f"apply: {o} exists and is not the expected symlink; leaving it", file=sys.stderr)
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, p)
            did["stubs"].append(o)
            touched.add(o)
            continue
        if p.is_file() and not p.is_symlink() and p.read_text() == body:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        mode = (root / n).stat().st_mode & 0o777 if (root / n).exists() else 0o644
        if o.endswith(".sh"):
            mode |= 0o755
        os.chmod(p, mode)
        did["stubs"].append(o)
        touched.add(o)

    # 6. stage exactly what we touched
    if touched:
        git(root, "add", "-A", "--", *sorted(touched))
    for k, v in did.items():
        print(f"{k}: {len(v)}" + (f"  ({', '.join(v)})" if 0 < len(v) <= 5 else ""))
    if rw.unknown:
        print("left alone (from nucleus import <name not in the map>): " + ", ".join(sorted(rw.unknown)))
    if not any(did.values()):
        print("apply: already applied, nothing to do")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
