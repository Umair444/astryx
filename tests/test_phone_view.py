#!/usr/bin/env python3
"""Oracle: plan-8675 S2, the phone in its own Hands desktop, watched, joined and STOPPED from the observatory.
No phone needed (tests/test_android_device.py drives a real one). Binding set: a4 #48201 (B1–B4, with a2 #48210's
mechanism for B1), a3 #48213 (C1, C2), a1 #48216 (B5).

  STOP  through the observatory's REAL routes, as hands.tsx sends them: an owner POST /api/hands/<phone desktop>/stop
        → the phone facade refuses look and act; shutdown still passes the stop; owner resume → it acts again.
        A NON-owner POST (no key, or a wrong key) → 403, and the phone still answers. Nothing here writes a flag itself.
  B3    a viewed boot says "watch and join it in the observatory"; a headless one says "no live view" and names the
        CLI and shutdown as the owner's stops
  B1    the phone's desktop is unreachable by Hands' agent tools, by ALLOWLIST: pool() lists only desk-*, acquire()
        never yields the phone desktop even when every pool desk is taken, and _ready() refuses its name.
        Control: "background" resolves to a desk-*.
  B2    ONE spelling: phone_desktop()/avd_of_desktop() round-trip, and no other CODE (tests excluded: a fixture
        string builds no desktop) constructs a "phone-…" name; the scan's pattern is proven on samples.
  C2    the resume sweep: a resume within 60 s of an agent's act on the laptop is flagged once; one far from any act
        is quiet; a resume whose +60 s window hasn't passed waits; a STOP near an act isn't a resume. The writers:
        hands_desktop.stop/resume append to the desktop's owner log, and an act on the laptop to its act log.
  B4    absent by omission: backup.sh --list-state carries nothing under ~/.android, and no snapper config's
        subvolume holds ANDROID_AVD_HOME (control: the root config does hold "/usr").
  B5    the VNC bearer key never reaches the log: uvicorn's own websocket-accept line, through the observatory's
        installed filter, carries key=<redacted> (in-process); and LIVE, one owner VNC connect to the running
        observatory adds 0 journal lines holding the key, while its redacted line WAS written (control).
Exit 77 if the venv's deps (the MCP SDK, FastAPI) aren't importable; a live arm whose precondition is absent is
UNVERIFIED and makes the run 77 (never a pass).
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
try:
    from mcp import ClientSession  # noqa: F401
    from fastapi.testclient import TestClient
except ImportError as e:
    print(f"SKIP: the venv's deps aren't importable here ({e}). Nothing was verified here.")
    sys.exit(77)

TMP = Path(tempfile.mkdtemp(prefix="phone-view-oracle-"))
os.environ["ASTRYX_HANDS_STATE"] = str(TMP / "state")          # the axes, set explicitly, before any import
os.environ["ASTRYX_HANDS_HOME"] = str(TMP / "home")
os.environ["ASTRYX_AGENT"] = "view-oracle"
TEST_KEY = "test-owner-key-phone-view"
os.environ["OBS_KEY"] = TEST_KEY

import importlib.util  # noqa: E402
import nucleus  # noqa: E402


def _load(modname, default, env):
    spec = importlib.util.spec_from_file_location(modname, os.environ.get(env) or str(REPO / default))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    if modname.startswith("nucleus."):
        setattr(nucleus, modname.split(".", 1)[1], mod)
    return mod


hd = _load("nucleus.hands_desktop", "nucleus/hands_desktop.py", "HANDS_DESKTOP_SRC")
droid = _load("nucleus.android", "nucleus/android.py", "ANDROID_SRC")
srv = _load("phone_server", "mcp/phone/server.py", "PHONE_SERVER_SRC")
sys.path.insert(0, str(REPO / "observatory" / "api"))
obs = _load("main", "observatory/api/main.py", "OBS_MAIN_SRC")

fails, unverified = [], []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def unver(label, why):
    print(f"  UNVERIFIED {label}: {why}")
    unverified.append(label)


AVD = "oracle-phone"
DESK = droid.phone_desktop(AVD)

# ── STOP, through the REAL routes ──────────────────────────────────────────────────────────────────────────────
reached = []


def _sentinel_drive(device, agent):
    reached.append(device)
    raise droid.AndroidError("reached-drive")


droid.drive = _sentinel_drive
srv.droid.drive = _sentinel_drive
cl = TestClient(obs.app)                       # no `with`: no startup (no database pool), the hands routes need none
OWNER = {"x-obs-key": TEST_KEY}
r = cl.post(f"/api/hands/{DESK}/stop", headers=OWNER)
want("STOP: the owner's POST to the phone desktop's stop route answers 200 (as hands.tsx sends it)",
     r.status_code == 200, f"{r.status_code} {r.text[:120]}")
reached.clear()
out = asyncio.run(srv.act("tap", device=AVD, x=1, y=1))
want("STOP: ...then the phone facade REFUSES an act (STOPPED), before taking the phone",
     str(out[0]).startswith("STOPPED") and not reached, f"{out[:1]} {reached}")
out = asyncio.run(srv.look(AVD, text=True))
want("STOP: ...and a look", str(out[0]).startswith("STOPPED") and not reached, f"{out[:1]} {reached}")
out = asyncio.run(srv.act("shutdown", device=AVD))
want("STOP: ...while shutdown still passes the stop (it only lowers capability)", "reached-drive" in str(out),
     str(out[:1]))
booted = []
_real_boot = srv.droid.boot
srv.droid.boot = lambda d, a: booted.append(d) or "emulator-0"
out = asyncio.run(srv.act("boot", device=AVD))
srv.droid.boot = _real_boot
want("STOP: ...and a stopped phone can't be BOOTED", str(out[0]).startswith("STOPPED") and not booted, f"{out[:1]}")
r = cl.post(f"/api/hands/{DESK}/resume", headers=OWNER)
reached.clear()
out = asyncio.run(srv.act("tap", device=AVD, x=1, y=1))
want("STOP: the owner's RESUME through the route lets the phone act again", r.status_code == 200
     and "reached-drive" in str(out) and reached == [AVD], f"{r.status_code} {out[:1]} {reached}")
for label, hdrs in (("no key", {}), ("a wrong key", {"x-obs-key": "not-the-key"})):
    r = cl.post(f"/api/hands/{DESK}/stop", headers=hdrs)
    reached.clear()
    out = asyncio.run(srv.act("tap", device=AVD, x=1, y=1))
    want(f"STOP: a NON-owner POST ({label}) is refused 403 and the phone still answers (control)",
         r.status_code == 403 and "reached-drive" in str(out), f"{r.status_code} {out[:1]}")

# ── B3: the boot answer says which kind of stop the owner has (a4 #48590: pin the headless wording too) ─────────
_saved = (srv.droid.boot, srv.droid.viewed, srv.droid.harden)
srv.droid.drive = lambda d, a: None
srv.droid.boot = lambda d, a: "emulator-9"
srv.droid.harden = lambda d, s: []
for viewed, must in ((True, "watch and join it in the observatory"), (False, "no live view")):
    srv.droid.viewed = lambda d, v=viewed: v
    out = asyncio.run(srv.act("boot", device=AVD))
    want(f"B3: a {'viewed' if viewed else 'HEADLESS'} boot says so ({must!r})", must in str(out[0]), str(out[:1]))
    if not viewed:
        want("B3: ...and names the stops that exist there (the CLI and shutdown)", "CLI" in str(out[0])
             and "shutdown" in str(out[0]), str(out[:1]))
srv.droid.boot, srv.droid.viewed, srv.droid.harden = _saved
srv.droid.drive = _sentinel_drive

# ── B1: the phone desktop is unreachable by Hands' agent tools (the allowlist, pinned) ─────────────────────────────
for d in (DESK, "desk-1"):
    hd.state_dir(d).mkdir(parents=True, exist_ok=True)
hd._hold("desk-1", "someone-else")             # every pool desk is taken: a widened pool would hand out the phone's
_real = (hd.alive, hd.up, hd._seed_profile)
hd.alive = lambda a: True
hd.up = lambda a: {"agent": a}
hd._seed_profile = lambda a: None
want("B1: pool() lists only desk-*, never the phone's desktop", DESK not in hd.pool() and "desk-1" in hd.pool(),
     str(hd.pool()))
got = hd.acquire("view-oracle")
want("B1: with every pool desk taken, acquire() makes a new desk-*, never the phone's desktop",
     got.startswith(hd.POOL_PREFIX) and got != DESK, got)
hsrv = _load("hands_server", "mcp/hands/server.py", "HANDS_SERVER_SRC")
try:
    hsrv._ready(DESK)
    want("B1: Hands' _ready() refuses the phone desktop's name as a screen", False, "it resolved")
except hd.HandsError:
    want("B1: Hands' _ready() refuses the phone desktop's name as a screen", True)
want("B1: control: 'background' resolves to a pool desk", str(hsrv._ready("background")).startswith(hd.POOL_PREFIX))
hd.alive, hd.up, hd._seed_profile = _real

# ── B2: one spelling ───────────────────────────────────────────────────────────────────────────────────────────
want("B2: phone_desktop and avd_of_desktop round-trip, from one template",
     droid.avd_of_desktop(droid.phone_desktop("x-1")) == "x-1" and droid.avd_of_desktop("desk-1") is None
     and droid.avd_of_desktop("laptop") is None)
spell = re.compile(r"""f["']phone-\{|["']phone-["']\s*\+|["']phone-\{\}["']""")
others = []
for p in subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True).stdout.split():
    if p == "nucleus/android.py" or p.startswith("tests/"):   # CODE only: a test's fixture strings build no desktop
        continue
    try:
        if spell.search((REPO / p).read_text()):
            others.append(p)
    except OSError:
        pass
