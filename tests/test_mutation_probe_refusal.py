#!/usr/bin/env python3
"""Oracle: when devtools/mutation_probe.py REFUSES (its baseline oracle fails or times out against the unmutated
subject), it prints the oracle's OWN failing lines, so the refusal names its arm (a4 night 10-16; memory #57741: the
parity baseline went red once at load 7.79 and the probe's bare "exit 1" left it unattributable for good).

    MUTATION_PROBE_SRC=<path> …   (the subject; default devtools/mutation_probe.py)

Hermetic: each arm writes a tiny subject, oracle and spec into a temp dir and runs the probe on it as a subprocess.
  R1  a baseline that FAILS: REFUSING, and its failing line is shown even when 60 lines of noise follow it
  R2  a baseline that TIMES OUT: "did not finish", and what it printed before the kill is shown
  R3  a baseline that prints nothing: the refusal says so, never an empty block
  R4  the shown block is capped (≤ REFUSAL_TAIL lines)
  R5  a line that IS a failure beats lines that only mention a keyword (no crowd-out at the cap)
  R6  a subject that can't load from the mutant location REFUSES (the relocated baseline), never grades a no-op CAUGHT
  R7  a same-size mutant right after the baseline is CAUGHT: no cached bytecode of the previous copy stands in for it
  R8  the probe adds no name to the oracle's environment but its ENV seam (unbuffered by `-u`, a flag) and its pinned
      ASTRYX_COG_REGISTRY
  R9  outside any git tree, a subject that resolves by its code-tree tail (pkg/subj.py, its oracle in tests/) loads at
      the mutant location: the baseline passes and its mutant is CAUGHT, never a REFUSE (a3 #60145, a4 10-19)
  R10 inside a git tree, the git root decides the tail, never the oracle: an oracle OUTSIDE the tree gives pkg/subj.py
  R11 no .git but the estate's marker (astryx.py): a subject in tests/ BESIDE its oracle keeps tests/subj.py, as a
      worktree places it, never the bare name the shared directory gives (a3 #60809: 4 specs of 166 live there)
  R12 the oracle never sees the HOST's org registry (plan-11324 S3f S3, a2 #60815): handed a REAL two-org registry by
      its caller (the pulse's probe_all on a cog host), the oracle's ASTRYX_COG_REGISTRY names no file
  R13 a CAUGHT names WHY: its oracle's first CHECK line (never the `FAIL:` summary), and how long it took
  R14 a mutant caught by a CRASH (a Traceback, no check line) says so: the weak catch is never dressed as a check's
  R15 --only PREFIX runs the named mutants alone and the headline never claims the set; a prefix naming none is rc 1
  C1  control: a passing baseline prints no tail block, and its mutant is CAUGHT
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("MUTATION_PROBE_SRC") or REPO / "devtools" / "mutation_probe.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[-400:]}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def probe(td: Path, oracle_body: str, timeout: int = 20, mutants=None, subject: str = "X = 1\n",
          subj_rel: str = "subj.py", oracle_rel: str = "oracle.py", args=()) -> tuple:
    sp, op = td / subj_rel, td / oracle_rel
    for f, body in ((sp, subject), (op, oracle_body)):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    m = mutants or {"M one": ("X = 1", "X = 2")}
    (td / "spec.py").write_text(
        f"SUBJECT = {str(sp)!r}\nORACLE = {str(op)!r}\nENV = 'FIX_SRC'\n"
        f"TIMEOUT = {timeout}\nMUTANTS = {m!r}\n")
    # PYTHONUNBUFFERED out too: an older outer mutation_probe set it for ITS oracle (this file), and inherited here it
    # would make the subject's own buffering unobservable (mutant T6 read NOT PROBED until this line)
    env = {k: v for k, v in os.environ.items() if k not in ("FIX_SRC", "ASTRYX_SQLGUARD_DIR", "PYTHONUNBUFFERED",
                                                         "PYTHONDONTWRITEBYTECODE")}
    # the subject finds `astryx` by its OWN path (dirname(dirname(file))), and mutation_probe writes each mutant into a
    # temp dir: without this every mutant of the probe would die at import and read CAUGHT vacuously
    env["PYTHONPATH"] = str(REPO / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    (td / "probe_env.json").write_text(json.dumps(sorted(env)))   # the names the PROBE was given (arm R8)
    # own-env: inherits; this file's one registry pop (:184) restores an ABSENT parent value in a finally
    r = subprocess.run([sys.executable, str(SUBJECT), str(td / "spec.py"), *args], capture_output=True, text=True,
                       timeout=120, env=env, cwd=td)
    return r.returncode, r.stdout + r.stderr


def shown(out: str) -> list:
    return [ln for ln in out.splitlines() if ln.startswith("    | ")]


with tempfile.TemporaryDirectory() as t:
    t = Path(t)

    d = t / "r1"; d.mkdir()
    noise = "".join(f"print('  ok    noise line {i}')\n" for i in range(60))
    rc, out = probe(d, "print('  PASS  an early arm')\nprint('  FAIL  arm-zeta-42 the arm that broke')\n"
                       + noise + "raise SystemExit(1)\n")
    check("R1 a failing baseline REFUSES (rc 1)", rc == 1 and "REFUSING" in out, out)
    check("R1 …and shows the oracle's failing line, though 60 lines of noise follow it",
          any("arm-zeta-42" in ln for ln in shown(out)), out)

    d = t / "r2"; d.mkdir()
    # NO flush: a real oracle's check() doesn't flush, and a kill discards a block-buffered pipe (a3 #57897 R-1)
    rc, out = probe(d, "import sys, time\nprint('  FAIL  half-done-77 before the hang')\n"
                       "time.sleep(30)\n", timeout=2)
    check("R2 a baseline that times out REFUSES with 'did not finish'", rc == 1 and "did not finish" in out, out)
    check("R2 …and shows what it printed before the kill", any("half-done-77" in ln for ln in shown(out)), out)

    d = t / "r3"; d.mkdir()
    rc, out = probe(d, "raise SystemExit(1)\n")
    check("R3 a silent failing baseline says it printed nothing", rc == 1 and "(it printed nothing)" in out, out)

    d = t / "r4"; d.mkdir()
    many = "".join(f"print('  FAIL  arm {i}')\n" for i in range(80))
    rc, out = probe(d, many + "raise SystemExit(1)\n")
    n = len(shown(out))
    check("R4 the shown block is capped (1..25 lines)", 1 <= n <= 25, f"{n} lines")

    d = t / "r5"; d.mkdir()
    crowd = "".join(f"print('  PASS  label {i} says OperationalError maps to retry')\n" for i in range(30))
    rc, out = probe(d, crowd + "print('  FAIL  real-broken-arm-7')\nprint('FAIL: 1 failing')\nraise SystemExit(1)\n")
    check("R5 a real FAIL is shown even after 30 PASS lines that merely MENTION a keyword (no crowd-out)",
          any("real-broken-arm-7" in ln for ln in shown(out)), out)

    d = t / "r6"; d.mkdir()
    # a subject that reads a file BESIDE itself loads in place and dies at the mutant location: every mutant, a no-op
    # one too, would read CAUGHT (a4 #60129: main.py's paths.estate(__file__) raised NoHome for a tempdir copy)
    (d / "beside.txt").write_text("ok\n")
    rc, out = probe(d, "import os, sys\nsrc = open(os.environ['FIX_SRC']).read()\n"
                       "exec(compile(src, os.environ['FIX_SRC'], 'exec'), {'__file__': os.environ['FIX_SRC']})\n",
                    mutants={"N0 a no-op": ("X = 1", "X = 1 ")},
                    subject="import os\nopen(os.path.join(os.path.dirname(__file__), 'beside.txt')).read()\nX = 1\n")
    check("R6 an unmutated copy that can't load at the mutant location REFUSES (rc 1), never grades a no-op CAUGHT",
          rc == 1 and "REFUSING" in out and not any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()), out)

    d = t / "r7"; d.mkdir()
    # an oracle that IMPORTS its subject reads a cached .pyc when the next copy has the same SIZE and lands in the same
    # mtime second at the same path: the mutant below ran as the unmutated copy and read NOT PROBED (memory #60378, D1)
    # the oracle PINS the copy's mtime first, so "the same second" is certain, not a race (2 of 3 runs RED without it)
    rc, out = probe(d, "import importlib.util, os, sys\nos.utime(os.environ['FIX_SRC'], (1e9, 1e9))\n"
                       "s = importlib.util.spec_from_file_location('subj', os.environ['FIX_SRC'])\n"
                       "m = importlib.util.module_from_spec(s)\ns.loader.exec_module(m)\nsys.exit(0 if m.X == 1 else 1)\n",
                    mutants={"M same size": ("X = 1", "X = 2")})
    check("R7 a SAME-SIZE mutant right after the baseline is CAUGHT (no stale bytecode stands in for it)",
          rc == 0 and any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()), out)

    d = t / "r8"; d.mkdir()
    # the probe adds NO name to its oracle's environment but the ENV seam: org-census's C4 refuses an unclassed name in
    # its own environment, and PYTHONUNBUFFERED=1 from the probe failed every census baseline (seed #60425)
    rc, out = probe(d, "import json, os, sys\n"
                       f"given = set(json.load(open({str(d / 'probe_env.json')!r})))\n"
                       "extra = sorted(set(os.environ) - given - {'FIX_SRC', 'ASTRYX_COG_REGISTRY'})\n"
                       "if extra:\n    print('  FAIL  added by the probe:', extra)\n    sys.exit(1)\n"
                       "sys.exit(0 if 'X = 1' in open(os.environ['FIX_SRC']).read() else 1)\n")
    check("R8 the oracle's environment gains no name from the probe but its ENV seam (baseline passes, mutant CAUGHT)",
          rc == 0 and any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()), out)

    # R9/R10: the subject resolves by its TAIL, as paths.estate's bare-tree rule does (a copy is known by its code-tree
    # tail): it loads only as .../pkg/subj.py. In R10 the tree's own root (gitroot-r10) above pkg/ is right only in place
    # (under r10/); a COPY carrying it under a probe slot was placed by the oracle's directory, not the git root
    tail = ("import sys\nfrom pathlib import Path\nf = Path(__file__)\n"
            "if f.parent.name != 'pkg' or (f.parent.parent.name == 'gitroot-r10' and f.parents[2].name != 'r10'):\n"
            "    sys.exit(f'  no tree tail: {f}')\nX = 1\n")
    runs = ("import os, sys\nsrc = open(os.environ['FIX_SRC']).read()\n"
            "g = {'__file__': os.environ['FIX_SRC'], '__name__': 'subj'}\n"
            "exec(compile(src, os.environ['FIX_SRC'], 'exec'), g)\nsys.exit(0 if g['X'] == 1 else 1)\n")

    d = t / "r9"; d.mkdir()
    rc, out = probe(d, runs, subject=tail, subj_rel="tree/pkg/subj.py", oracle_rel="tree/tests/oracle.py")
    check("R9 no .git: a tail-resolved subject loads at the mutant location (baseline passes, mutant CAUGHT)",
          rc == 0 and "REFUSING" not in out and any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()), out)

    d = t / "r10"; d.mkdir()
    g = d / "gitroot-r10"; g.mkdir()
    # own-env: inherits; this file's one registry pop (:184) restores an ABSENT parent value in a finally
    subprocess.run(["git", "init", "-q", str(g)], check=True, capture_output=True,
                   env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    rc, out = probe(d, runs, subject=tail, subj_rel="gitroot-r10/pkg/subj.py", oracle_rel="outside/oracle.py")
    check("R10 a git tree: the git root decides the tail (pkg/subj.py), never the oracle's shared directory",
          rc == 0 and "REFUSING" not in out and any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()), out)

    d = t / "r11"; d.mkdir()
    (d / "tree").mkdir(); (d / "tree" / "astryx.py").write_text("")
    beside = ("import sys\nfrom pathlib import Path\n"
              "if Path(__file__).parent.name != 'tests':\n    sys.exit(f'  no tree tail: {__file__}')\nX = 1\n")
    rc, out = probe(d, runs, subject=beside, subj_rel="tree/tests/subj.py", oracle_rel="tree/tests/oracle.py")
    check("R11 no .git, the marker decides: a subject beside its oracle in tests/ keeps tests/subj.py (mutant CAUGHT)",
          rc == 0 and "REFUSING" not in out and any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()), out)

    d = t / "r12"; d.mkdir()
    host = d / "host-cog.json"                         # the caller's REAL two-org registry, as the pulse would read /etc
    host.write_text(json.dumps({"orgs": {"fxqa": {"home": str(d / "a"), "db": "fxprobe_a"},
                                         "fxqb": {"home": str(d / "b"), "db": "fxprobe_b"}}}))
    old = os.environ.get("ASTRYX_COG_REGISTRY")
    os.environ["ASTRYX_COG_REGISTRY"] = str(host)
    try:
        rc, out = probe(d, "import os, sys\nfrom pathlib import Path\n"
                           "reg = os.environ.get('ASTRYX_COG_REGISTRY', '')\n"
                           f"if not reg or reg == {str(host)!r} or Path(reg).exists():\n"
                           "    print('  FAIL  the oracle sees the host registry:', reg)\n    sys.exit(1)\n"
                           "sys.exit(0 if 'X = 1' in open(os.environ['FIX_SRC']).read() else 1)\n")
    finally:
        if old is None:
            os.environ.pop("ASTRYX_COG_REGISTRY", None)
        else:
            os.environ["ASTRYX_COG_REGISTRY"] = old
    check("R12 handed a REAL two-org registry, the oracle's ASTRYX_COG_REGISTRY names no file (baseline passes, mutant "
          "CAUGHT)", rc == 0 and "REFUSING" not in out and any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()),
          out)

    def after_caught(out):
        ls = out.splitlines()
        return [ls[i + 1].strip() for i, ln in enumerate(ls[:-1]) if ln.lstrip().startswith("CAUGHT")]

    d = t / "r13"; d.mkdir()
    # each fixture oracle FAILS anything but X = 1 (the canary's destroyed copy too), and reaches its arm on X = 2
    rc, out = probe(d, "import os, sys\nsrc = open(os.environ['FIX_SRC']).read()\nprint('  PASS  arm-ok')\n"
                       "if 'X = 1' not in src:\n"
                       "    print('  FAIL  arm-why-13 the arm that judged it')\n    print('FAIL: 1 failing')\n"
                       "    sys.exit(1)\nprint('PASS: 0 failing')\n")
    caught_ln = next((ln for ln in out.splitlines() if ln.lstrip().startswith("CAUGHT")), "")
    check("R13 a CAUGHT is followed by its why: the oracle's first CHECK line, not its `FAIL:` summary",
          rc == 0 and after_caught(out) == ["why: FAIL  arm-why-13 the arm that judged it"], out)
    check("R13 …and the CAUGHT line ends with its elapsed seconds", caught_ln.rstrip().endswith("s)")
          and caught_ln.rstrip().rsplit("(", 1)[-1][:-2].isdigit(), caught_ln)

    d = t / "r14"; d.mkdir()
    rc, out = probe(d, "import os, sys\nsrc = open(os.environ['FIX_SRC']).read()\nif 'X = 2' in src:\n    1 / 0\n"
                       "sys.exit(0 if 'X = 1' in src else 1)\n")
    w = after_caught(out)
    check("R14 a mutant caught by a CRASH says so, naming the exception (never dressed as a check's catch)",
          rc == 0 and len(w) == 1 and w[0].startswith("why: a CRASH, not a check:") and "ZeroDivisionError" in w[0], out)

    d = t / "r15"; d.mkdir()
    two = {"M one": ("X = 1", "X = 2"), "N two": ("X = 1", "X = 3")}
    body = "import os, sys\nsys.exit(0 if 'X = 1' in open(os.environ['FIX_SRC']).read() else 1)\n"
    rc, out = probe(d, body, mutants=two, args=("--only", "N"))
    cl = [ln.strip() for ln in out.splitlines() if ln.lstrip().startswith("CAUGHT")]
    check("R15 --only N runs N two alone, and the headline names the subset (1 of 2), never the authored set",
          rc == 0 and len(cl) == 1 and "N two" in cl[0] and "1 of 2 authored" in out
          and "Every authored mutant was caught" not in out, out)
    rc, out = probe(d, body, mutants=two, args=("--only", "Z"))
    check("R15 …a prefix naming no mutant is rc 1, never an empty run read as clean",
          rc == 1 and "named by --only" in out and "CAUGHT" not in out, out)

    d = t / "c1"; d.mkdir()
    rc, out = probe(d, "import os, sys\nsys.exit(0 if 'X = 1' in open(os.environ['FIX_SRC']).read() else 1)\n")
    check("C1 control: a passing baseline prints no tail block, and its mutant is CAUGHT",
          rc == 0 and not shown(out) and "CAUGHT" in out, out)

print(f"\n{'FAIL' if fails else 'PASS'}: mutation_probe refusal tail ({len(fails)} failing)")
sys.exit(1 if fails else 0)
