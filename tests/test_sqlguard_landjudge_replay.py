#!/usr/bin/env python3
"""The land judge on the SHIPPED case (plan-11908 D6's required arm, a4 #62645): /chat f46eb3e5 added 4 SQL sites in
observatory/api/chat.py::work and landed green; fb4800b's D4 arms were what made them RESPONSIVE.

    venv/bin/python tests/test_sqlguard_landjudge_replay.py      (needs the fixture DB: the oracle is test_chat_api)

A --shared clone of this repo (no write to it) gets two tips over A = f46eb3e5^:
  R1 B  = f46eb3e5 with the oracle as it stood just before fb4800b (1cc447e8's R6 hermeticity fix, so it runs off the
     live estate): the land judge REFUSES, naming the chat.py::work keys
  R2 B+ = B + fb4800b's tests/test_chat_api.py (its D4 arms): the land judge PASSES
  R3 D8: the costs, measured on this replay (inventories, oracle under the shim vs bare, judge), printed
The clone has no .env (never linked): the admin DSN is resolved here and handed to the children by env, never printed.
Exit 0 pass · 1 fail · 77 no fixture DB or no .git (nothing verified).
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard import landjudge as lj  # noqa: E402

SHIPPED, ARMS, ORACLE = "f46eb3e5", "fb4800b0", "tests/test_chat_api.py"
fails = []
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


def git(r, *a, inp=None):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r, env=ENV, input=inp,
                          capture_output=True, text=True, check=True).stdout.strip()


def main():
    if not (REPO / ".git").exists():
        print("NOT SEARCHED: no .git (an extract): nothing to replay")
        return 77
    try:
        from astryx.security.sqlguard.fixture import live_dsn
        admin = live_dsn()
    except Exception as e:                                       # noqa: BLE001
        print(f"NOT SEARCHED: no fixture admin DSN ({type(e).__name__}): the oracle needs the fixture DB")
        return 77
    os.environ["ASTRYX_FIXTURE_ADMIN_DSN"] = admin               # the clone has no .env; children inherit it
    with tempfile.TemporaryDirectory(prefix="lj-replay-") as td:
        c = Path(td) / "c"
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(REPO), str(c)], env=ENV, check=True)
        a = git(c, "rev-parse", f"{SHIPPED}^")
        git(c, "checkout", "-q", "-b", "shipped", SHIPPED)
        # the oracle as it stood just BEFORE fb4800b (1cc447e8's R6 hermeticity fix included, so it can run here):
        # f46eb3e5's sites, without the D4 arms
        git(c, "checkout", f"{ARMS}^", "--", ORACLE)
        git(c, "commit", "-qm", "the oracle before fb4800b", "--allow-empty")
        b = git(c, "rev-parse", "HEAD")
        lines = []
        start = set(Path(tempfile.gettempdir()).glob("landjudge-trace-*"))
        rc = lj.land_judge(a, b, c, [ORACLE], log=lines.append)
        for d in set(Path(tempfile.gettempdir()).glob("landjudge-trace-*")) - start:   # R1's kept trace: ours, by design
            __import__("shutil").rmtree(d, ignore_errors=True)
        out = "\n".join(lines)
        print("\n".join(f"    | {x}" for x in lines))
        work = [x for x in lines if "R-NEW-introduced observatory/api/chat.py::work" in x]
        arm("R1 f46eb3e5 as shipped is REFUSED, naming the chat.py::work keys",
            rc == 1 and len(work) >= 1 and "land judge: REFUSED" in out, f"rc={rc}, {len(work)} work line(s)")

        git(c, "checkout", ARMS, "--", ORACLE)                  # + fb4800b's D4 arms
        git(c, "commit", "-qm", "fb4800b's D4 arms")
        bp = git(c, "rev-parse", "HEAD")
        lines = []
        traces = lambda: set(Path(tempfile.gettempdir()).glob("landjudge-trace-*"))
        before = traces()
        rc2 = lj.land_judge(a, bp, c, [ORACLE], log=lines.append)
        print("\n".join(f"    | {x}" for x in lines))
        arm("R2 f46eb3e5 + fb4800b's D4 arms PASSES the land judge", rc2 == 0 and "land judge: PASS" in lines[-1],
            f"rc={rc2}: {lines[-1] if lines else ''}")
        arm("R2 ...and its trace dir is gone (removed on green)", not (traces() - before), sorted(traces() - before))

        t = time.monotonic()
        bare = subprocess.run([sys.executable, ORACLE], cwd=c, env={k: v for k, v in os.environ.items()
                                                                   if not k.startswith("ASTRYX_SQLGUARD_")},
                              capture_output=True, timeout=900).returncode
        bare_s = time.monotonic() - t
        cost = next((x for x in lines if "cost (D8)" in x), "")
        print(f"  D8 cost: {cost.strip()}; the oracle BARE (no shim): {bare_s:.1f}s rc {bare}")
        arm("R3 D8 costs measured and printed (inventories, oracles under the shim, judge; bare oracle for the shim's "
            "overhead)", bool(cost) and bare == 0, cost)
    print(("PASS: land judge replay" if not fails else f"FAIL: {len(fails)} arm(s)") + " (0 failing)" * (not fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