want("B2 control: the scan catches a construction (f-string, concatenation, format template)",
     all(spell.search(x) for x in ('d = f"phone-{avd}"', "d = 'phone-' + avd", 'T = "phone-{}"')))
want("B2: no code outside nucleus/android.py builds a phone desktop name", not others, str(others))

# ── C2: the resume sweep ───────────────────────────────────────────────────────────────────────────────────────
sweep_mod = _load("phone_resume_sweep", "nucleus/shipped_triggers/phone_resume_sweep.py", "SWEEP_SRC")
log = hd.state_dir(DESK) / "owner_log"
acts = hd.state_dir(hd.LAPTOP) / "acts.log"
acts.parent.mkdir(parents=True, exist_ok=True)
T = 1_900_000_000.0
log.write_text(f"{T - 500:.3f} stop\n{T:.3f} resume\n{T + 1000:.3f} resume\n{T + 1950:.3f} resume\n")
acts.write_text(f"{T - 20:.3f} click agent-x\n{T - 520:.3f} key agent-y\n{T + 1960:.3f} click agent-z\n")
st = {}
flags = sweep_mod.sweep(st, now=T + 1100)
want("C2: a resume 20 s after an agent's laptop act is FLAGGED, naming that agent",
     [f["resume_ts"] for f in flags] == [T] and flags[0]["agents"] == ["agent-x"], json.dumps(flags))
