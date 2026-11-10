#!/usr/bin/env python3
"""Oracle: no gate sees the HOST's org registry (plan-11324 S3f S3, seed #60778 item 4).

`/etc/astryx/cog.json` is a host FILE that no env scrub removes (pushed_tree_check scrubs ASTRYX_*, but a file isn't an
env var), so on a cog host every gate would run under multi. check.sh pins ASTRYX_COG_REGISTRY to a path that names no
file before its first estate read, so a gate runs as this checkout's own org: in a cog, the PRIMARY's (its HOME is
the checkout), exactly as before the cog.

The caller here stands in for a cog host: it hands check.sh a REAL two-org registry by ASTRYX_COG_REGISTRY (the env
form of the host file), and the arms watch what a gate is given:
  P0 positive control: outside check.sh, `orgs.py multi` reads the caller's registry as a cog (exit 0)
  P1 check.sh sourced (CHECK_LIB_ONLY, test_check_noagent's seam): ASTRYX_COG_REGISTRY is no longer the caller's, and
     names no file
  P2 a gate run through the REAL run(): inside it `orgs.py multi` answers one org (exit 1), under that pinned path
CHECK_SH_SRC: a mutant check.sh (tests/mutants_check_registry_pin.py). Exit 0 pass · 1 fail.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = Path(os.environ.get("CHECK_SH_SRC") or REPO / "devtools" / "check.sh")
PY = sys.executable
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def main():
    with tempfile.TemporaryDirectory(prefix="regpin-") as t:
        t = Path(t)
        reg = t / "cog.json"
        reg.write_text('{"orgs": {"fxpa": {"home": "%s/a", "db": "fxpin_a"}, "fxpb": {"home": "%s/b", "db": "fxpin_b"}}}'
                       % (t, t))
        env = {k: v for k, v in os.environ.items() if k not in ("TMPDIR", "CHECK_GATE_TIMES", "ASTRYX_SQLGUARD_DIR")}
        env.update({"ASTRYX_COG_REGISTRY": str(reg), "TMPDIR": str(t), "PY": PY})
        multi = [PY, str(REPO / "src" / "astryx" / "orgs.py"), "multi"]

        print("P0 THE CALLER'S REGISTRY IS A COG (positive control)")
        r = subprocess.run(multi, env=env, cwd=REPO, capture_output=True, text=True, timeout=60)
        check("outside check.sh, `orgs.py multi` reads it as several orgs (exit 0)", r.returncode == 0,
              f"rc {r.returncode} {r.stderr[-200:]}")

        print("\nP1 CHECK.SH PINS A REGISTRY THAT NAMES NO FILE")
        r = subprocess.run(["bash", "-c", f'CHECK_LIB_ONLY=1 . "{CHECK}" >/dev/null 2>&1; '
                                          'echo "${ASTRYX_COG_REGISTRY-UNSET}"'],
                           env=env, cwd=REPO, capture_output=True, text=True, timeout=120)
        pinned = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        check("sourced, ASTRYX_COG_REGISTRY is no longer the caller's", pinned and pinned != "UNSET"
              and pinned != str(reg), repr(pinned))
        check("...and names no file (orgs.load reads it as absent: one org)", pinned and not Path(pinned).exists(),
              repr(pinned))

        print("\nP2 A GATE RUN BY check.sh's run() SEES ONE ORG")
        out = t / "gate.out"
        body = (f'run "fx registry probe" bash -c \'echo "$ASTRYX_COG_REGISTRY" > "{out}"; '
                f'"{PY}" "{REPO}/src/astryx/orgs.py" multi; echo "rc=$?" >> "{out}"; exit 0\'')
        r = subprocess.run(["bash", "-c", f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\n{body}\n'],
                           env=env, cwd=REPO, capture_output=True, text=True, timeout=120)
        got = out.read_text().split() if out.exists() else []
        check("the gate ran (anti-vacuity: it wrote its report)", len(got) == 2, (r.stdout + r.stderr)[-300:])
        check("inside the gate `orgs.py multi` answers ONE org (exit 1): the host's cog is invisible to it",
              len(got) == 2 and got[1] == "rc=1", str(got))
        check("...under a pinned path that names no file, never the caller's", len(got) == 2 and got[0] != str(reg)
              and not Path(got[0]).exists(), str(got))


if __name__ == "__main__":
    main()
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
          "check.sh registry pin: no gate sees the host's org registry; each runs as the checkout's own org")
    sys.exit(1 if fails else 0)
