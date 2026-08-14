#!/usr/bin/env python3
"""Class-2 oracle: prove.sh and prove_egress.sh DECISION LOGIC (docker stubbed).

READ THE SCOPE LINE FIRST, because this oracle's honesty depends on it and a green tick here
means less than the Class-1 one:

    IT PROVES: each verdict in the two host-side scripts takes the right branch for a given
               observation, that a breach trips exactly its own verdict, and that a check
               whose precondition failed reports UNVERIFIED rather than PASS.
    IT DOES NOT PROVE: that the cell is contained, that the proxy filters, that the network
               is internal, or that any of these scripts do anything correct when pointed at
               real docker. Every `docker` invocation here is a stub reading a fixture
               variable. Containment is proven ONLY by running the real scripts on the real
               cell; this proves the instruments can fail when they should.

A stubbed-docker oracle that printed "prove.sh verified" would be the aggregate lying about its
parts — the defect the org filed as "a SKIP is not a PASS". So the scope limit is printed in
this file's own output, not buried in a docstring nobody reads at check.sh time.

WHY IT EXISTS: seed's plan-15 requirement, and the same finding behind Class 1 — every verdict
in the prove_* family was asserted, never demonstrated. prove.sh's three verdicts all read
`docker inspect` output; prove_egress.sh's read curl exit codes and HTTP status through the cell.
None had ever been driven in both directions.

POLARITY AUDIT RESULT, recorded because it is the reusable half (seed asked for the pattern to
be repeated on anything M-next adds):
  - prove.sh P1/P2/P3 all fail toward FALSE ALARM. Empty/garbage `docker inspect` output makes
    each comparison false, which routes to bad(). Safe direction, verified below.
  - prove_egress.sh E2/E4/E5 read a FAILURE as evidence of safety (denied/blocked), so they
    fail toward FALSE GREEN. All three now carry an explicit precondition and report UNVERIFIED
    when it is absent.

Run by nucleus/check.sh. Exits 77 (SKIP) if either script is absent.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROVE = REPO / "harness/cell/prove.sh"
EGRESS = REPO / "harness/cell/prove_egress.sh"
EXIT_SKIP = 77

missing = [str(p) for p in (PROVE, EGRESS) if not p.exists()]
if missing:
    print(f"SKIP: absent ({', '.join(missing)}) — nothing verified here.")
    sys.exit(EXIT_SKIP)

fails: list[str] = []
VERDICT = re.compile(r"^\s*(PASS|FAIL|UNVERIFIED)\s+(.*?)\s*$")

NET = "astryx-cell-net"

# (key, PASS-marker, FAIL-marker, UNVERIFIED-marker or None). Markers must be MUTUALLY
# EXCLUSIVE — asserted per case below, after a substring collision between two markers put a
# phantom breach in the Class-1 vector. A discriminator that is not mutually exclusive is not a
# discriminator, and in a security oracle that is how a phantom PASS arrives looking sound.
PROVE_CHECKS = [
    ("P1", "no host bind-mount on the cell", "cell has a host mount", None),
    ("P2", "cell attached ONLY to", "cell on unexpected networks", None),
    ("P3", "is --internal (no gateway", "is NOT internal", None),
]
EGRESS_CHECKS = [
    ("E1", "api.anthropic.com reachable via proxy", "api.anthropic.com NOT reachable via proxy", None),
    ("E2", "example.com denied by proxy", "example.com REACHED via proxy", "example.com denial NOT VERIFIED"),
    ("E3", "cell executes (liveness precondition", "cell could NOT execute a trivial command", None),
    ("E4", "direct egress to api.anthropic.com denied", "direct egress to api.anthropic.com succeeded",
     "direct egress to api.anthropic.com NOT VERIFIED"),
    ("E5", "direct TCP to arbitrary internet denied", "direct TCP to 1.1.1.1:443 succeeded",
     "direct TCP to 1.1.1.1:443 NOT VERIFIED"),
]

# `docker` stub. prove.sh calls: rm -f / run -d / inspect --format / exec.
# prove_egress.sh calls: run --rm --network NET [-e https_proxy] IMG <cmd...>.
DOCKER_STUB = r'''#!/bin/sh
sub=$1; shift
case "$sub" in
  rm) exit 0 ;;
  network)
      # docker network inspect NET --format '{{.Internal}}'
      printf '%s' "${G15T_NET_INTERNAL-true}"; exit 0 ;;
  inspect)
      fmt=""
      for a in "$@"; do case "$prev" in --format) fmt=$a ;; esac; prev=$a; done
      case "$fmt" in
        *HostConfig.Binds*)      printf '%s' "${G15T_BINDS-null}" ;;
        *Mounts*)                printf '%s' "${G15T_MOUNTS-[]}" ;;
        *NetworkSettings*)       printf '%s' "${G15T_NETS-astryx-cell-net }" ;;
        *Internal*)              printf '%s' "${G15T_NET_INTERNAL-true}" ;;
      esac
      exit 0 ;;
  exec) exit "${G15T_CONTAIN_RC:-0}" ;;
  run)
      # Classify by the target that appears in the argv.
      t=""
      for a in "$@"; do
        case "$a" in
          -d) t=detach ;;
          g15-alive) t=alive ;;
          https://api.anthropic.com*) [ -z "$t" ] && t=api ;;
          https://example.com*) t=ex ;;
          *dev/tcp/1.1.1.1*) t=tcp ;;
        esac
        case "$a" in *https_proxy*) viaproxy=1 ;; esac
      done
      case "$t" in
        detach) exit 0 ;;
        alive)  [ "${G15T_CELL_ALIVE:-1}" = 1 ] && { printf 'g15-alive'; exit 0; }; exit 1 ;;
      esac
      if [ "${viaproxy:-0}" = 1 ]; then
        case "$t" in
          api) printf '%s' "${G15T_API_CODE:-200}"; exit 0 ;;
          ex)  printf '%s' "${G15T_EX_CODE:-000}";  exit 0 ;;
        esac
      fi
      case "$t" in
        api) exit "${G15T_DIRECT_API_RC:-1}" ;;
        tcp) exit "${G15T_DIRECT_TCP_RC:-1}" ;;
      esac
      exit 1 ;;
esac
exit 0
'''


def run_script(script, checks, **g15t):
    tmp = Path(tempfile.mkdtemp(prefix="g15-host-"))
    try:
        bindir = tmp / "bin"
        bindir.mkdir()
        d = bindir / "docker"
        d.write_text(DOCKER_STUB)
        d.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{bindir}:{env['PATH']}"
        env.update({k: str(v) for k, v in g15t.items()})
        r = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
        seen, collisions = {}, []
        for line in r.stdout.splitlines():
            m = VERDICT.match(line)
            if not m:
                continue
            state, text = m.group(1), m.group(2)
            hits = []
            for key, ok_s, bad_s, unv_s in checks:
                if state == "PASS" and ok_s in text:
                    hits.append((key, "PASS"))
                elif state == "FAIL" and bad_s in text:
                    hits.append((key, "FAIL"))
                elif state == "UNVERIFIED" and unv_s and unv_s in text:
                    hits.append((key, "UNVERIFIED"))
            if len(hits) > 1:
                collisions.append((text, [k for k, _ in hits]))
            for key, st in hits:
                seen[key] = st
        return r.returncode, seen, collisions
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        fails.append(label)


def expect(label, checks, rc, seen, want_states, collisions, want_rc):
    base = {k: "PASS" for k, _, _, _ in checks}
    base.update(want_states)
    check(f"{label}: verdict vector", seen, base)
    check(f"{label}: exit code", rc, want_rc)
    check(f"{label}: no line matched two checks", list(collisions), [])


print("=" * 78)
print("SCOPE: decision logic ONLY. docker is stubbed throughout. This proves these gates CAN")
print("fail when they should; it proves NOTHING about whether the cell is actually contained.")
print("=" * 78)

print("\nprove.sh — COVERAGE verdicts (all three read `docker inspect`):\n")
rc, seen, col = run_script(PROVE, PROVE_CHECKS)
check("all three verdicts observed", sorted(seen), ["P1", "P2", "P3"])
expect("clean", PROVE_CHECKS, rc, seen, {}, col, 0)

for label, kw, want in [
    ("P1 a host bind-mount exists", dict(G15T_BINDS='["/home/umair:/host"]'), {"P1": "FAIL"}),
    ("P1 a mount exists even with null binds", dict(G15T_MOUNTS='[{"Source":"/etc"}]'), {"P1": "FAIL"}),
    ("P2 cell also on another network", dict(G15T_NETS="astryx-cell-net pg_default "), {"P2": "FAIL"}),
    ("P3 network is not internal", dict(G15T_NET_INTERNAL="false"), {"P3": "FAIL"}),
]:
    rc, seen, col = run_script(PROVE, PROVE_CHECKS, **kw)
    expect(label, PROVE_CHECKS, rc, seen, want, col, 1)

print("\n  POLARITY — unreadable docker output must fail toward ALARM, not toward green:")
rc, seen, col = run_script(PROVE, PROVE_CHECKS, G15T_BINDS="", G15T_MOUNTS="",
                           G15T_NETS="", G15T_NET_INTERNAL="")
check("empty inspect output trips all three (safe direction)",
      seen, {"P1": "FAIL", "P2": "FAIL", "P3": "FAIL"})
check("...and the gate refuses", rc, 1)

print("\n  the containment gate's own exit propagates (prove.sh runs it via docker exec):")
rc, _, _ = run_script(PROVE, PROVE_CHECKS, G15T_CONTAIN_RC="1")
check("a failing prove_containment.sh fails prove.sh", rc, 1)

print("\nprove_egress.sh — the PINHOLE verdicts:\n")
rc, seen, col = run_script(EGRESS, EGRESS_CHECKS)
check("all five verdicts observed", sorted(seen), ["E1", "E2", "E3", "E4", "E5"])
expect("clean", EGRESS_CHECKS, rc, seen, {}, col, 0)

for label, kw, want in [
    ("E1 proxy cannot reach the model API", dict(G15T_API_CODE="000"),
     {"E1": "FAIL", "E2": "UNVERIFIED"}),
    ("E2 arbitrary host REACHED through the proxy (exfil)", dict(G15T_EX_CODE="200"),
     {"E2": "FAIL"}),
    ("E4 direct egress to the model API succeeds", dict(G15T_DIRECT_API_RC="0"),
     {"E4": "FAIL"}),
    ("E5 direct TCP to the internet succeeds", dict(G15T_DIRECT_TCP_RC="0"),
     {"E5": "FAIL"}),
]:
    rc, seen, col = run_script(EGRESS, EGRESS_CHECKS, **kw)
    expect(label, EGRESS_CHECKS, rc, seen, want, col, 1)

print("\n  THE GRANTED FIX — a cell that cannot execute must yield UNVERIFIED, not PASS:")
rc, seen, col = run_script(EGRESS, EGRESS_CHECKS, G15T_CELL_ALIVE="0")
expect("cell cannot execute", EGRESS_CHECKS, rc, seen,
       {"E3": "FAIL", "E4": "UNVERIFIED", "E5": "UNVERIFIED"}, col, 1)

print("\n  BREACH-FIRST — an observed escape is never downgraded to UNVERIFIED,")
print("  even when the precondition also failed (a proven breach outranks an unproven gate):")
rc, seen, col = run_script(EGRESS, EGRESS_CHECKS, G15T_CELL_ALIVE="0", G15T_DIRECT_API_RC="0")
check("E4 reports FAIL, not UNVERIFIED, when egress actually succeeded", seen.get("E4"), "FAIL")
check("E5 still UNVERIFIED (it did not observe a breach)", seen.get("E5"), "UNVERIFIED")
rc, seen, _ = run_script(EGRESS, EGRESS_CHECKS, G15T_API_CODE="000", G15T_EX_CODE="200")
check("E2 reports FAIL, not UNVERIFIED, when example.com was actually reached",
      seen.get("E2"), "FAIL")

print("\n  RED-PROOF — the granted verdict must be shown to change behaviour:")
src = EGRESS.read_text()
mutant = src.replace('elif [ "$cell_live" = 0 ]; then', 'elif false; then')
if mutant == src:
    check("mutation applied (UNVERIFIED branch disabled)", "no-op", "applied")
else:
    tmpd = Path(tempfile.mkdtemp(prefix="g15-emut-"))
    try:
        mp = tmpd / "prove_egress.sh"
        mp.write_text(mutant)
        _, mseen, _ = run_script(mp, EGRESS_CHECKS, G15T_CELL_ALIVE="0")
        check("without the fix, a dead cell prints PASS for closed egress (the old defect)",
              (mseen.get("E4"), mseen.get("E5")), ("PASS", "PASS"))
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

print("\n" + "=" * 78)
print("REMINDER: every verdict above was reached against a STUBBED docker. Nothing here")
print("licenses firing a probe. That authority comes only from the real scripts on the real")
print("cell, and this oracle exists so that when they speak, their failing branches work.")
print("=" * 78)
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
