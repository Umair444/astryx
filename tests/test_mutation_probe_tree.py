#!/usr/bin/env python3
"""Oracle: devtools/mutation_probe.py's TREE form (a1 #62024, a4 #62026), the spec whose mutants span several files.
Each MUTANTS value names its file, (path, old, new[, oracle]), and every run happens in a fresh copy of the spec's git
tree, never in the checkout. floor-v2's hand runner, which this form replaces, scored its oracle's crash as 17/17
killed (a1 #62023 R-1).

    MUTATION_PROBE_SRC=<path> …   (the subject; default devtools/mutation_probe.py)

Hermetic: each arm builds a tiny git tree in a temp dir (pkg/a.py, pkg/b.py, an oracle in tests/ that imports both from
its OWN tree) and runs the probe on it as a subprocess.
  P1  a two-file spec: a mutant in each file is CAUGHT (rc 0), and the report groups them under their files
  P2  an anchor that occurs 0 times in ITS file is NOT PROBED (rc 2), while the other file's mutant is still CAUGHT
  P3  an anchor that occurs twice is NOT PROBED, never applied at its first match
  P4  two oracles, one of whose baselines FAILS: REFUSING (rc 1), and no mutant ran (the oracles' own run log)
  P5  a crash-only oracle (it raises against the unmutated tree): REFUSING, never a CAUGHT
  P6  an oracle that reads none of its subjects: WIRING FAULT (the canary), never graded
  P7  a subject outside the tree, or one git doesn't list (gitignored): REFUSING, naming it; nothing is run in place
  P8  the oracle's environment is the probe's, plus only the pinned no-file registry (the single form's rule, R8/R12)
  P9  every file of the checkout is byte-identical after a run with CAUGHT mutants
  P10 a SIGTERM mid-run: the probe exits, the checkout is byte-identical, and no temporary copy is left behind
  P11 a mutant whose oracle SKIPS (77) is NOT PROBED, never CAUGHT
  P12 an oracle and spec git doesn't track yet (untracked, not ignored) still travel into the copy
  P13 --only NAME in the tree form runs that mutant alone, and the headline never claims the set
  P14 a mutant whose oracle doesn't finish is NOT PROBED (TIMED OUT), never CAUGHT
  P15 a baseline that doesn't finish REFUSES with "did not finish" and shows what it printed before the kill
  P16 an oracle that passes the checkout but fails its unmutated COPY (it reads a gitignored file): REFUSING
  C1  control: the single form is untouched (one spec with SUBJECT/ENV is graded exactly as before, rc 0)
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("MUTATION_PROBE_SRC") or REPO / "devtools" / "mutation_probe.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[-600:]}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


ORACLE = """import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
log = os.environ.get("TREE_RUN_LOG")
if log:
    with open(log, "a") as f:
        f.write(str(ROOT) + "\\n")
from pkg import a, b
bad = []
if a.A != 1: bad.append("a")
if b.B != 2: bad.append("b")
for x in bad:
    print("  FAIL  value " + x)