want("C2: ...a resume far from any act is quiet, and a STOP near an act isn't a resume", len(flags) == 1)
want("C2: a resume whose +60 s window hasn't passed is not judged yet",
     all(f["resume_ts"] != T + 1950 for f in flags) and st["through"] == T + 1100 - 60)
flags2 = sweep_mod.sweep(st, now=T + 2100)
want("C2: ...and is judged on a later sweep (the act came 10 s AFTER it), while the old flag isn't repeated",
     [f["resume_ts"] for f in flags2] == [T + 1950] and flags2[0]["agents"] == ["agent-z"], json.dumps(flags2))
want("C2: the trigger's message names the desktop and the agent",
     "agent-x" in (sweep_mod.tick({}, now=T + 1100) or "") and DESK in (sweep_mod.tick({}, now=T + 1100) or ""))
log.unlink()
acts.unlink()
hd.stop(DESK)
hd.resume(DESK)
want("C2 writer: hands_desktop.stop/resume append to the desktop's owner log (any caller: route or CLI)",
     [v for _, v in hd.owner_log(DESK)] == ["stop", "resume"], str(hd.owner_log(DESK)))
_real_session = hd._session
hd._session = lambda a, required=True: {}
hd._guard(hd.LAPTOP, "click")
hd._guard("desk-1", "click")
hd._session = _real_session
la = hd.laptop_acts()
want("C2 writer: an agent's act on the LAPTOP lands in its act log (name + agent, never text); a pool desk's doesn't",
     len(la) == 1 and la[0][1:] == ("click", "view-oracle"), str(la))

# ── B4: absent by omission ─────────────────────────────────────────────────────────────────────────────────────
avd_home = Path(os.environ.get("ANDROID_AVD_HOME") or Path.home() / ".android" / "avd").resolve()
r = subprocess.run(["bash", "nucleus/backup.sh", "--list-state"], cwd=REPO, capture_output=True, text=True,
                   timeout=60)
listed = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
if r.returncode != 0 or not listed:
    unver("B4 backup", f"backup.sh --list-state gave nothing (rc {r.returncode}): {r.stderr.strip()[:120]}")
else:
    under = []
    for x in listed:
        for base in (REPO, Path.home()):
            p = (base / x).resolve()
            if p == avd_home or avd_home in p.parents or p in avd_home.parents and p != Path.home():
                under.append(x)
    want("B4: backup.sh's state carries nothing that holds the phone's data (positive control: it listed "
         f"{len(listed)} paths)", not under, str(under))


