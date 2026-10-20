#!/usr/bin/env python3
"""Oracle for devtools/child_env_gate.py (plan-10224 child-env-gate; a3 #61402, seed ruling #61406).

    venv/bin/python tests/test_child_env_gate.py        (also run by devtools/check.sh)

The gate partitions every subprocess `env=` in tests/*.py: GREEN when it provably carries the parent's cog registry
pin (inherits os.environ, goes through propagate.env_for_child, or names its own registry), GREEN when the child is
provably a plain tool, DECLARED by `# own-env: <why>`, RED otherwise. Each bucket is pinned BOTH ways on fixture text
(a RED that must fire, a control that must not), then the gate runs on THIS tree: zero findings, and enough sites
classified that the zero means something. Hermetic: no database, no subprocess. Exit 0 pass · 1 fail.
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("CHILD_ENV_GATE_SRC") or REPO / "devtools" / "child_env_gate.py")

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("child_env_gate", SUBJECT)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

fails: list[str] = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + ("" if cond else f"  — {detail}"))
    if not cond:
        fails.append(label)


HEAD = "import os, subprocess, sys\nfrom astryx.security.sqlguard import propagate\n"


def red(body: str) -> list:
    return g.scan_text(HEAD + body, "tests/fx.py")


def buckets(body: str) -> list:
    return [f["bucket"] for f in g.classify_text(HEAD + body, "tests/fx.py")]


PY = 'subprocess.run([sys.executable, "-c", "import astryx"], env={})\n'

print("RED: an env that drops the pin")
for label, body in (
        ("a scratch dict handed to a python child", 'subprocess.run([sys.executable, "x.py"], env={"PATH": "/bin"})\n'),
        ("a name assigned a scratch dict", 'e = {"PATH": "/bin"}\nsubprocess.run([sys.executable, "x.py"], env=e)\n'),
        ("an ALLOWLIST copy of os.environ (keeps only what it names)",
         'subprocess.run([sys.executable, "x.py"], env={k: os.environ[k] for k in ("PATH",) if k in os.environ})\n'),
        ("an ALLOWLIST filter over os.environ.items() (`if k in (…)` keeps only what it names)",
         'subprocess.run([sys.executable, "x.py"], env={k: v for k, v in os.environ.items() '
         'if k in ("PATH", "HOME")})\n'),
        ("a copy whose filter drops the registry by name",
         'subprocess.run([sys.executable, "x.py"], env={k: v for k, v in os.environ.items() '
         'if k not in ("ASTRYX_COG_REGISTRY",)})\n'),
        ("a copy whose filter drops every ASTRYX_ key",
         'subprocess.run([sys.executable, "x.py"], env={k: v for k, v in os.environ.items() '
         'if not k.startswith("ASTRYX_")})\n'),
        ("a copy filtered by a set the gate can't see",
         'DROP = set()\nsubprocess.run([sys.executable, "x.py"], env={k: v for k, v in os.environ.items() '
         'if k not in DROP})\n'),
        ("the host's LIVE registry named as the env's own",
         'subprocess.run([sys.executable, "x.py"], env={"ASTRYX_COG_REGISTRY": "/etc/astryx/cog.json"})\n'),
        ("a parameter some caller hands a scratch env",
         'def go(e):\n    subprocess.run([sys.executable, "x.py"], env=e)\ngo({"PATH": "/bin"})\n'),
        ("a builder defined here that returns a scratch env",
         'def mk():\n    return {"PATH": "/bin"}\nsubprocess.run([sys.executable, "x.py"], env=mk())\n'),
        ("a conditional env with one scratch branch",
         'subprocess.run([sys.executable, "x.py"], env=os.environ if sys.argv else {"PATH": "/bin"})\n'),
        ("bash running a repo script by path", 'subprocess.run(["bash", "scripts/spawn.sh", "x"], env={})\n'),
        ("a bash -c body that runs a repo script (seed #61406)",
         'subprocess.run(["bash", "-c", "cd /r && ./scripts/spawn.sh x"], env={})\n'),
        ("a bash -c body that runs python", 'subprocess.run(["bash", "-c", "python3 -m astryx.orgs"], env={})\n'),
        ("a bash -c body built at runtime (invisible)", 'b = "x"\nsubprocess.run(["bash", "-c", b], env={})\n'),
        ("git commit (it can run the repo's hooks)", 'subprocess.run(["git", "commit", "-m", "x"], env={})\n'),
        ("systemctl start (a unit may run astryx)", 'subprocess.run(["systemctl", "--user", "start", "u"], env={})\n'),
        ("a program the gate doesn't know", 'subprocess.run(["make", "x"], env={})\n'),
        ("an empty `# own-env:` (a reason is required)", '# own-env:\n' + PY),
        ("a declaration two lines up doesn't reach the call", '# own-env: far away\n\n' + PY),
        ("an imported spawner (from subprocess import run)",
         'from subprocess import run\nrun([sys.executable, "x.py"], env={})\n'),
        ("an aliased module (import subprocess as sp)", 'import subprocess as sp\nsp.run([sys.executable], env={})\n'),
        # a3 #61413's bypass fixtures, each green at ea6023f
        ("B1 a green copy that POPS the registry",
         'e = os.environ.copy()\ne.pop("ASTRYX_COG_REGISTRY", None)\nsubprocess.run([sys.executable], env=e)\n'),
        ("B2 a green copy that DELETES the registry",
         'e = dict(os.environ)\ndel e["ASTRYX_COG_REGISTRY"]\nsubprocess.run([sys.executable], env=e)\n'),
        ("B3 a green copy whose ASTRYX_ keys a loop deletes",
         'e = dict(os.environ)\nfor k in list(e):\n    if k.startswith("ASTRYX_"):\n        del e[k]\n'
         'subprocess.run([sys.executable], env=e)\n'),
        ("B4 `not (k in SCRUB)`: an unseen set, negated (unknown is never proven)",
         'SCRUB = set()\nsubprocess.run([sys.executable], env={k: v for k, v in os.environ.items() '
         'if not (k in SCRUB)})\n'),
        ("B5 `not (k == R)` with R a name", 'R = "x"\nsubprocess.run([sys.executable], env={k: v for k, v in '
         'os.environ.items() if not (k == R)})\n'),
        ("B6 a filter that tests something other than the key (k[:6])",
         'subprocess.run([sys.executable], env={k: v for k, v in os.environ.items() if k[:6] not in ("ASTRYX",)})\n'),
        ("B7 `os.environ | {REGISTRY: '/etc/…'}`: the right side wins the key",
         'subprocess.run([sys.executable], env=os.environ | {"ASTRYX_COG_REGISTRY": "/etc/astryx/cog.json"})\n'),
        ("B8 `e[REGISTRY] = '/etc/…'`", 'e = {"PATH": "/usr/bin"}\ne["ASTRYX_COG_REGISTRY"] = "/etc/astryx/cog.json"\n'
         'subprocess.run([sys.executable], env=e)\n'),
        ("B9 node on a runtime path (an interpreter, not a data consumer)",
         'mjs = "x"\nsubprocess.run(["node", str(mjs)], env={"PATH": "/usr/bin"})\n'),
        ("B10 tmux running a python command string",
         'subprocess.run(["tmux", "new-session", "-d", "venv/bin/python -m astryx.pulse.pulse"], '
         'env={"PATH": "/usr/bin"})\n'),
        ("B11 npm run (package.json scripts run repo code)", 'subprocess.run(["npm", "run", "build"], env={})\n'),
        ("B12 git fetch (gc --auto runs pre-auto-gc)", 'subprocess.run(["git", "fetch", "origin"], env={})\n'),
        ("B13 git clone (post-checkout)", 'subprocess.run(["git", "clone", "a", "b"], env={})\n'),
        ("B15 a git ALIAS (the host's alias.ci is a commit)", 'subprocess.run(["git", "ci", "-m", "x"], env={})\n'),
        ("B16 a registry set inside an `if`, then an unconditional spawn",
         'e = {"PATH": "/usr/bin"}\nif sys.argv:\n    e["ASTRYX_COG_REGISTRY"] = "/tmp/r"\n'
         'subprocess.run([sys.executable], env=e)\n'),
        ("a git subcommand built at runtime", 'a = "log"\nsubprocess.run(["git", a], env={})\n'),
        ("an __enter__ that returns ANOTHER object: the receiver isn't a C",
         'class D:\n    def env(self):\n        return {"PATH": "/bin"}\nclass C:\n    def __enter__(self):\n'
         '        return D()\n    def env(self):\n        return {**os.environ}\n'
         'fx = C().__enter__()\nsubprocess.run([sys.executable], env=fx.env())\n'),
        ("a receiver bound to two different classes (it can't be judged as either)",
         'class C:\n    def env(self):\n        return {**os.environ}\nclass D:\n    def env(self):\n'
         '        return {"PATH": "/bin"}\nfx = C()\nfx = D()\nsubprocess.run([sys.executable], env=fx.env())\n'),
        ("`|` with a right side the gate can't see",
         'x = {}\nsubprocess.run([sys.executable], env=os.environ | x)\n'),
):
    check(f"RED {label}", len(red(body)) == 1, str(red(body)))
check("RED a file that doesn't parse is a finding, never \"no sites\" (its sites would vanish)",
      len(g.scan_text("def (:\n", "tests/fx.py")) == 1)

print("\nGREEN: the env provably carries the pin, or the child provably reads none")
for label, body, want in (
        ("no env= at all (inherits)", 'subprocess.run([sys.executable, "x.py"])\n', []),
        ("os.environ", 'subprocess.run([sys.executable], env=os.environ)\n', ["inherit"]),
        ("os.environ.copy()", 'subprocess.run([sys.executable], env=os.environ.copy())\n', ["inherit"]),
        ("dict(os.environ, X=…)", 'subprocess.run([sys.executable], env=dict(os.environ, X="1"))\n', ["inherit"]),
        ("{**os.environ, …}", 'subprocess.run([sys.executable], env={**os.environ, "X": "1"})\n', ["inherit"]),
        ("os.environ | {…}", 'subprocess.run([sys.executable], env=os.environ | {"X": "1"})\n', ["inherit"]),
        ("a copy excluding other literal keys",
         'subprocess.run([sys.executable], env={k: v for k, v in os.environ.items() '
         'if k not in ("ASTRYX_DSN", "ASTRYX_HOME")})\n', ["inherit"]),
        ("an allowlist that NAMES the registry",
         'subprocess.run([sys.executable], env={k: v for k, v in os.environ.items() '
         'if k in ("PATH", "ASTRYX_COG_REGISTRY")})\n', ["inherit"]),
        ("a copy dropping another prefix",
         'subprocess.run([sys.executable], env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})\n',
         ["inherit"]),
        ("propagate.env_for_child(…)", 'subprocess.run([sys.executable], env=propagate.env_for_child({}))\n',
         ["helper"]),
        ("a dict naming its own registry",
         'subprocess.run([sys.executable], env={"ASTRYX_COG_REGISTRY": "/tmp/x/cog.json"})\n', ["own-registry"]),
        ("a name whose registry is set by subscript",
         'e = {"PATH": "/bin"}\ne["ASTRYX_COG_REGISTRY"] = "/tmp/r"\nsubprocess.run([sys.executable], env=e)\n',
         ["own-registry"]),
        ("a builder call handed the registry", 'def mk(**k):\n    return k\n'
         'subprocess.run([sys.executable], env=mk(ASTRYX_COG_REGISTRY="/tmp/r"))\n', ["own-registry"]),
        ("a builder defined here that inherits",
         'def mk():\n    return {**os.environ, "X": "1"}\nsubprocess.run([sys.executable], env=mk())\n', ["inherit"]),
        ("a builder that shares its name with what it calls (no self-recursion)",
         'class F:\n    def env(self):\n        return {**os.environ}\nfx = F()\n'
         'def env():\n    return fx.env()\nsubprocess.run([sys.executable], env=env())\n', ["inherit"]),
        ("a parameter every caller hands a green env",
         'def go(e):\n    subprocess.run([sys.executable], env=e)\ngo(os.environ)\ngo(e={**os.environ})\n',
         ["inherit"]),
        ("a keyword-only parameter", 'def go(*a, env):\n    subprocess.run([sys.executable], env=env)\n'
         'go(env=os.environ)\n', ["inherit"]),
        ("a lambda reading its outer function's name",
         'def f():\n    ge = {**os.environ}\n    g = lambda *a: subprocess.run([sys.executable, *a], env=ge)\n',
         ["inherit"]),
        ("a for-loop over literal rows", 'for w, e in (("a", os.environ), ("b", {**os.environ})):\n'
         '    subprocess.run([sys.executable], env=e)\n', ["inherit"]),
        ("a conditional env, both branches green",
         'subprocess.run([sys.executable], env=os.environ if sys.argv else {**os.environ})\n', ["inherit"]),
        ("git with a runtime path (data, not code)",
         'r = "/tmp"\nsubprocess.run(["git", "-C", r, "ls-files"], env={})\n', ["child"]),
        ("systemctl is-active (starts nothing)",
         'subprocess.run(["systemctl", "--user", "is-active", "astryx-x"], env={})\n', ["child"]),
        ("a literal bash -c body that runs no repo code", 'subprocess.run(["bash", "-c", "echo hi"], env={})\n',
         ["child"]),
        ("a mutation that drops ANOTHER literal key keeps the pin (B1's control)",
         'e = os.environ.copy()\ne.pop("ASTRYX_HOME", None)\ndel e["LANGUAGE"]\n'
         'subprocess.run([sys.executable], env=e)\n', ["inherit"]),
        ("a registry set earlier in the SAME block (B16's control)",
         'e = {"PATH": "/usr/bin"}\ne["ASTRYX_COG_REGISTRY"] = "/tmp/r"\nsubprocess.run([sys.executable], env=e)\n',
         ["own-registry"]),
        ("`os.environ | {REGISTRY: <own path>}` (B7's control)",
         'subprocess.run([sys.executable], env=os.environ | {"ASTRYX_COG_REGISTRY": "/tmp/r"})\n', ["own-registry"]),
        ("a filter on the key, negated and decided (B4's control)",
         'subprocess.run([sys.executable], env={k: v for k, v in os.environ.items() if not (k in ("X",))})\n',
         ["inherit"]),
        ("a receiver built by C().__enter__() when C.__enter__ returns self",
         'class C:\n    def __enter__(self):\n        return self\n    def env(self):\n        return {**os.environ}\n'
         'fx = C().__enter__()\nsubprocess.run([sys.executable], env=fx.env())\n', ["inherit"]),
        ("a receiver that is a parameter, every caller passing C()",
         'class C:\n    def env(self):\n        return {**os.environ}\n'
         'def arms(fx):\n    subprocess.run([sys.executable], env=fx.env())\narms(C())\n', ["inherit"]),
        ("git log, a read-only subcommand after -C <path>", 'r = "/tmp"\nsubprocess.run(["git", "-C", r, "log"], '
         'env={})\n', ["child"]),
        ("a `# own-env: <why>` on the line above", '# own-env: asserts its own env\n' + PY, ["declared"]),
        ("a `# own-env: <why>` on the call's own line",
         'subprocess.run([sys.executable], env={})  # own-env: the arm\n', ["declared"]),
):
    got = buckets(body)
    check(f"GREEN {label} → {want or 'not a site'}", got == want and not red(body), f"{got} {red(body)}")

print("\nSIBLING MODULE: a builder imported from tests/ is judged in ITS module (org_home_fixture's OrgHomes.env)")
with tempfile.TemporaryDirectory(prefix="ceg-") as d:
    td = Path(d)
    (td / "fxlib.py").write_text('import os\nclass H:\n    def env(self, **o):\n        e = {"PATH": "/bin"}\n'
                                 '        e["ASTRYX_COG_REGISTRY"] = "/tmp/r"\n        return e\n'
                                 '    def bare(self):\n        return {"PATH": "/bin"}\n')
    body = 'from fxlib import H\nfx = H()\nsubprocess.run([sys.executable], env=fx.env())\n'
    check("a sibling builder that sets its own registry is GREEN",
          [f["bucket"] for f in g.classify_text(HEAD + body, "tests/fx.py", td, {})] == ["own-registry"])
    body = 'from fxlib import H\nfx = H()\nsubprocess.run([sys.executable], env=fx.bare())\n'
    check("…and one that returns a scratch env is RED", len(g.scan_text(HEAD + body, "tests/fx.py", td, {})) == 1)
    # B14 (a3 #61413): a builder is reached through the name IMPORTED, never by its bare method name on any receiver
    (td / "fxenv.py").write_text('import os\nOTHER = 1\ndef env():\n    return dict(os.environ)\n')
    body = 'from fxenv import OTHER\nimport x as sb\nsubprocess.run([sys.executable], env=sb.env())\n'
    check("B14 importing ANY name from a module that defines env() doesn't make sb.env() green",
          len(g.scan_text(HEAD + body, "tests/fx.py", td, {})) == 1)
    body = 'from fxenv import OTHER\nsubprocess.run([sys.executable], env=env())\n'
    check("…nor does a bare env() the file never imported (only OTHER came in)",
          len(g.scan_text(HEAD + body, "tests/fx.py", td, {})) == 1)
    body = 'from fxenv import env\nsubprocess.run([sys.executable], env=env())\n'
    check("…while the IMPORTED function itself is followed (green)",
          [f["bucket"] for f in g.classify_text(HEAD + body, "tests/fx.py", td, {})] == ["inherit"])

print("\nTHIS TREE")
cen = g.census(REPO)
reds = [c for c in cen if c["bucket"] == "red"]
check("every subprocess env in tests/ is classified: 0 RED", not reds,
      "; ".join(f"{c['file']}:{c['line']} {c['why']}" for c in reds[:8]))
by = {b: sum(1 for c in cen if c["bucket"] == b) for b in ("inherit", "helper", "own-registry", "child", "declared")}
check("anti-vacuity: the gate saw the tree (≥150 sites, every green bucket non-empty)",
      len(cen) >= 150 and all(by.values()), f"{len(cen)} {by}")
dec = [c for c in cen if c["bucket"] == "declared"]
check("…and the declared bucket stays the SMALL one (fewer than a sixth of all sites)", len(dec) * 6 < len(cen),
      f"{len(dec)} of {len(cen)}")
check("the gate's own residual is stated: branch_check.py and mutation_probe.py are out of its domain",
      "branch_check.py" in (g.__doc__ or "") and "mutation_probe.py" in (g.__doc__ or ""))
check("bucket 1's dependency is stated: green BECAUSE the parent carries the pin (check.sh:51, estate.gate())",
      "check.sh:51" in (g.__doc__ or "") and "estate.gate()" in (g.__doc__ or ""))

print(f"\n{'FAIL' if fails else 'PASS'}: child-env gate ({len(fails)} failing) · {len(cen)} sites {by}")
sys.exit(1 if fails else 0)
