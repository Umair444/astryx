#!/usr/bin/env python3
"""Oracle: plan-7862 "Hands" S1, the cell. Per-lease egress, no model-API pinhole, no secrets,
kill wipes, and a lease dies at its STEP cap or its WALL-TIME cap (seed #38260).

    venv/bin/python tests/test_hands_cell.py        (also run by nucleus/check.sh)

It drives the REAL executor (nucleus/hands.py) and the real images (astryx-hands-cell,
astryx-hands-proxy) against a throwaway, sqlguard-stamped lease table (HANDS_DSN, set explicitly).
Real public hosts stand in for a lease's allowed site: example.com is allowed, example.org isn't.

VERDICTS HAVE THREE STATES (the harness/cell law): a denial is only evidence once the SAME lease
has PROVEN it can reach its allowed host. If the allowed host doesn't load, every denial arm
reads UNVERIFIED (and the oracle fails), never PASS: "denied" from a cell that can't reach
anything proves nothing.

  H1 create REFUSES a model-API host (and any subdomain) and anything that isn't a plain hostname
  H2 the lease's browser LOADS its allowed host (liveness: the precondition for H3–H5)
  H3 a host off the lease's allow-list is denied
  H4 the model-API host is denied, even when asked for directly
  H5 the cell has NO route out except its proxy (direct HTTPS and raw TCP both fail)
  H6 leases are isolated: lease A can't use lease B's proxy, and B's allow-list doesn't widen A's
  H7 no secrets and no host: zero mounts, no docker socket, no host paths, read-only rootfs,
     cap-drop ALL, no secret-shaped env
  H8 KILL WIPES: a cookie planted in the profile is gone, the containers, network and generated
     filter are gone, and a fresh lease starts with an empty profile
  H9 STEP CAP: N steps run, the lease dies AT the Nth, and the next step is refused
  H9b the LAST step can't be taken twice: two concurrent steps on a 1-step lease, exactly one
      runs (the guard is one atomic UPDATE; without the cap condition in it both would)
  H9c a refused caller never ABORTS the last step in flight: once the last step is counted and
      running, a second call is refused, and the running step still completes (deterministic: it
      waits for the count before calling, unlike H9b's race)
  H10 WALL CAP with no calls: the detached reaper kills the lease at its deadline
  H11 WALL CAP on a call: a step after the deadline is refused BEFORE it runs (it's never
      counted), and the lease is dead. Not "it timed out": the exec timeout is a second guard, and
      a fast enough action would finish inside it, so the refusal must come first (K7 survived on
      the timeout alone)
  H13 NAMESPACES: a lease in ANOTHER namespace (the org's real executor, say) is never touched by
      this namespace's sweep, even though its id isn't live in this table
  H12 SWEEP kills an expired lease that has no reaper and no caller; a step, status or reap on a
      lease that doesn't exist is refused or empty

GRADE (stated in every run): PREVENTION against the EXTERNAL adversary (the page steering the
driver, outside parties), to the kernel boundary. Residents are trusted by owner ruling (#38554)
and aren't a threat this design defends against.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = os.environ.get("HANDS_SRC")               # mutation_probe's seam: a mutant hands.py
fails, unverified = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def unver(name, why):
    print(f"  UNVERIFIED  {name}\n        {why}")
    unverified.append(name)


def skip(why):
    print(f"SKIP: {why}. Nothing was verified here.")
    sys.exit(77)


def docker(*a, timeout=60):
    return subprocess.run(["docker", *a], capture_output=True, text=True, timeout=timeout)


if shutil.which("docker") is None or docker("info").returncode != 0:
    skip("docker is unavailable")
for img in ("astryx-hands-cell", "astryx-hands-proxy"):
    if docker("image", "inspect", img).returncode != 0:
        skip(f"image {img} isn't built (harness/hands/build.sh)")

sys.path.insert(0, str(REPO))
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    skip(f"the fixture database couldn't be built ({type(e).__name__})")
state = Path(tempfile.mkdtemp(prefix="hands-state-"))
os.environ["HANDS_DSN"] = fx["dsn"]                 # the axis is set EXPLICITLY, never inherited
os.environ["HANDS_STATE_DIR"] = str(state)
# Our OWN namespace: lease ids repeat across DBs, so without it this run's names would collide
# with the org's real leases (and other runs), and our sweep() would kill theirs as orphans.
os.environ["HANDS_NS"] = f"t{os.getpid()}"
if SUBJECT:                                          # the subject under test, by path
    import importlib.util
    from importlib.machinery import SourceFileLoader
    _spec = importlib.util.spec_from_file_location("hands_under_test", SUBJECT,
                                                   loader=SourceFileLoader("hands_under_test", SUBJECT))
    hands = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(hands)
else:
    from nucleus import hands  # noqa: E402  (after the env is set: hands reads it per call)

made = []


def lease(allow, steps=20, wall=600, reaper=True):
    lid = hands.create("forge-oracle", allow, steps, wall, reaper=reaper)
    made.append(lid)
    return lid


def go(lid, url):
    try:
        return hands.step(lid, {"verb": "goto", "url": url})
    except hands.Refused as e:
        return {"ok": False, "refused": str(e)}


def reached(r):
    return bool(r.get("ok")) and isinstance(r.get("status"), int) and r["status"] < 500


def cell_sh(lid, *cmd, timeout=30):
    return docker("exec", hands.names(lid)["cell"], *cmd, timeout=timeout)


def gone(lid):
    n = hands.names(lid)
    left = [x for x in (n["cell"], n["proxy"]) if docker("inspect", x).returncode == 0]
    if docker("network", "inspect", n["net"]).returncode == 0:
        left.append(n["net"])
    return left


print("GRADE: prevention vs the EXTERNAL adversary (page/app content, outside parties), to the kernel")
print("       boundary. Residents are trusted by owner ruling (#38554); not a threat model here.")
try:
    # ── H1 ────────────────────────────────────────────────────────────────────────────────────
    for bad, why in (("api.anthropic.com", "model API"), ("x.api.openai.com", "model-API subdomain"),
                     ("https://example.com", "scheme"), ("example.com:443", "port"),
                     ("*.example.com", "wildcard"), ("localhost", "not a public hostname")):
        try:
            hands.create("forge-oracle", [bad], 3, 60)
            ok = False
        except hands.Refused:
            ok = True
        check(f"H1 create refuses {bad!r} ({why})", ok)
    check("H1 the generated filter is anchored and escaped, one line per host",
          hands.filter_text(["example.com"]) == "^example\\.com$\n", repr(hands.filter_text(["example.com"])))

    # ── H2–H5: one lease allowing example.com ─────────────────────────────────────────────────
    A = lease(["example.com"])
    r = go(A, "https://example.com/")
    live = reached(r)
    check("H2 the lease's browser LOADS its allowed host (example.com)", live, json.dumps(r)[:200])
    for name, url in (("H3 a host off the allow-list is denied (example.org)", "https://example.org/"),
                      ("H4 the model-API host is denied (api.anthropic.com)", "https://api.anthropic.com/")):
        r = go(A, url)
        if reached(r):
            check(name, False, f"REACHED: {json.dumps(r)[:200]}")     # breach-first: never downgraded
        elif not live:
            unver(name, "the allowed host didn't load either, so a failure here proves nothing")
        else:
            check(name, True)
    direct = cell_sh(A, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--noproxy", "*",
                     "--max-time", "8", "https://example.com/")
    raw = cell_sh(A, "curl", "-s", "-o", "/dev/null", "--noproxy", "*", "--max-time", "8",
                  "--connect-timeout", "6", "telnet://1.1.1.1:443")
    alive = cell_sh(A, "echo", "hands-alive").stdout.strip() == "hands-alive"
    for name, res, breached in (("H5 no direct HTTPS out of the cell (proxy bypassed)", direct,
                                 direct.stdout.strip() not in ("", "000")),
                                ("H5 no raw TCP out of the cell (1.1.1.1:443)", raw, raw.returncode == 0)):
        if breached:
            check(name, False, f"REACHED: rc={res.returncode} out={res.stdout[:80]!r}")
        elif not alive:
            unver(name, "the cell can't execute, so a failed connect proves nothing")
        else:
            check(name, True)

    # ── H6: a second, concurrent lease ────────────────────────────────────────────────────────
    B = lease(["example.org"])
    rb = go(B, "https://example.org/")
    check("H6 lease B loads ITS host (example.org)", reached(rb), json.dumps(rb)[:200])
    ra = go(A, "https://example.org/")
    check("H6 B's allow-list doesn't widen A's (A still can't reach example.org)", not reached(ra),
          json.dumps(ra)[:200])
    cross = cell_sh(A, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "8",
                    "-x", f"http://{hands.names(B)['proxy']}:8888", "https://example.org/")
    check("H6 A's cell can't use B's proxy (no shared network)",
          cross.stdout.strip() in ("", "000"), f"code={cross.stdout.strip()!r}")

    # ── H7 ────────────────────────────────────────────────────────────────────────────────────
    info = json.loads(docker("inspect", hands.names(A)["cell"]).stdout)[0]
    hc = info["HostConfig"]
    check("H7 the cell has ZERO mounts (no bind, no volume; the profile is tmpfs)",
          info.get("Mounts") == [] and not hc.get("Binds"), str(info.get("Mounts"))[:200])
    check("H7 read-only rootfs, cap-drop ALL, no-new-privileges",
          hc.get("ReadonlyRootfs") is True and "ALL" in (hc.get("CapDrop") or [])
          and any("no-new-privileges" in s for s in (hc.get("SecurityOpt") or [])), "")
    env_names = [e.split("=", 1)[0] for e in info["Config"]["Env"]]
    leaky = [n for n in env_names if re.search(r"DSN|TOKEN|KEY|SECRET|PASS|ANTHROPIC|ASTRYX", n)]
    check("H7 no secret-shaped env in the cell", not leaky, str(leaky))
    probe = cell_sh(A, "sh", "-c", "ls /home/umair /var/run/docker.sock /run/docker.sock 2>&1; "
                    "test -e /home/umair || test -S /var/run/docker.sock || test -S /run/docker.sock "
                    "&& echo LEAK || echo none")
    check("H7 no host paths and no docker socket inside", probe.stdout.strip().endswith("none"),
          probe.stdout[-200:])

    # ── H8: kill wipes ────────────────────────────────────────────────────────────────────────
    hands.step(A, {"verb": "cookie_set", "name": "hands_oracle", "value": "x",
                   "url": "https://example.com/"})
    had = hands.step(A, {"verb": "cookies"})
    check("H8 precondition: the planted cookie is in A's profile",
          any(c["name"] == "hands_oracle" for c in had.get("cookies", [])), json.dumps(had)[:200])
    check("H8 kill returns true for a live lease", hands.kill(A) is True)
    check("H8 after kill, A's cell, proxy and network are all gone", gone(A) == [], str(gone(A)))
    check("H8 ...and its generated filter dir is gone", not hands.names(A)["dir"].exists())
    st = hands.status(A)
    check("H8 the row says dead / killed", st["state"] == "dead" and st["end_reason"] == "killed", str(st))
    C = lease(["example.com"])
    fresh = hands.step(C, {"verb": "cookies"})
    check("H8 a fresh lease starts with an EMPTY profile (nothing survived the kill)",
          fresh.get("ok") and fresh.get("cookies") == [], json.dumps(fresh)[:200])
    hands.kill(C)
    hands.kill(B)

    # ── H9: step cap ──────────────────────────────────────────────────────────────────────────
    D = lease(["example.com"], steps=2)
    s1 = hands.step(D, {"verb": "cookies"})
    s2 = hands.step(D, {"verb": "cookies"})
    check("H9 steps 1 and 2 run", s1.get("ok") and s2.get("ok"), f"{s1} {s2}")
    stD = hands.status(D)
    check("H9 the lease dies AT its step cap (dead / step_cap after step 2)",
          stD["state"] == "dead" and stD["end_reason"] == "step_cap", str(stD))
    check("H9 ...and nothing of it is left running", gone(D) == [], str(gone(D)))
    try:
        hands.step(D, {"verb": "cookies"})
        refused = False
    except hands.Refused:
        refused = True
    check("H9 step 3 is refused", refused)

    # ── H9b: two concurrent callers race for the last step ───────────────────────────────────
    import threading
    R = lease(["example.com"], steps=1)
    results = []

    def racer():
        try:
            results.append(("ran", hands.step(R, {"verb": "cookies"})))
        except hands.Refused as e:
            results.append(("refused", str(e)))
    ts = [threading.Thread(target=racer) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(120)
    ran = [r for r in results if r[0] == "ran"]
    stR = hands.status(R)
    check("H9b two concurrent steps on a 1-step lease: exactly ONE runs",
          len(ran) == 1 and stR["steps_used"] == 1, f"{[r[0] for r in results]} steps_used={stR['steps_used']}")

    # ── H9c: a refusal during the in-flight last step must not abort it ───────────────────────
    Q = lease(["example.com"], steps=1)
    first = []
    t = threading.Thread(target=lambda: first.append(hands.step(Q, {"verb": "goto",
                                                                     "url": "https://example.com/"})))
    t.start()
    end = time.monotonic() + 30
    while time.monotonic() < end and hands.status(Q)["steps_used"] < 1:
        time.sleep(0.05)
    try:
        hands.step(Q, {"verb": "cookies"})
        second = "ran"
    except hands.Refused:
        second = "refused"
    t.join(120)
    check("H9c a second call during the in-flight last step is refused", second == "refused", second)
    check("H9c ...and the in-flight last step still COMPLETES (it wasn't aborted)",
          bool(first) and reached(first[0]), json.dumps(first)[:200])

    # ── H10: wall cap, no calls ───────────────────────────────────────────────────────────────
    E = lease(["example.com"], wall=6)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline and hands.status(E)["state"] == "live":
        time.sleep(1)
    stE = hands.status(E)
    check("H10 with no calls, the reaper kills the lease at its wall cap (dead / wall_cap)",
          stE["state"] == "dead" and stE["end_reason"] == "wall_cap", str(stE))
    check("H10 ...and nothing of it is left running", gone(E) == [], str(gone(E)))

    # ── H11: wall cap on a call ───────────────────────────────────────────────────────────────
    # NO reaper on F: it would kill F at 3s and answer for the step's own deadline check, so a
    # missing check would still pass. Only the step path may satisfy H11.
    F = lease(["example.com"], wall=3, reaper=False)
    time.sleep(4)
    try:
        hands.step(F, {"verb": "cookies"})
        refused = False
    except hands.Refused:
        refused = True
    stF = hands.status(F)
    check("H11 a step after the deadline is refused", refused)
    check("H11 ...and the lease is dead / wall_cap", stF["state"] == "dead" and stF["end_reason"] == "wall_cap",
          str(stF))
    check("H11 the refused step never RAN: steps_used is still 0", stF["steps_used"] == 0,
          f"steps_used={stF['steps_used']}")

    # ── H12: sweep, and the no-such-lease edges ───────────────────────────────────────────────
    G = lease(["example.com"], wall=2, reaper=False)
    time.sleep(3)
    swept = hands.sweep()
    stG = hands.status(G)
    check("H12 sweep kills an expired lease with no reaper and no caller",
          f"expired {G}" in swept and stG["state"] == "dead" and stG["end_reason"] == "wall_cap",
          f"{swept} {stG}")
    check("H12 ...and nothing of it is left running", gone(G) == [], str(gone(G)))
    try:
        hands.step(10**9, {"verb": "cookies"})
        nolease = False
    except hands.Refused:
        nolease = True
    check("H12 a step on a lease that doesn't exist is refused", nolease)
    check("H12 status of a lease that doesn't exist says so", hands.status(10**9) == {"lease": 10**9, "exists": False})
    # H13: plant a container labelled as ANOTHER namespace's lease 1 (a live lease of the real
    # executor, as far as this table knows nothing about it). Our sweep must leave it alone.
    foreign = f"hands-foreign{os.getpid()}-1-cell"
    docker("run", "-d", "--name", foreign, "--label", f"astryx.hands.ns=foreign{os.getpid()}",
           "--label", "astryx.hands.lease=1", "--network", "none", "--entrypoint", "sleep",
           "astryx-hands-cell", "300")
    try:
        hands.sweep()
        check("H13 another namespace's lease survives our sweep", docker("inspect", foreign).returncode == 0)
    finally:
        docker("rm", "-f", foreign)
    hands.reap(10**9)                                   # returns at once: nothing to reap
    check("H12 reap of a lease that doesn't exist returns without acting", True)
finally:
    for lid in made:
        try:
            hands.kill(lid)
        except Exception:  # noqa: BLE001
            pass
    # Teardown that DOESN'T trust the subject: under a mutant, hands.kill() may itself be the bug
    # (it leaked 20 containers across one battery). Everything carrying OUR namespace label goes,
    # straight through docker. The namespace scopes it, so nothing of the org's is touched.
    _ns = os.environ["HANDS_NS"]
    # Volumes too, after the containers that hold them: a mutant (K3) persists the profile in one.
    for kind, rm in ((["ps", "-aq"], ["rm", "-f"]), (["network", "ls", "-q"], ["network", "rm"]),
                     (["volume", "ls", "-q"], ["volume", "rm", "-f"])):
        ids = docker(*kind, "--filter", f"label=astryx.hands.ns={_ns}").stdout.split()
        if ids:
            docker(*rm, *ids)
    try:
        hands.sweep()
    except Exception:  # noqa: BLE001
        pass
    _fx.__exit__(None, None, None)
    shutil.rmtree(state, ignore_errors=True)

if fails or unverified:
    print(f"\nFAIL: {len(fails)} broken, {len(unverified)} UNVERIFIED (an unverified containment "
          f"check is never a pass)")
    sys.exit(1)
print("\nPASS: per-lease egress, no model-API pinhole, no secrets, kill wipes, step and wall caps hold")
