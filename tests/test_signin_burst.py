#!/usr/bin/env python3
"""plan-11859 U1U2-F (seed #62578): a burst of sign-ins costs the host at most its bound. The REAL front (uvicorn
front:app) on a loopback socket it inherits, with the real cogauth, its password check WRAPPED in the front's own
process (a preload) to count how many run at once and in all, and to hold each for 0.3 s so a burst overlaps. A
fixture cog store (the real host CLI makes the cog, its key and one account). No backend runs; nothing binds 8090.

  B1 50 concurrent bad sign-ins, each its own client and email: never more than 2 checks at once; the ones refused
     busy (503, "busy") paid NO check, so checks == the 401s; 401 + 503 == 50, and the cap did engage (a 503 seen)
  B2 one ACCOUNT, 20 concurrent bad tries from 20 clients: at most 5 checks for it (the account's limit, counted from
     each attempt's START), and the rest 429 or busy
  B3 once the burst is over, a good sign-in from a fresh client is 200 (the positive control: the bound is no outage)
Seams: OBS_FRONT_SRC (a mutant front.py), COGAUTH_SRC (a mutant cogauth.py). Exit 0 · 1 · 77 (no database).
"""
import atexit
import concurrent.futures
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_signin_burst', REPO, deps=('psycopg', 'fastapi', 'httpx', 'uvicorn'), env=False)
from astryx.security.sqlguard import propagate  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

