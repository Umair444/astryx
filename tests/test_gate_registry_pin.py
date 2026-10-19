"""estate.gate() pins the cog registry for a gate run BY HAND, as check.sh does for the suite (seed 10-19: the relay oracle
run bare on the cog host, started its fixture gateways under /etc/astryx/cog.json, and 'orga.test' introduced itself
to the LIVE seed).

  P1 unset: after gate(), ASTRYX_COG_REGISTRY names a path that is no file, and never the host default
     (RED on the old gate: the variable stays unset, so orgs.load reads /etc/astryx/cog.json).
  P2 set: a value already in the env (check.sh's, or an oracle's own registry) stands.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHILD = ("import os, sys; sys.path.insert(0, sys.argv[1]); from astryx.security.sqlguard.estate import gate; "
         "gate('p', sys.argv[2], deps=(), env=False); print(os.environ.get('ASTRYX_COG_REGISTRY', '<unset>'))")
fails = []


def child(extra):
    env = {k: v for k, v in os.environ.items() if k != "ASTRYX_COG_REGISTRY"}
    env.update(extra)
    r = subprocess.run([sys.executable, "-B", "-c", CHILD, str(REPO / "src"), str(REPO)], env=env,
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout.strip().splitlines()[-1:] or [r.stderr[-300:]]


def check(name, ok, got):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f": got {got!r}"))
    if not ok:
        fails.append(name)


rc, (got,) = child({})
check("P1 unset: pinned to a path that names no file", rc == 0 and got != "<unset>" and "no-registry" in got
      and not Path(got).exists() and got != "/etc/astryx/cog.json", got)
rc, (got,) = child({"ASTRYX_COG_REGISTRY": "/nonexistent/oracle/cog.json"})
check("P2 set: an oracle's own registry stands", rc == 0 and got == "/nonexistent/oracle/cog.json", got)
print(f"{2 - len(fails)}/2 passed")
sys.exit(1 if fails else 0)
