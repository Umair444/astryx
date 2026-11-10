#!/usr/bin/env python3
"""The goal 10224 S4 reorg census: every moved module's root is the repo root, and every stub IS its module.

For each row of devtools/reorg/map.tsv whose module moved:
  R1  it imports, and its REPO / ROOT / LIVE (where it has one) equals the checkout root (astryx.paths.repo_root());
  R2  its source computes no root from `Path(__file__)...parents[n]` / `.parent.parent` (the one helper does it);
  S1  `import nucleus.<x>` returns the SAME module object as `import astryx.<sub>.<x>` (an alias, never a copy);
  S2  a stub run as a script and with -m behaves as the moved module does (same stdout, same rc);
  S3  a sourced shell stub sources its target, and an exec'd one runs it with the same argv.
Exit 0 pass, 1 fail, 77 when the reorg isn't applied in this tree (the map's new paths are absent).
"""
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

# R1 must see what a pushed-tree clone sees: config.dsn() falls back to the ENVIRONMENT, so a caller's exported DSN would
# let a module that reads it at import pass here and fail every clone (a1 #62279). Drop it before any import.
for _k in ("ASTRYX_DSN", "ASTRYX_FIXTURE_ADMIN_DSN"):
    os.environ.pop(_k, None)
os.environ["ASTRYX_COG_REGISTRY"] = "/nonexistent/cog.json"   # and the host's registry can't point ESTATE at a live HOME (a1 #62283)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PY = sys.executable
MAP = REPO / "devtools" / "reorg" / "map.tsv"

rows = []
for line in MAP.read_text().splitlines():
    if line.strip() and not line.startswith("#"):
        old, new, mod = line.split("\t")
        if not old.endswith("/"):
            rows.append((old, new, None if mod == "-" else mod))
if not all((REPO / n).exists() for _, n, _ in rows):
    print("SKIP: the reorg map is not applied in this tree")
    sys.exit(77)

from astryx.paths import repo_root  # noqa: E402

fails = []
root = repo_root()
if root != REPO:
    fails.append(f"astryx.paths.repo_root() = {root}, not this checkout {REPO}")

# apply.py's ROOT_EXEMPT: a module that ships itself alone (the sandbox probe) keeps its own, same-depth root
ROOT_EXEMPT = {"devtools/branch_check_sandbox.py"}
ROOT_EXPR = re.compile(r"Path\(__file__\)\.resolve\(\)\.(parents\[\d\]|parent\.parent(?!\.))")
checked = 0
for old, new, mod in rows:
    if not mod:
        continue
    src = (REPO / new).read_text()
    if ROOT_EXPR.search(src) and new not in ROOT_EXEMPT:
        fails.append(f"R2 {new}: computes a root from __file__ instead of astryx.paths.repo_root()")
    try:
        m = importlib.import_module(mod)
    except ModuleNotFoundError as e:
        if e.name and e.name.split(".")[0] in ("astryx", "nucleus", "devtools"):
            fails.append(f"R1 {mod}: {e}")
        else:
            print(f"  note: {mod} needs {e.name}, not installed here; R1/S1 not checked for it")
        continue
    except FileNotFoundError as e:
        if str(e.filename or "").endswith("/.env"):  # it reads the org's .env at import: a clone without one
            print(f"  note: {mod} reads .env at import and there is none here; R1/S1 not checked for it")
            continue
        fails.append(f"R1 {mod}: import raised FileNotFoundError: {e}")
        continue
    except BaseException as e:                       # a module that exits or raises at import is a failure here
        fails.append(f"R1 {mod}: import raised {type(e).__name__}: {e}")
        continue
    for name in ("REPO", "ROOT") + (("LIVE",) if mod.endswith(".rekey") else ()):   # branch_check's LIVE is the live org
        v = getattr(m, name, None)
        if isinstance(v, Path) and v.resolve() != REPO:
            fails.append(f"R1 {mod}.{name} = {v}, not the repo root {REPO}")
    legacy = old[:-3].replace("/", ".").removesuffix(".__init__")
    try:
        if importlib.import_module(legacy) is not m:
            fails.append(f"S1 {legacy} is not the same object as {mod}")
    except BaseException as e:
        fails.append(f"S1 import {legacy}: {type(e).__name__}: {e}")
    checked += 1


def run(argv, **kw):
    r = subprocess.run(argv, cwd=kw.get("cwd", REPO), capture_output=True, text=True, timeout=120,
                       env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    return r.returncode, r.stdout


# S2: by path and by -m, through the stub, behave as the moved module does
want = run([PY, "src/astryx/core/toolreg.py", "list"])
for argv in ([PY, "nucleus/toolreg.py", "list"], [PY, "-m", "nucleus.toolreg", "list"]):
    got = run(argv)
    if got != want:
        fails.append(f"S2 {' '.join(argv[1:])}: rc/stdout differ from the moved module's ({got[0]} vs {want[0]})")
got = run([PY, str(REPO / "nucleus" / "toolreg.py"), "list"], cwd="/")
if got != want:
    fails.append("S2 nucleus/toolreg.py run by absolute path from / differs from the moved module")

# S3: a sourced shell stub sources, an exec'd one passes argv through
src_new = run(["bash", "-c", '. scripts/pgcontainer.sh; echo "PG=$PG_CONTAINER"'])
src_old = run(["bash", "-c", '. nucleus/pgcontainer.sh; echo "PG=$PG_CONTAINER"'])
if src_old != src_new or "PG=" not in src_old[1]:
    fails.append(f"S3 sourcing nucleus/pgcontainer.sh: {src_old} vs {src_new}")
ex = run(["bash", "nucleus/estate_grep.sh"])
ex_new = run(["bash", "devtools/estate_grep.sh"])
if ex != ex_new:
    fails.append(f"S3 nucleus/estate_grep.sh (no args) differs from devtools/estate_grep.sh: {ex} vs {ex_new}")

for f in fails:
    print("  ✗", f)
print(f"reorg census: {checked} moved modules imported and aliased; {len(fails)} failures")
sys.exit(1 if fails else 0)