PY = sys.executable
fails = []
ORIGIN = "http://fx-burst.invalid"
PW = "fx-dummy-pass-burst-0001"
# the front's own process: the real cogauth (or a mutant), its check_password wrapped to count and hold, then uvicorn
PRELOAD = r"""
import os, sys, threading, time, types
src, log = sys.argv[1], sys.argv[2]
del sys.argv[1:3]
sys.path.insert(0, src)
mut = os.environ.get("COGAUTH_SRC")
if mut:
    import astryx
    m = types.ModuleType("astryx.cogauth"); m.__file__ = src + "/astryx/cogauth.py"; m.__package__ = "astryx"
    sys.modules["astryx.cogauth"] = m; astryx.cogauth = m
    exec(compile(open(mut).read(), m.__file__, "exec"), m.__dict__)
from astryx import cogauth
real, lock, state = cogauth.check_password, threading.Lock(), {"now": 0, "max": 0, "n": 0}
def counted(pw, phc):
    with lock:
        state["now"] += 1; state["n"] += 1; state["max"] = max(state["max"], state["now"])
        open(log, "w").write("%d %d\n" % (state["max"], state["n"]))
    try:
        time.sleep(0.3)
        return real(pw, phc)
    finally:
        with lock:
            state["now"] -= 1
cogauth.check_password = counted
import uvicorn
sys.exit(uvicorn.main())
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {str(detail).replace(PW, '<the password>')}")


def post(port, email, pw, client):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/auth/login", method="POST",
                                 data=json.dumps({"email": email, "password": pw}).encode(),
                                 headers={"content-type": "application/json", "origin": ORIGIN,
                                          "x-forwarded-for": client})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def counts(log: Path):
    try:
        mx, n = log.read_text().split()
        return int(mx), int(n)
    except (OSError, ValueError):
        return 0, 0


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-burst-")).resolve()
    atexit.register(shutil.rmtree, t, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    procs = []
    atexit.register(lambda: [p.kill() for p in procs if p.poll() is None])
    cog_sql = (REPO / "src" / "astryx" / "sql" / "cog_schema.sql").read_text()
    with fixture_db(extra=(cog_sql,)) as store:
        run(t, store, procs)
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a burst of sign-ins costs at most its bound")
    return 1 if fails else 0


def run(t, store, procs):
    pid = os.getpid()
    reg = {"orgs": {}}
    for k in ("a", "b"):
        h = t / f"fxbu-{k}-{pid}"
        h.mkdir()
        (h / ".env").write_text(f"ASTRYX_ORG=fed-fxbu-{k}\n")
        reg["orgs"][f"fxbu-{k}-{pid}"] = {"home": str(h), "db": f"fxbudb_{k}_{pid}"}
    home = t / "cog"
    home.mkdir()
    (home / ".env").write_text(f"ASTRYX_DSN={store['url']}\nASTRYX_COG_ORIGINS={ORIGIN}\n")
    regf = t / "cog.json"
    regf.write_text(json.dumps(reg))
    base = {k: os.environ[k] for k in ("PATH", "HOME", "ASTRYX_FIXTURE_ADMIN_DSN") if k in os.environ}
    cogbase = {**base, "ASTRYX_SQLGUARD_ROOT": str(REPO)}     # a cog-scoped child: its stamps read through the tree
    cli = [PY, str(REPO / "src/astryx/cogauth.py")]

    def cog(*args, stdin=None):
        return subprocess.run([*cli, *args], input=stdin, capture_output=True, text=True, timeout=120,
                              env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(regf)}))
    r = cog("init", "--home", str(home), "--id", f"fxcog-{pid:08d}")
    check("cogauth init (rc 0)", r.returncode == 0, r.stderr[-300:])
    reg["cog"] = {"id": f"fxcog-{pid:08d}", "home": str(home)}
    regf.write_text(json.dumps(reg))
    r = cog("user", "add", "burst@fx-burst.invalid", stdin=PW + "\n")
    check("cogauth user add (rc 0)", r.returncode == 0, r.stderr[-300:])

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(256)
    port = s.getsockname()[1]
    fdir = REPO / "observatory"
    if os.environ.get("OBS_FRONT_SRC"):
        fdir = t / "observatory"
        fdir.mkdir()
        (fdir / "front.py").write_text(Path(os.environ["OBS_FRONT_SRC"]).read_text().replace(
            'ROOT = Path(__file__).resolve().parent', f'ROOT = Path({str(REPO / "observatory")!r})'))
    log = t / "checks.log"
    front = subprocess.Popen([PY, "-c", PRELOAD, str(REPO / "src"), str(log), "front:app", "--fd", str(s.fileno())],
                             pass_fds=(s.fileno(),), cwd=fdir,
                             env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(regf)}),
                             stdout=subprocess.DEVNULL, stderr=(t / "front.err").open("w"))
    procs.append(front)
    s.close()
    end = time.time() + 60
    up = False
    while time.time() < end and front.poll() is None and not up:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cog", timeout=2)
            up = True
        except urllib.error.HTTPError:
            up = True
        except OSError:
            time.sleep(0.3)
    check("the front starts", up, (t / "front.err").read_text()[-300:] if not up else "")
    if not up:
        return
    post(port, "warm@fx-burst.invalid", "fx-dummy-wrong-0000", "198.51.100.250")    # sign-in state loaded once
    time.sleep(0.5)
    base_max, base_n = counts(log)

    print("\nB1 50 CONCURRENT BAD SIGN-INS")
    with concurrent.futures.ThreadPoolExecutor(50) as ex:
        res = list(ex.map(lambda i: post(port, f"nobody{i}@fx-burst.invalid", "fx-dummy-wrong-0001",
                                         f"203.0.113.{i + 1}"), range(50)))
    mx, n = counts(log)
    st = [r[0] for r in res]
    n401, n503 = st.count(401), st.count(503)
    check("never more than 2 checks at once", mx <= 2 and n > base_n, f"max {mx}, checks {n - base_n}")
    check("401 + 503 == 50, the cap engaged (a 503), every 503 says busy",
          n401 + n503 == 50 and n503 > 0 and all("busy" in r[1] for r in res if r[0] == 503), f"{n401} 401, {n503} 503")
    check("a busy refusal paid no check: checks run == the 401s", n - base_n == n401, f"checks {n - base_n}, 401s {n401}")

    print("\nB2 ONE ACCOUNT, 20 CONCURRENT BAD TRIES")
    before = counts(log)[1]
    with concurrent.futures.ThreadPoolExecutor(20) as ex:
        res = list(ex.map(lambda i: post(port, "burst@fx-burst.invalid", "fx-dummy-wrong-0002",
                                         f"192.0.2.{i + 1}"), range(20)))
    ran = counts(log)[1] - before
    st = [r[0] for r in res]
    check("at most 5 checks for the account (its limit counts from each attempt's start)", ran <= 5,
          f"{ran} checks; statuses {sorted(st)}")
    check("...and the rest are 429 or busy, never a check", st.count(401) == ran
          and all(x in (401, 429, 503) for x in st), str(sorted(st)))

    print("\nB3 AFTER THE BURST")
    time.sleep(1.0)
    st_ok, body = post(port, "burst@fx-burst.invalid", PW, "198.51.100.200")
    check("the account's own good sign-in, from a fresh client: 429 while its window holds (5 failures), never 503",
          st_ok == 429, f"{st_ok} {body[:80]}")
    r = cog("user", "add", "fresh@fx-burst.invalid", stdin=PW + "\n")
    st_ok, body = post(port, "fresh@fx-burst.invalid", PW, "198.51.100.201")
    check("a fresh account's good sign-in: 200 (the bound is no outage)", r.returncode == 0 and st_ok == 200,
          f"{st_ok} {body[:80]}")


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    try:
        sys.exit(main())
    except FixtureUnavailable as e:
        unavailable("test_signin_burst", REPO, e)