sys.exit(1 if bad else 0)
"""


def git(root: Path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env, timeout=30)


def tree(td: Path, oracles=None, mutants=None, extra=None, commit=True, spec_extra="") -> Path:
    """A git tree: pkg/a.py (A = 1), pkg/b.py (B = 2), tests/oracle*.py, and a tree-form spec tests/mutants_x.py."""
    root = td / "repo"
    files = {"pkg/__init__.py": "", "pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n", ".gitignore": "secret.txt\n"}
    files.update({f"tests/{n}": body for n, body in (oracles or {"oracle.py": ORACLE}).items()})
    files.update(extra or {})
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    m = mutants or {"M1 a moved": ("pkg/a.py", "A = 1", "A = 5"), "M2 b moved": ("pkg/b.py", "B = 2", "B = 7")}
    (root / "tests" / "mutants_x.py").write_text(
        "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
        "ORACLE = ROOT / 'tests' / 'oracle.py'\nTIMEOUT = 20\n" + spec_extra + f"MUTANTS = {m!r}\n")
    git(root, "init", "-q")
    if commit:
        git(root, "add", "-A")
        git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture")
    return root


def probe_env(td: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("MUTATION_PROBE_SRC", "ASTRYX_SQLGUARD_DIR",
                                                         "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE")
           and not k.startswith("GIT_")}
    # the subject finds `astryx` by its OWN path; a mutant copy of it in a temp dir needs the source on the path
    env["PYTHONPATH"] = str(REPO / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["TMPDIR"] = str(td / "tmp")
    (td / "tmp").mkdir(exist_ok=True)
    return env


def run(td: Path, root: Path, args=(), extra_env=None, timeout=200) -> tuple:
    env = dict(probe_env(td), **(extra_env or {}))
    # own-env: the probe's environment is this oracle's, minus its own seam and the git-hook names, plus a private TMPDIR
    r = subprocess.run([sys.executable, str(SUBJECT), str(root / "tests" / "mutants_x.py"), *args],
                       capture_output=True, text=True, timeout=timeout, env=env, cwd=td)
    return r.returncode, r.stdout + r.stderr


def digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts}


def leftovers(td: Path) -> list:
    return sorted(p.name for p in (td / "tmp").glob("astryx-probe-tree-*"))


with tempfile.TemporaryDirectory() as t:
    t = Path(t)

    d = t / "p1"; d.mkdir()
    root = tree(d)
    before = digest(root)
    rc, out = run(d, root)
    check("P1 a two-file spec: a mutant in each file is CAUGHT (rc 0)", rc == 0 and out.count("CAUGHT") >= 2, out)
    check("P1 …grouped under its file", out.find("pkg/a.py") < out.find("M1 a moved") < out.find("pkg/b.py")
          < out.find("M2 b moved"), out)
    check("P9 every file of the checkout is byte-identical after the run", digest(root) == before)
    check("P9 …and no temporary copy is left", leftovers(d) == [], str(leftovers(d)))

    d = t / "p2"; d.mkdir()
    root = tree(d, mutants={"M1 gone": ("pkg/a.py", "A = 9", "A = 5"), "M2 b moved": ("pkg/b.py", "B = 2", "B = 7")})
    rc, out = run(d, root)
    check("P2 an anchor 0x in ITS file is NOT PROBED (rc 2)", rc == 2 and "M1 gone (its anchor occurs 0x in pkg/a.py"
          in out, out)
    check("P2 …and the other file's mutant is still CAUGHT", "CAUGHT" in out and "M2 b moved" in out, out)
    check("P2 …and the headline does not claim the set", "Every authored mutant was caught" not in out, out)

    d = t / "p3"; d.mkdir()
    root = tree(d, extra={"pkg/a.py": "A = 1\nZ = 'A = 1'\n"}, mutants={"M1 twice": ("pkg/a.py", "A = 1", "A = 5")})
    rc, out = run(d, root)
    check("P3 an anchor 2x is NOT PROBED, never applied at its first match", rc == 2 and "occurs 2x" in out
          and "CAUGHT" not in out, out)

    d = t / "p4"; d.mkdir()
    log = d / "runs.log"
    root = tree(d, oracles={"oracle.py": ORACLE, "oracle_red.py": ORACLE.replace("if b.B != 2", "if b.B != 3")},
                mutants={"M1 a moved": ("pkg/a.py", "A = 1", "A = 5"),
                         "M2 b moved, graded by the red oracle": ("pkg/b.py", "B = 2", "B = 7", "tests/oracle_red.py")})
    rc, out = run(d, root, extra_env={"TREE_RUN_LOG": str(log)})
    runs = log.read_text().splitlines() if log.exists() else []
    check("P4 one oracle's baseline FAILS: REFUSING (rc 1)", rc == 1 and "REFUSING" in out and "oracle_red.py" in out,
          out)
    check("P4 …and no mutant ran: only the in-place baselines, from the checkout", runs and all(r == str(root.resolve())
          for r in runs) and len(runs) <= 2 and "CAUGHT" not in out, f"{runs} {out}")

    d = t / "p5"; d.mkdir()
    root = tree(d, oracles={"oracle.py": "raise RuntimeError('this oracle only ever crashes')\n"})
    rc, out = run(d, root)
    check("P5 a crash-only oracle REFUSES, never a CAUGHT", rc == 1 and "REFUSING" in out and "CAUGHT" not in out, out)

    d = t / "p6"; d.mkdir()
    root = tree(d, oracles={"oracle.py": "print('  PASS  reads nothing')\n"})
    rc, out = run(d, root)
    check("P6 an oracle that reads none of its subjects: WIRING FAULT, never graded", rc == 1 and "WIRING FAULT" in out
          and "CAUGHT" not in out, out)

    d = t / "p7"; d.mkdir()
    outside = d / "elsewhere.py"
    outside.write_text("A = 1\n")
    root = tree(d, mutants={"M1 outside": (str(outside), "A = 1", "A = 5")})
    before = outside.read_text()
    rc, out = run(d, root)
    check("P7 a subject outside the tree: REFUSING, naming it", rc == 1 and "outside the tree" in out
          and "elsewhere.py" in out, out)
    check("P7 …and it is never mutated in place", outside.read_text() == before)
    d = t / "p7b"; d.mkdir()
    root = tree(d, extra={"secret.txt": "A = 1\n"}, mutants={"M1 ignored": ("secret.txt", "A = 1", "A = 5")})
    rc, out = run(d, root)
    check("P7 a subject git doesn't list (gitignored): REFUSING, the copy cannot carry it", rc == 1
          and "the copy cannot carry it" in out and "secret.txt" in out, out)

    d = t / "p8"; d.mkdir()
    dump = d / "env.json"
    envo = ("import json, os, sys\njson.dump({'names': sorted(os.environ), 'reg': os.environ.get('ASTRYX_COG_REGISTRY')},"
            f" open({str(dump)!r}, 'w'))\n") + ORACLE
    root = tree(d, oracles={"oracle.py": envo})
    given = probe_env(d)
    rc, out = run(d, root)
    got = json.loads(dump.read_text()) if dump.exists() else {"names": [], "reg": None}
    extra = set(got["names"]) - set(given)
    check("P8 the oracle gets the probe's environment plus only the pinned registry", rc == 0 and extra
          <= {"ASTRYX_COG_REGISTRY"} and set(given) <= set(got["names"]), f"extra={sorted(extra)} rc={rc} {out}")
    check("P8 …and that registry names no file", bool(got["reg"]) and not Path(got["reg"]).exists(), str(got["reg"]))

    d = t / "p10"; d.mkdir()
    slow = ORACLE.replace("from pkg import a, b", "from pkg import a, b\nimport time\nif a.A == 5: time.sleep(60)")
    root = tree(d, oracles={"oracle.py": slow})
    before = digest(root)
    env = probe_env(d)
    p = subprocess.Popen([sys.executable, str(SUBJECT), str(root / "tests" / "mutants_x.py")], env=env, cwd=d,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not any((d / "tmp").glob("astryx-probe-tree-*/m0")):
        time.sleep(0.2)
    in_flight = any((d / "tmp").glob("astryx-probe-tree-*/m0"))
    p.send_signal(signal.SIGTERM)
    try:
        p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
    check("P10 a SIGTERM mid-mutant ends the probe", in_flight and p.returncode is not None, f"in_flight={in_flight}")
    check("P10 …the checkout is byte-identical", digest(root) == before)
    check("P10 …and no temporary copy is left behind", leftovers(d) == [], str(leftovers(d)))

    d = t / "p11"; d.mkdir()
    skipper = ORACLE.replace("from pkg import a, b", "from pkg import a, b\nif a.A == 5:\n    print('SKIP: no')\n"
                                                     "    sys.exit(77)")
    root = tree(d, oracles={"oracle.py": skipper}, mutants={"M1 a moved": ("pkg/a.py", "A = 1", "A = 5")})
    rc, out = run(d, root)
    check("P11 a skipping oracle is NOT PROBED, never CAUGHT", rc == 2 and "oracle SKIPPED" in out
          and "CAUGHT" not in out, out)

    d = t / "p12"; d.mkdir()
    root = tree(d, commit=False)
    rc, out = run(d, root)
    check("P12 an untracked (not ignored) oracle and spec travel into the copy: graded, rc 0", rc == 0
          and "CAUGHT" in out, out)

    d = t / "p13"; d.mkdir()
    root = tree(d)
    rc, out = run(d, root, args=("--only", "M2"))
    check("P13 --only M2 runs M2 alone, and the headline names the selection", rc == 0 and "M2 b moved" in out
          and "M1 a moved" not in out and "Every SELECTED mutant" in out, out)

    d = t / "p14"; d.mkdir()
    root = tree(d, oracles={"oracle.py": slow}, mutants={"M1 a moved": ("pkg/a.py", "A = 1", "A = 5")},
                spec_extra="TIMEOUT = 3\n")
    (root / "tests" / "mutants_x.py").write_text((root / "tests" / "mutants_x.py").read_text()
                                                 .replace("TIMEOUT = 20\n", ""))
    rc, out = run(d, root)
    check("P14 a mutant whose oracle doesn't finish is NOT PROBED (TIMED OUT), never CAUGHT", rc == 2
          and "TIMED OUT after 3s" in out and "CAUGHT" not in out, out)

    d = t / "p15"; d.mkdir()
    hang = "import time\nprint('  FAIL  half-done-91 before the hang')\ntime.sleep(30)\n"
    root = tree(d, oracles={"oracle.py": hang}, spec_extra="TIMEOUT = 2\n")
    (root / "tests" / "mutants_x.py").write_text((root / "tests" / "mutants_x.py").read_text()
                                                 .replace("TIMEOUT = 20\n", ""))
    rc, out = run(d, root)
    check("P15 a baseline that doesn't finish REFUSES with 'did not finish'", rc == 1 and "did not finish" in out, out)
    check("P15 …and shows what it printed before the kill", "half-done-91" in out, out)

    d = t / "p16"; d.mkdir()
    needs = ORACLE.replace("from pkg import a, b", "from pkg import a, b\nassert (ROOT / 'secret.txt').exists()")
    root = tree(d, oracles={"oracle.py": needs}, extra={"secret.txt": "x\n"})
    rc, out = run(d, root)
    check("P16 an oracle that fails its unmutated COPY (a gitignored read): REFUSING", rc == 1
          and "fails its unmutated COPY" in out and "CAUGHT" not in out, out)

    d = t / "c1"; d.mkdir()
    (d / "subj.py").write_text("X = 1\n")
    (d / "oracle.py").write_text("import os, runpy, sys\nx = runpy.run_path(os.environ['FIX_SRC'])['X']\n"
                                 "sys.exit(0 if x == 1 else 1)\n")
    (d / "spec.py").write_text(f"SUBJECT = {str(d / 'subj.py')!r}\nORACLE = {str(d / 'oracle.py')!r}\nENV = 'FIX_SRC'\n"
                               "MUTANTS = {'M one': ('X = 1', 'X = 2')}\n")
    r = subprocess.run([sys.executable, str(SUBJECT), str(d / "spec.py")], capture_output=True, text=True,
                       timeout=120, env=probe_env(d), cwd=d)
    check("C1 control: a single-form spec is graded as before (rc 0, CAUGHT, no tree-form header)", r.returncode == 0
          and "CAUGHT" in r.stdout and "tree form" not in r.stdout, r.stdout + r.stderr)

print(f"\n{'PASS' if not fails else 'FAIL'}: mutation_probe tree form ({len(fails)} failing)")
sys.exit(1 if fails else 0)
