#!/usr/bin/env python3
"""Oracle: the Windows VM on demand (plan-8675 C5, a4 #42255 / #48958). Never the owner's VM: a STAND-IN container plays
it, and the vm-slot lives in a fixture database.

  W1 RED (a4): the slot is held by a live other VM → opening the Windows viewer is REFUSED naming the holder, the
     container stays stopped, nothing is recorded, and no browser opens
  W2 a free slot → the open claims it for "windows", starts the container, records that IT started it, opens the page
  W3 any other URL (another port, another host) never touches the slot or the container
  W4 (i) idle stop of a run the open STARTED: before the idle window → nothing; past it → a stop is ISSUED (detached:
     the tick returns at once, inside the pulse's budget) and the slot stays held until the container is really
     down; the next tick frees the slot and clears the record
  W5 (ii) a VM ALREADY running when the open claimed the slot is held but NEVER auto-stopped
  W6 (iii) a live connection keeps an agent-started VM up
  W7 HANDS_WINDOWS_IDLE_S=0 disables the stop
  W8 the viewer-URL test is exact (port and host), not a substring
  W9 the record is bound to ITS run by the container's StartedAt: a later run (restarted out of band, or brought back
     by a host reboot) is never stopped as ours, and the stale record is dropped (a4 #49102)
Needs docker, a local image for the stand-in and a fixture database, else 77.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
TMP = Path(tempfile.mkdtemp(prefix="win-ondemand-oracle-"))
os.environ["ASTRYX_HANDS_STATE"] = str(TMP / "state")
os.environ["ASTRYX_HANDS_HOME"] = str(TMP / "home")
os.environ["ASTRYX_AGENT"] = "win-oracle"
os.environ["HANDS_WINDOWS_IDLE_S"] = "600"
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def skip(why):
    print(f"SKIP: {why}. Nothing was verified here.")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(77)


def docker(*a, timeout=60):
    return subprocess.run(["docker", *a], capture_output=True, text=True, timeout=timeout)


if not shutil.which("docker") or docker("info").returncode != 0:
    skip("docker is unavailable")
IMG = next((i for i in ("astryx-hands-cell", "astryx-hands-proxy") if docker("image", "inspect", i).returncode == 0),
           None)
if IMG is None:
    skip("no local image to run a stand-in container")
try:
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db
except ImportError as e:
    skip(f"deps ({e})")

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


android = _load("nucleus.android", "nucleus/android.py", "ANDROID_SRC")
hd = _load("nucleus.hands_desktop", "nucleus/hands_desktop.py", "HANDS_DESKTOP_SRC")
stop_mod = _load("windows_idle_stop", "nucleus/shipped_triggers/windows_idle_stop.py", "WIN_IDLE_SRC")
from nucleus import ear_lease as L  # noqa: E402

STAND_IN = f"astryx-test-win-{os.getpid()}"
android.WINDOWS_CONTAINER = STAND_IN
opened = []
hd._session = lambda a, required=True: {}
hd._sway = lambda a, cmd: opened.append(cmd) or []
hd.browser_argv = lambda a, url=None: ["browser", url or ""]
DESK = "desk-1"
running = lambda: docker("inspect", "--format", "{{.State.Running}}", STAND_IN).stdout.strip() == "true"  # noqa: E731


def fresh_stand_in(start=False):
    docker("rm", "-f", STAND_IN)
    docker("create", "--init", "--name", STAND_IN, "--entrypoint", "sleep", IMG, "3000")
    if start:
        docker("start", STAND_IN)


try:
    with fixture_db() as fx:
        os.environ["ANDROID_DSN"] = fx["dsn"]
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            slot = lambda: (L.get(c, "vm-slot") or {}).get("holder")  # noqa: E731
            # ── W8 ─────────────────────────────────────────────────────────────────────────────────────────────
            yes = ["127.0.0.1:8006", "http://localhost:8006/vnc.html?autoconnect=1", "https://127.0.0.1:8006"]
            no = ["127.0.0.1:80060", "http://127.0.0.1:8007/", "https://evil.example/127.0.0.1:8006",
                  "http://10.0.0.5:8006/", "example.com"]
            want("W8 the viewer test matches 127.0.0.1/localhost:8006 exactly, and nothing else",
                 all(hd.is_windows_viewer(u) for u in yes) and not any(hd.is_windows_viewer(u) for u in no),
                 str([(u, hd.is_windows_viewer(u)) for u in yes + no]))
            # ── W1: RED ─────────────────────────────────────────────────────────────────────────────────────────
            fresh_stand_in()
            L.hold(c, "vm-slot", "oracle-live-vm", 600)
            try:
                hd.open_(DESK, "http://127.0.0.1:8006/")
                want("W1 a live other holder: the open is REFUSED", False, "it opened")
            except hd.HandsError as e:
                want("W1 a live other holder: the open is REFUSED, naming the holder", "oracle-live-vm" in str(e), str(e))
            want("W1 ...the container stays stopped, nothing is recorded, no browser opened",
                 not running() and not hd.WINDOWS_STARTED.exists() and not opened, f"{running()} {opened}")
            L.unhold(c, "vm-slot", "oracle-live-vm")
            # ── W2 ──────────────────────────────────────────────────────────────────────────────────────────────
            hd.open_(DESK, "http://127.0.0.1:8006/")
            rec = json.loads(hd.WINDOWS_STARTED.read_text()) if hd.WINDOWS_STARTED.exists() else {}
            want("W2 a free slot: claimed for windows, the container started, the start recorded, the page opened",
                 slot() == "windows" and running() and rec.get("container") == STAND_IN and len(opened) == 1,
                 f"slot={slot()} running={running()} rec={rec} opened={opened}")
            # ── W3 ──────────────────────────────────────────────────────────────────────────────────────────────
            before = (slot(), running(), hd.WINDOWS_STARTED.read_text())
            for u in ("http://127.0.0.1:9999/", "https://example.com/"):
                hd.open_(DESK, u)
            want("W3 other URLs never touch the slot or the container",
                 (slot(), running(), hd.WINDOWS_STARTED.read_text()) == before and len(opened) == 3)
            # ── W4 (i) ──────────────────────────────────────────────────────────────────────────────────────────
            st = {}
            t0 = rec["ts"]
            none = lambda: 0  # noqa: E731
            want("W4 an agent-started VM inside its idle window is left alone",
                 stop_mod.tick(st, now=t0 + 599, conns=none) is None and running())
            t = time.time()
            msg = stop_mod.tick(st, now=t0 + 601, conns=none)
            took = time.time() - t
            want("W4 past the idle window a stop is ISSUED, detached (the tick returns at once)",
                 msg and "stopping the Windows VM" in msg and took < 3 and st.get("stopping"), f"{msg} {took:.1f}s")
            want("W4 ...and the slot stays held while the container is still going down",
                 slot() == "windows", str(slot()))
            for _ in range(60):
                if not running():
                    break
                time.sleep(1)
            msg = stop_mod.tick(st, now=t0 + 700, conns=none)
            want("W4 once it's down, the next tick frees the slot and clears the record",
                 not running() and slot() is None and not hd.WINDOWS_STARTED.exists() and msg and "slot is free" in msg,
                 f"running={running()} slot={slot()} msg={msg}")
            # ── W5 (ii) ─────────────────────────────────────────────────────────────────────────────────────────
            fresh_stand_in(start=True)
            hd.open_(DESK, "http://127.0.0.1:8006/")
            want("W5 a VM ALREADY running: the open holds the slot but records no start",
                 slot() == "windows" and not hd.WINDOWS_STARTED.exists(), f"slot={slot()}")
            st = {}
            want("W5 ...and it is NEVER auto-stopped, however idle",
                 stop_mod.tick(st, now=time.time() + 10 ** 6, conns=none) is None and running())
            L.unhold(c, "vm-slot", "windows")
            # ── W9: the record is bound to ITS run (a4 #49102) ───────────────────────────────────────────────────
            fresh_stand_in()
            hd.open_(DESK, "http://127.0.0.1:8006/")
            rec9 = json.loads(hd.WINDOWS_STARTED.read_text())
            docker("restart", "-t", "2", STAND_IN)                 # out of band: the owner's restart, or a reboot
            st = {}
            out9 = stop_mod.tick(st, now=rec9["ts"] + 10 ** 6, conns=none)
            want("W9 a LATER run of the container (restarted out of band) is never stopped as ours, and the stale "
                 "record is dropped", out9 is None and running() and not hd.WINDOWS_STARTED.exists()
                 and rec9.get("started_at"), f"out={out9} running={running()} rec={rec9}")
            L.unhold(c, "vm-slot", "windows")
            # ── W6 (iii) + W7 ───────────────────────────────────────────────────────────────────────────────────
            fresh_stand_in()
            hd.open_(DESK, "http://127.0.0.1:8006/")
            t0 = json.loads(hd.WINDOWS_STARTED.read_text())["ts"]
            st = {}
            want("W6 a live connection keeps an agent-started VM up",
                 stop_mod.tick(st, now=t0 + 10 ** 5, conns=lambda: 1) is None and running() and not st.get("stopping"))
            os.environ["HANDS_WINDOWS_IDLE_S"] = "0"
            st = {}
            want("W7 HANDS_WINDOWS_IDLE_S=0 disables the stop",
                 stop_mod.tick(st, now=t0 + 10 ** 6, conns=none) is None and running())
            os.environ["HANDS_WINDOWS_IDLE_S"] = "600"
finally:
    docker("rm", "-f", STAND_IN)
    shutil.rmtree(TMP, ignore_errors=True)

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: Windows on demand (claim before start, refuse naming the holder, idle stop only of its own starts)")
