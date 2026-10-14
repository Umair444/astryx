"""Oracle: devtools/identity_gate.py, plan-10224 D1's CODE identity gate (which astryx a tree's python imports).

The fixture arms run the REAL probes with -S, so the live venv's site-packages can't decide them, and each
fixture install is a site dir whose .pth names a src/ (what `pip install -e` writes):
  G1  nothing installed                          -> PASS (outside absent, inside this tree)
  G2  an install of a FOREIGN copy (main, PyPI)  -> RED, naming the foreign path
  G3  an install of THIS tree's own src          -> PASS (outside == inside)
  G4  a BROKEN install (its __init__ raises)     -> RED, never read as "nothing installed"
  G5  a tree whose root shim can't reach src/    -> RED (the inside reading is checked too)
  G6  LIVE: this tree with the real interpreter  -> PASS today; the first install that shadows it turns it RED
Mutants: tests/mutants_identity_gate.py.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = Path(os.environ.get("IDENTITY_GATE_SRC", REPO / "devtools" / "identity_gate.py"))
ns: dict = {"__name__": "identity_gate_under_test"}
exec(compile(SUBJECT.read_text(), str(SUBJECT), "exec"), ns)
check = ns["check"]
PY = sys.executable

fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f" :: {detail}"))
    fails += 0 if ok else 1


def site_for(tmp: Path, name: str, src: Path) -> Path:
    d = tmp / f"site-{name}"
    d.mkdir()
    (d / f"_{name}.pth").write_text(f"{src}\n")
    return d


tmp = Path(tempfile.mkdtemp(prefix="identity-gate-oracle-"))
try:
    foreign = tmp / "foreign" / "src"
    shutil.copytree(REPO / "src" / "astryx", foreign / "astryx", ignore=shutil.ignore_patterns("__pycache__"))
    broken = tmp / "broken" / "src"
    (broken / "astryx").mkdir(parents=True)
    (broken / "astryx" / "__init__.py").write_text("raise RuntimeError('half-installed')\n")
    shimless = tmp / "shimless"
    shimless.mkdir()
    shutil.copy(REPO / "astryx.py", shimless / "astryx.py")          # the root shim, with no src/ beside it

    probs, out, ins = check(REPO, PY, nosite=True)
    arm("G1 nothing installed -> PASS", probs == [] and out[0] == "absent" and ins[0] == "path", (probs, out, ins))

    probs, out, ins = check(REPO, PY, sites=(site_for(tmp, "foreign", foreign),), nosite=True)
    arm("G2 a foreign install -> RED, naming it", len(probs) == 1 and str(foreign) in probs[0], (probs, out))

    probs, out, ins = check(REPO, PY, sites=(site_for(tmp, "own", REPO / "src"),), nosite=True)
    arm("G3 this tree's own src installed -> PASS", probs == [] and out[0] == "path", (probs, out, ins))

    probs, out, ins = check(REPO, PY, sites=(site_for(tmp, "broken", broken),), nosite=True)
    arm("G4 a broken install -> RED, not 'absent'", out[0] == "error" and len(probs) == 1, (probs, out))

    probs, out, ins = check(shimless, PY, nosite=True)
    arm("G5 the root shim can't reach src/ -> RED", ins[0] != "path" and len(probs) == 1, (probs, ins))

    probs, out, ins = check(REPO, PY)
    arm("G6 LIVE: this tree imports only its own astryx", probs == [], probs)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if fails:
    print(f"FAILED: identity gate ({fails} failing)")
    sys.exit(1)
print("ALL PASS: identity gate (0 failing)")
