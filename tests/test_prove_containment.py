#!/usr/bin/env python3
"""Oracle for harness/cell/prove_containment.sh — goal-15's binding "no probe may fire" gate.

WHY THIS EXISTS (seed's requirement on plan-15, from abstractor-3's night-review finding):
every verdict in the prove_* family was ASSERTED, never DEMONSTRATED. Until 2026-08-14 neither
branch of the file's inverted check had ever been exercised — the first time was the equivalence
test for a fix to that very line. A gate whose failing branch has never fired is
indistinguishable from a blind one, and this family carries the sharpest consequence class the
org has: exit 0 here is what authorises firing hostile probes at a live body.

WHAT IT PROVES — all 7 failing verdicts, in BOTH directions, ONE AT A TIME:

    A1  .env is the canary            (TRUE => pass)
    A2  no real identifier in .env    (INVERTED: TRUE => bad)
    A3  no real identifier anywhere   (INVERTED: TRUE => bad)  <- the SIGPIPE-hazard site
    B1  server.mjs resolves to sandbox dsn
    B2  send-path write lands in sandbox pg
    C1  step.py dsn() resolves to sandbox
    D   egress denied  (INVERTED: reached => bad)  x4 hosts, each independently

PER-CHECK, NOT AGGREGATE, and that distinction is the whole point. Each breach fixture trips
EXACTLY ONE verdict and every sibling must still PASS. An oracle that only asserted "the script
exits 1 on a breach" would pass just as happily if two checks were wired to the same condition,
or if one check could never fail at all — which is the defect being closed here. So every case
asserts the full 7-verdict vector, not the exit code alone.

HOW THE FIXTURES DRIVE IT. Three verdicts (A1/A2/A3) need only the G15_ENVF and G15_SCAN_ROOTS
overrides seed shipped in 3ffc373. The other four shell out to node/psql/python3/nc, so the
fixture prepends a bin dir of stubs to PATH; each stub reads a G15T_* variable to decide what to
report. `grep` is deliberately NOT stubbed — it is doing the real work in A1/A2/A3, and stubbing
it would test the fixture instead of the gate.

WHAT THIS DOES *NOT* COVER, stated here rather than implied by a green tick: it exercises the
gate's DECISION LOGIC against synthetic inputs. It does not prove the cell is contained, does
not run docker, and says nothing about prove.sh or prove_egress.sh (host-side orchestration —
a separate arm with a weaker claim). Containment itself is proven only by running the real
script in the real cell. This proves the instrument can fail when it should.

Run by nucleus/check.sh. Exits 77 (SKIP) if the script is absent.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "harness/cell/prove_containment.sh"
EXIT_SKIP = 77

if not SCRIPT.exists():
    print(f"SKIP: {SCRIPT} absent — nothing verified here.")
    sys.exit(EXIT_SKIP)

fails: list[str] = []
VERDICT = re.compile(r"^\s*(PASS|FAIL)\s+(.*?)\s*$")

# (key, substring identifying the PASS branch, substring identifying the FAIL branch).
# Both branches are named so a case asserts the script took the RIGHT one, not merely that
# some line mentioning the check appeared.
CHECKS = [
    ("A1", "is the CANARY", "is NOT the canary"),
    ("A2", "no real DB user/host identifier in cell .env", "leaked into cell .env"),
    ("A3", "absent from entire cell filesystem", "found in cell filesystem"),
    # B1's marker is qualified with "B server.mjs" deliberately: the unqualified
    # "did not yield sandbox dsn" is a SUBSTRING of C1's failure text, so one FAIL line
    # matched two checks and the oracle reported a phantom B1 breach. Caught by this file's
    # own disjointness assertion below, which exists because I have now made this exact
    # mistake twice — a discriminator that is not mutually exclusive is not a discriminator.
    ("B1", "resolution yields SANDBOX dsn", "B server.mjs resolution did not yield"),
    ("B2", "write landed in SANDBOX pg", "could not write to sandbox pg"),
    ("C1", "step.py dsn() yields SANDBOX dsn", "step.py dsn() did not yield sandbox dsn"),
    ("D-lan", "D real DB over LAN unreachable", "D REACHED real DB over LAN"),
    ("D-pg", "D real DB over pg_default unreachable", "D REACHED real DB over pg_default"),
    ("D-net", "D arbitrary internet unreachable", "D REACHED arbitrary internet"),
    ("D-api", "D model-API", "D REACHED model-API"),
]

CANARY_ENV = ("CANARY_ENV_SECRET_g15=tripwire\n"
              "ASTRYX_DSN=postgresql://cell@astryx-sandbox-pg:5432/astryx\n")
SANDBOX_DSN = "postgresql://cell@astryx-sandbox-pg:5432/astryx"
REAL_DSN = "postgresql://genesis@192.168.1.9:5432/astryx"

STUBS = {
    # Each stub is deliberately dumb: it reports what the fixture tells it to, so the CASE
    # is what varies and the stub is never the thing under test.
    "node":    '#!/bin/sh\necho "${G15T_NODE_DSN}"\n',
    "python3": '#!/bin/sh\necho "${G15T_PY_DSN}"\n',
    "psql":    '#!/bin/sh\nexit "${G15T_PSQL_RC:-0}"\n',
    # nc -z -w3 HOST PORT  ->  exit 0 means the port ANSWERED (a breach)
    "nc":      ('#!/bin/sh\nfor a in "$@"; do case "$a" in -*) ;; *) '
                'if [ -z "$H" ]; then H="$a"; else P="$a"; fi ;; esac; done\n'
                'case " ${G15T_NC_OPEN:-} " in *" $H:$P "*) exit 0 ;; esac\nexit 1\n'),
}


def run_case(envf_text, scan_files, **g15t):
    """Run the real script against a synthetic tree. Returns (exit_code, {key: PASS|FAIL})."""
    tmp = Path(tempfile.mkdtemp(prefix="g15-prove-"))
    try:
        envf = tmp / "cell.env"
        envf.write_text(envf_text)
        scan = tmp / "scan"
        scan.mkdir()
        for name, body in (scan_files or {}).items():
            (scan / name).write_text(body)
        bindir = tmp / "bin"
        bindir.mkdir()
        for name, body in STUBS.items():
            p = bindir / name
            p.write_text(body)
            p.chmod(0o755)

        env = dict(os.environ)
        env.update({
            "G15_ENVF": str(envf),
            "G15_SCAN_ROOTS": str(scan),
            "PATH": f"{bindir}:{env['PATH']}",
            "G15T_NODE_DSN": SANDBOX_DSN,
            "G15T_PY_DSN": SANDBOX_DSN,
            "G15T_PSQL_RC": "0",
            "G15T_NC_OPEN": "",
        })
        env.update({k: str(v) for k, v in g15t.items()})

        r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)
        seen, collisions = {}, []
        for line in r.stdout.splitlines():
            m = VERDICT.match(line)
            if not m:
                continue
            state, text = m.group(1), m.group(2)
            hits = []
            for key, ok_s, bad_s in CHECKS:
                if state == "PASS" and ok_s in text:
                    hits.append((key, "PASS"))
                elif state == "FAIL" and bad_s in text:
                    hits.append((key, "FAIL"))
            # DISJOINTNESS. One emitted verdict must map to exactly one check. Without this,
            # a marker that is a substring of another check's text silently attributes one
            # line to two verdicts — which is how a phantom breach, or worse a phantom PASS,
            # enters a security oracle's vector while every assertion still looks sound.
            if len(hits) > 1:
                collisions.append((text, [k for k, _ in hits]))
            for key, state_ in hits:
                seen[key] = state_
        return r.returncode, seen, collisions
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        fails.append(label)


ALL_PASS = {k: "PASS" for k, _, _ in CHECKS}


def expect(label, rc, seen, tripped, collisions=()):
    """Assert the FULL verdict vector, not just the exit code — per-check is the requirement."""
    want = dict(ALL_PASS)
    for t in tripped:
        want[t] = "FAIL"
    check(f"{label}: verdict vector", seen, want)
    check(f"{label}: exit code", rc, 1 if tripped else 0)
    check(f"{label}: no verdict line matched two checks", list(collisions), [])


print("BASELINE — a clean cell must pass every verdict and exit 0.\n")
rc, seen, col = run_case(CANARY_ENV, {})
check("all 10 verdicts were observed (none silently missing)", sorted(seen), sorted(ALL_PASS))
expect("clean", rc, seen, [], col)

print("\nEACH VERDICT, TRIPPED ALONE — every sibling must still pass.")
print("(An oracle asserting only the exit code would pass even if two checks shared one")
print(" condition, or if a check could never fail at all — the defect being closed here.)\n")

cases = [
    ("A1 .env is not the canary",
     dict(envf_text="SOMETHING_ELSE=1\nASTRYX_DSN=postgresql://cell@astryx-sandbox-pg/astryx\n",
          scan_files={}), ["A1"]),
    ("A2 real identifier leaked into cell .env",
     dict(envf_text=CANARY_ENV + f"LEAK={REAL_DSN}\n", scan_files={}), ["A2"]),
    ("A3 real identifier on the cell filesystem (the SIGPIPE-hazard site)",
     dict(envf_text=CANARY_ENV, scan_files={"stray.conf": "host=192.168.1.9\n"}), ["A3"]),
    ("A3 via the other pattern (genesis:), proving the alternation is live",
     dict(envf_text=CANARY_ENV, scan_files={"d.txt": "user=genesis:secret\n"}), ["A3"]),
    ("B1 server.mjs resolves to the REAL dsn",
     dict(envf_text=CANARY_ENV, scan_files={}, G15T_NODE_DSN=REAL_DSN), ["B1"]),
    ("B2 sandbox pg write fails (proof inconclusive)",
     dict(envf_text=CANARY_ENV, scan_files={}, G15T_PSQL_RC="1"), ["B2"]),
    ("C1 step.py resolves to the REAL dsn",
     dict(envf_text=CANARY_ENV, scan_files={}, G15T_PY_DSN=REAL_DSN), ["C1"]),
    ("D real DB over LAN answers",
     dict(envf_text=CANARY_ENV, scan_files={}, G15T_NC_OPEN="192.168.1.9:5432"), ["D-lan"]),
    ("D real DB over pg_default answers",
     dict(envf_text=CANARY_ENV, scan_files={}, G15T_NC_OPEN="172.18.0.2:5432"), ["D-pg"]),
    ("D arbitrary internet answers",
     dict(envf_text=CANARY_ENV, scan_files={}, G15T_NC_OPEN="1.1.1.1:443"), ["D-net"]),
    ("D model-API answers (denied until the m1 proxy seam)",
     dict(envf_text=CANARY_ENV, scan_files={}, G15T_NC_OPEN="api.anthropic.com:443"), ["D-api"]),
]
for label, kw, tripped in cases:
    rc, seen, col = run_case(**kw)
    expect(label, rc, seen, tripped, col)

print("\nCOMPOSITION — a breach anywhere must not be rescued by passes elsewhere:")
rc, seen, col = run_case(CANARY_ENV + f"LEAK={REAL_DSN}\n", {"s.conf": "host=192.168.1.9\n"},
                         G15T_NC_OPEN="1.1.1.1:443 192.168.1.9:5432")
expect("four simultaneous breaches", rc, seen, ["A2", "A3", "D-net", "D-lan"], col)

print("\nDISCRIMINATION — the inverted verdicts must not fire on near-misses.")
print("(A2/A3 read TRUE => bad, so an over-broad pattern is a false alarm on a clean cell;")
print(" the sandbox DSN itself must never look like a leak.)\n")
rc, seen, col = run_case(CANARY_ENV, {"ok.conf": f"dsn={SANDBOX_DSN}\ncomment=genesis is our org\n"})
check("'genesis' without a colon is not a leak (A3 keys on 'genesis:')", seen.get("A3"), "PASS")
check("the sandbox DSN in a scanned file is not a leak", rc, 0)

print("\nRED-PROOF — this oracle must FAIL if a verdict is neutered.")
print("(A gate never shown red is indistinguishable from a blind one — including this one.)\n")
src = SCRIPT.read_text()
mutant = src.replace(
    'if grep -Eq \'genesis|127\\.0\\.0\\.1|192\\.168\\.1\\.9\' "$ENVF"; then',
    'if false; then')
if mutant == src:
    check("mutation applied (A2 wired to a condition that can never fire)", "no-op", "applied")
else:
    tmpd = Path(tempfile.mkdtemp(prefix="g15-mutant-"))
    try:
        mp = tmpd / "prove_containment.sh"
        mp.write_text(mutant)
        real, SCRIPT = SCRIPT, mp
        globals()["SCRIPT"] = mp
        _, mseen, _mcol = run_case(CANARY_ENV + f"LEAK={REAL_DSN}\n", {})
        globals()["SCRIPT"] = real
        check("a neutered A2 is CAUGHT (it reports PASS on a real leak)", mseen.get("A2"), "PASS")
        check("...and the oracle's own assertion would have failed on it",
              mseen.get("A2") != "FAIL", True)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

print("\nSCOPE — stated, not implied: this proves the gate's DECISION LOGIC against synthetic")
print("inputs. It does not run docker, does not prove the cell is contained, and covers")
print("neither prove.sh nor prove_egress.sh. Containment is proven only in the real cell.")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