def subvol(path):
    r = subprocess.run(["findmnt", "-no", "SOURCE", "-T", str(path)], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else None


if not shutil.which("snapper") or not shutil.which("findmnt"):
    unver("B4 snapper", "no snapper (or findmnt) here: nothing to compare")
else:
    r = subprocess.run(["snapper", "--csvout", "list-configs"], capture_output=True, text=True, timeout=20)
    rows = [ln.split(",") for ln in r.stdout.splitlines()[1:] if ln.strip()]
    vols = [row[1] for row in rows if len(row) > 1]
    if r.returncode != 0 or not vols:
        unver("B4 snapper", f"snapper listed no configs (rc {r.returncode})")
    else:
        mine = subvol(avd_home if avd_home.exists() else avd_home.parent if avd_home.parent.exists() else Path.home())
        covering = [v for v in vols if subvol(v) == mine]
        want("B4 control: the detection works (the config for '/' holds /usr)",
             "/" not in vols or subvol("/usr") == subvol("/"))
        want("B4: no snapper config's subvolume holds the phone's data (a home config would make this RED)",
             not covering and mine is not None, f"configs={vols} avd_subvol={mine}")

# ── B5: the VNC key never reaches the log ──────────────────────────────────────────────────────────────────────
from uvicorn.protocols.utils import get_path_with_query_string  # noqa: E402
cap = []


class _Cap(logging.Handler):
    def emit(self, record):
        cap.append(record.getMessage())


h = _Cap()
logging.getLogger("uvicorn.error").addHandler(h)
SENT = "SENTINEL-KEY-0123456789"
path = get_path_with_query_string({"path": f"/api/hands/{DESK}/vnc", "query_string": f"key={SENT}".encode()})
logging.getLogger("uvicorn.error").info('%s - "WebSocket %s" [accepted]', "127.0.0.1:5", path)
logging.getLogger("uvicorn.error").removeHandler(h)
want("B5: uvicorn's own websocket-accept line, through the filter the observatory installs, carries key=<redacted>",
     cap and SENT not in cap[-1] and "key=<redacted>" in cap[-1], str(cap[-1:]))


def _env_file(key):
    try:
        for ln in (REPO / ".env").read_text().splitlines():
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


live_key = _env_file("OBS_KEY")
active = subprocess.run(["systemctl", "is-active", "astryx-observatory"], capture_output=True, text=True).stdout.strip()
running = [d["agent"] for d in json.loads(subprocess.run(
    [sys.executable, "-c", "import json,sys; sys.path.insert(0,'.'); from nucleus import hands_desktop as h; "
     "print(json.dumps(h.status()))"], cwd=REPO, capture_output=True, text=True,
    env={k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_HANDS_")}).stdout or "[]") if d.get("running")]
if not live_key or active != "active" or not running or not shutil.which("journalctl"):
    unver("B5 live", f"needs the running observatory, a running desktop and its key (active={active!r}, "
          f"desktops={running}, key={'set' if live_key else 'absent'})")
else:
    import websockets
    t0 = time.time() - 1

    async def connect():
        url = f"ws://127.0.0.1:8090/api/hands/{running[0]}/vnc?key={live_key}"
        try:
            async with websockets.connect(url, open_timeout=10, close_timeout=2):
                await asyncio.sleep(0.5)
            return True
        except Exception as e:  # noqa: BLE001
            return f"{type(e).__name__}"

    res = asyncio.run(connect())
    time.sleep(2)
    j = subprocess.run(["journalctl", "-u", "astryx-observatory", "--since", f"@{t0:.0f}", "--no-pager", "-o", "cat"],
                       capture_output=True, text=True, timeout=30).stdout
    leaked = sum(1 for ln in j.splitlines() if live_key in ln)
    redacted = sum(1 for ln in j.splitlines() if "vnc?key=<redacted>" in ln)
    if res is not True or redacted == 0:
        unver("B5 live", f"the owner connect didn't produce a log line to judge (connect={res}, redacted lines="
              f"{redacted})")
    else:
        want(f"B5 LIVE: one owner VNC connect to {running[0]} adds 0 journal lines holding the key "
             f"(control: {redacted} redacted line(s) written)", leaked == 0, f"{leaked} line(s) carry the key")

shutil.rmtree(TMP, ignore_errors=True)
if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
if unverified:
    print(f"NOT VERIFIED: {', '.join(unverified)} (every other arm passed)")
    sys.exit(77)
print("PASS: phone view (owner stop through the real routes, Hands can't reach it, one spelling, resume sweep, "
      "persistence by omission, no key in the log)")
