#!/usr/bin/env python3
"""Oracle: an agent drives a real Android phone through the facade, end to end, on a PUBLIC app (plan-8675 S1).

    ANDROID_DEVICE_TEST=1 venv/bin/python tests/test_android_device.py
    (77 without that, and unless this org opted in and the phone is installed: check.sh runs it, and it says so)

It boots the org's phone (ANDROID_AVD) through act("boot"), drives Settings, and switches it off again. Leases live
in a throwaway fixture database (ANDROID_DSN, set explicitly); stop flags in a throwaway state dir. Never a money app.

  D1 boot: the phone comes up through the facade; every boot re-applies the quiet notification settings (all three
     read back 0) and makes the phone's data owner-only (no file in the .avd dir readable by group or others)
  D2 launch Settings: the answer ends with the surface stamp, and it says "org" (Settings + system decor)
  D3 look(text): the elements include a Settings label; the stamp is the LAST block and says "org"
  D4 look(): a picture, then the stamp
  D5 a notification POSTED with the shade closed adds no window off the public list (heads-up is off: the status bar
     shows an icon, no text); the shade PULLED DOWN makes the stamp "personal" (C3 RED arm)
  D6 a second agent acting on the phone is refused, naming the driver (C4); after act("done") it may drive
  D7 the owner's stop for an agent refuses its phone actions; resume restores them
  D8 shutdown frees the VM slot and the phone's driver hold; with a "Windows VM" running (a stand-in container named
     by WINDOWS_CONTAINER) boot is refused and the phone stays off
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
fails, unverified = [], []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def skip(why):
    print(f"SKIP: {why}. Nothing was verified here.")
    sys.exit(77)


if os.environ.get("ANDROID_DEVICE_TEST") != "1":
    skip("it boots a ~3 GB phone for minutes, so it runs only on request: ANDROID_DEVICE_TEST=1 "
         "venv/bin/python tests/test_android_device.py")
rc = subprocess.run([str(REPO / "nucleus/android_setup.sh"), "check"], capture_output=True, text=True)
if rc.returncode != 0 or not rc.stdout.startswith("ready"):          # "off" exits 0 too: only "ready" runs
    skip(f"the phone isn't set up here ({rc.stdout.strip() or rc.stderr.strip()})")
STAND_IN = f"astryx-test-vm-{os.getpid()}"
os.environ["ASTRYX_HANDS_STATE"] = tempfile.mkdtemp(prefix="phone-oracle-state-")
os.environ["ASTRYX_AGENT"] = "phone-oracle-a"

from nucleus import android as droid  # noqa: E402
if droid.windows_running():
    skip("the Windows VM is running: the phone can't run beside it on this machine (that's the vm-slot rule)")
AVD = droid.default_avd()
if droid.emulator_pids(AVD):
    skip(f"{AVD} is already running (in use?): this oracle boots and stops it itself")

from nucleus.sqlguard.fixture import fixture_db  # noqa: E402
import importlib.util  # noqa: E402
_s = importlib.util.spec_from_file_location("phone_server", REPO / "mcp/phone/server.py")
srv = importlib.util.module_from_spec(_s)
_s.loader.exec_module(srv)
from nucleus import hands_desktop as hd  # noqa: E402

STAMP = "astryx-surface: "


def tier(out):
    """The stamp's tier, read only from the LAST block (as step.py reads it); None if it isn't a stamp."""
    last = out[-1] if out else None
    if not (isinstance(last, str) and last.startswith(STAMP)):
        return None
    return json.loads(last[len(STAMP):]).get("tier")


def run(coro):
    return asyncio.run(coro)


def as_agent(name):
    srv.AGENT = name


A = lambda s: srv.droid.adb(*s.split(), serial=droid.serial(AVD), timeout=60)  # noqa: E731
import re  # noqa: E402
import time  # noqa: E402


def settle(want_org=True, tries=12):
    """look(text) until the screen is settled: a loaded host makes apps show "isn't responding" dialogs (measured);
    an agent taps Wait, and so does this. Returns the last answer."""
    out = []
    for _ in range(tries):
        out = run(srv.look(AVD, text=True))
        body = "\n".join(o for o in out[:-1] if isinstance(o, str))
        m = re.search(r'Button text="Wait"[^\n]* at=(\d+),(\d+) size=(\d+)x(\d+)', body)
        if m:
            x, y, w, h = map(int, m.groups())
            run(srv.act("tap", device=AVD, x=x + w // 2, y=y + h // 2))
            time.sleep(5)
            continue
        if body.startswith("phone error"):          # upstream's dump failed (a starved phone): look again
            time.sleep(5)
            continue
        if not want_org or tier(out) == "org":
            return out
        time.sleep(5)
    return out
try:
    with fixture_db() as fx:
        os.environ["ANDROID_DSN"] = fx["dsn"]                     # the lease axis, set explicitly
        as_agent("phone-oracle-a")
        # ── D1 ─────────────────────────────────────────────────────────────────────────────────────────────────
        out = run(srv.act("boot", device=AVD))
        up = bool(droid.serial(AVD))
        want("D1 the phone boots through act('boot')", up and "is up" in str(out[0]), str(out[:1]))
        if not up:
            raise SystemExit("no phone: the remaining arms can't run")
        vals = [A(f"shell settings get {ns} {k}").stdout.strip() for ns, k, _ in droid.QUIET]
        want("D1 every boot setting reads back as set (pop-ups off, lock-screen text off, awake)",
             vals == [v for _, _, v in droid.QUIET], f"{vals} vs {[v for _, _, v in droid.QUIET]}")
        home = Path(os.environ.get("ANDROID_AVD_HOME") or Path.home() / ".android/avd") / f"{AVD}.avd"
        loose = [str(p) for p in home.rglob("*") if p.stat().st_mode & 0o077]
        want("D1 nothing in the phone's .avd dir is readable by group or others", not loose, str(loose[:3]))
        # ── D2 ─────────────────────────────────────────────────────────────────────────────────────────────────
        out = run(srv.act("launch", device=AVD, app="com.android.settings"))
        want("D2 upstream launched Settings, and the answer ends with a stamp",
             "Launched app com.android.settings" in str(out[0]) and tier(out) is not None, str(out))
        time.sleep(6)
        # Settled AND drawn: a launch is animated first (measured: the list held only System UI's launch container,
        # an org screen with none of Settings' labels yet), so wait for Settings' own content before judging it.
        labels = ("Network", "Search settings", "Connected devices", "Apps")
        for _ in range(6):
            out = settle()
            body = json.dumps(out[:-1])
            if any(w in body for w in labels):
                break
            time.sleep(5)
        want("D3 look(text) shows Settings' own labels", any(w in body for w in labels), body[:400])
        want("D3 ...and its stamp, LAST, says org (Settings + system decor)", tier(out) == "org", str(out[-1:]))
        out = run(srv.look(AVD))
        want("D4 look() returns upstream's picture (and its scale note), then the stamp",
             any(not isinstance(o, str) for o in out[:-1]) and "Screenshot is" in str(out[0]) and tier(out) is not None,
             str([o[:60] if isinstance(o, str) else type(o).__name__ for o in out]))
        # ── D5 ─────────────────────────────────────────────────────────────────────────────────────────────────
        def shown():
            """Visible windows, minus "isn't responding" dialogs (a loaded host's noise, not the notification)."""
            r = A("shell dumpsys window windows")
            return {(w["package"], w["title"]) for w in srv._surface.windows(r.stdout)
                    if w["visible"] and not w["title"].startswith("Application Not Responding")}
        before_w = shown()
        A("shell cmd notification post -t oracle-title oracle-tag oracle-body-text")
        time.sleep(5)
        new_w = shown() - before_w
        # The launcher's Taskbar shows and hides by itself (measured), so the claim is about TAINT, not any change:
        # every window that appeared must be on the public list. A pop-up surface would not be.
        taint = srv._surface.classify([{"package": p, "title": t, "visible": True} for p, t in new_w])["unlisted"] \
            if new_w else []
        want("D5 a posted notification (shade closed, heads-up off) adds no window off the public list: no pop-up",
             bool(before_w) and not taint, f"new={sorted(new_w)} unlisted={taint}")
        A("shell cmd statusbar expand-notifications")
        # PRECONDITION first: the shade must really be open (its window visible). On a starved host System UI can stop
        # drawing at all (measured: no StatusBar or NotificationShade window for minutes), and then "personal" or
        # "org" would say nothing about the shade. Unmet → UNVERIFIED, never PASS.
        opened = False
        for _ in range(12):
            if ("com.android.systemui", "NotificationShade") in shown():
                opened = True
                break
            time.sleep(5)
        if not opened:
            print("  UNVERIFIED D5 the shade PULLED DOWN makes the screen personal: the shade never opened "
                  "(System UI isn't drawing), so this run can't test it")
            unverified.append("D5 shade RED")
        else:
            out = run(srv.look(AVD, text=True))
            want("D5 the shade PULLED DOWN (its window visible) makes the screen personal (C3 RED)",
                 tier(out) == "personal", str(out[-1:]))
        A("shell cmd statusbar collapse")
        A("shell cmd notification cancel oracle-tag")
        time.sleep(3)
        # ── D6 ─────────────────────────────────────────────────────────────────────────────────────────────────
        as_agent("phone-oracle-b")
        out = run(srv.act("foreground", device=AVD))
        want("D6 a second agent is refused, naming the driver", "phone-oracle-a" in str(out[0]), str(out[:1]))
        as_agent("phone-oracle-a")
        run(srv.act("done", device=AVD))
        as_agent("phone-oracle-b")
        out = run(srv.act("button", device=AVD, button="BACK"))
        want("D6 after the driver says done, the other agent drives (upstream pressed BACK)",
             "Pressed the button: BACK" in str(out[0]), str(out[:1]))
        # ── D7 ─────────────────────────────────────────────────────────────────────────────────────────────────
        hd.stop("phone-oracle-b", "the owner stopped your hands (oracle)")
        out = run(srv.act("foreground", device=AVD))
        want("D7 the owner's stop refuses the agent's phone action", str(out[0]).startswith("STOPPED"), str(out[:1]))
        hd.resume("phone-oracle-b")
        out = run(srv.act("button", device=AVD, button="HOME"))
        want("D7 resume restores it (upstream pressed HOME)", "Pressed the button: HOME" in str(out[0]), str(out[:1]))
        # ── D8 ─────────────────────────────────────────────────────────────────────────────────────────────────
        out = run(srv.act("shutdown", device=AVD))
        import psycopg
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            rows = dict(c.execute("SELECT resource, state FROM leases WHERE resource IN ('vm-slot', %s)",
                                  (f"android:{AVD}",)).fetchall())
        want("D8 shutdown stops the phone", not droid.emulator_pids(AVD), str(out[:1]))
        want("D8 ...and frees the VM slot and the driver hold", set(rows.values()) <= {"free"}, str(rows))
        img = "astryx-hands-cell" if subprocess.run(["docker", "image", "inspect", "astryx-hands-cell"],
                                                     capture_output=True).returncode == 0 else None
        if img is None:
            print("  UNVERIFIED D8 refusal: no local image to run a stand-in Windows VM container")
            fails.append("D8 refusal UNVERIFIED")
        else:
            subprocess.run(["docker", "run", "-d", "--rm", "--name", STAND_IN, "--entrypoint", "sleep", img, "300"],
                           capture_output=True, check=True)
            droid.WINDOWS_CONTAINER = STAND_IN
            out = run(srv.act("boot", device=AVD))
            want("D8 with a Windows VM running, boot is refused, saying why", "Windows VM is running" in str(out[0]),
                 str(out[:1]))
            want("D8 ...and the phone stays off", not droid.emulator_pids(AVD))
finally:
    if droid.emulator_pids(AVD):
        droid.adb("emu", "kill", serial=droid.serial(AVD), timeout=20)
    subprocess.run(["docker", "rm", "-f", STAND_IN], capture_output=True)
    shutil.rmtree(os.environ["ASTRYX_HANDS_STATE"], ignore_errors=True)
    droid.adb("kill-server", timeout=10)

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
if unverified:
    print(f"NOT VERIFIED: {', '.join(unverified)} (every other arm passed)")
    sys.exit(77)
print("PASS: an agent drove a real phone through the facade on a public app; stamp, leases, stop and vm-slot hold")
