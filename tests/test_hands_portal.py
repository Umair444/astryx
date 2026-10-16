#!/usr/bin/env python3
"""test_hands_portal: a desk's file chooser opens ON THE DESK (seed #57131, canopus #57128).

A desk is a `systemd-run --user` unit, so it inherited the owner's Hyprland display from the user manager. Its
dbus-daemon activated every portal there, and a site's upload button put a GTK file chooser on the owner's screen
while the desk's browser waited for it, stuck.

PURE (no session, never anything on a screen):
  P1 the desk unit UNSETS every owner-session variable the user manager carries (the set is derived from
     `systemctl --user show-environment`, by name: WAYLAND_DISPLAY, DISPLAY, HYPRLAND_*, XDG_SESSION_*, DESKTOP_SESSION;
     control: the declared set covers WAYLAND_DISPLAY and DISPLAY even on a host that exports neither)
  P2 sway publishes ITS display to the desk bus before the desk counts as up: the session file is written only after
     `dbus-update-activation-environment WAYLAND_DISPLAY SWAYSOCK` succeeds
  P3 the desk's portals.conf is on its XDG_CONFIG_DIRS and pins FileChooser=gtk, with hyprland's four off
LIVE (a throwaway desk under its own unit prefix and a short state root; never desk-1):
  GATE the fixture unit's UnsetEnvironment must hold WAYLAND_DISPLAY and DISPLAY, or no chooser is ever requested
       (a chooser from a desk with the owner's display lands on HIS screen: UNVERIFIED, and with P1 red, rc 1)
  L1 a FileChooser.OpenFile request on the desk bus is answered by a dialog in THAT desk's sway tree
     (RED before the fix, measured once at 09:52 PKT 10-16: request answered, desk tree empty; not re-run)
  L2 the desk's portal frontend picked no hyprland backend (its journal never says "Choosing hyprland.portal")
  S1-S5 a deadline is classified by MEASUREMENT (fixture desks that run no sway): still starting (sway's execs not
     run yet, the seat process alive) → HandsSlow → UNVERIFIED; died, the publish chain finished without a session,
     or no seat process → HandsError → RED (seed #57429: never read a slow host as broken, or as passing)
Pure arms run first; a red pure arm is rc 1 whatever the live arm says. DESK_SRC points at a mutant hands_desktop.py
(tests/mutants_hands_portal.py). Exit 0 pass · 1 fail · 77 not run (no sway/gdbus/user manager here).
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
fails, unverified = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def finish():
    if fails:
        print(f"\nFAIL ({len(fails)}): " + "; ".join(fails))
        sys.exit(1)
    if unverified:
        print(f"\nNOT VERIFIED: {', '.join(unverified)} (every other arm passed)")
        sys.exit(77)
    print("\nPASS: a desk's file chooser opens on the desk, never on the owner's screen")
    sys.exit(0)


RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
# a SHORT state root: wayvnc's control socket under a long temp path fails "File name too long"
ROOT = Path(tempfile.mkdtemp(prefix="hp-", dir=RUNTIME if RUNTIME.is_dir() else None))
os.environ["ASTRYX_HANDS_STATE"] = str(ROOT / "s")
os.environ["ASTRYX_HANDS_HOME"] = str(ROOT / "h")
os.environ["ASTRYX_HANDS_UNIT_PREFIX"] = f"astryx-hands-hp{os.getpid()}-"   # never the real desk-1's unit
AGENT = f"hp-{os.getpid()}"
user_env = {**os.environ, "XDG_RUNTIME_DIR": str(RUNTIME),
            "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={RUNTIME}/bus"}
hd = None
try:                               # from here on the state root is removed on EVERY exit, a subject that won't load too
    spec = importlib.util.spec_from_file_location(
        "astryx.hands.hands_desktop", os.environ.get("DESK_SRC") or REPO / "src/astryx/hands/hands_desktop.py")
    hd = importlib.util.module_from_spec(spec)
    sys.modules["astryx.hands.hands_desktop"] = hd
    spec.loader.exec_module(hd)
    print("pure:")
    if not hasattr(hd, "_desk_cmd") or not hasattr(hd, "PORTALS_CONF"):
        check("P0 the desk's unit command and portals.conf are readable without starting a desk", False,
              "no _desk_cmd / PORTALS_CONF")
        finish()
    cmd = hd._desk_cmd(AGENT)
    props = [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == "-p"]
    unset = {n for p in props if p.startswith("UnsetEnvironment=") for n in p.split("=", 1)[1].split()}
    owner = re.compile(r"^(WAYLAND_DISPLAY|DISPLAY|HYPRLAND_\w+|XDG_SESSION_\w+|DESKTOP_SESSION)$")
    r = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True, env=user_env)
    carried = {ln.split("=", 1)[0] for ln in r.stdout.splitlines() if "=" in ln} if r.returncode == 0 else set()
    needed = {n for n in carried if owner.match(n)} - {"XDG_SESSION_TYPE"} | {"WAYLAND_DISPLAY", "DISPLAY"}
    check(f"P1 the desk unit unsets every owner-session variable the user manager carries ({len(carried)} names read)",
          needed <= unset, f"not unset: {sorted(needed - unset)}")
    setenv = dict(cmd[i + 1].split("=", 1) for i, a in enumerate(cmd[:-1]) if a == "--setenv")
    check("P1 ...and sets none of them back", not (set(setenv) & needed), str(sorted(set(setenv) & needed)))
    conf = hd._sway_config(AGENT, 5999)
    execs = [ln for ln in conf.splitlines() if ln.startswith("exec ")]
    first = next((ln for ln in execs if "/session" in ln), "")
    check("P2 the session file is written only after sway's display is published to the desk bus",
          re.search(r"dbus-update-activation-environment (?=[^&]*\bWAYLAND_DISPLAY\b)(?=[^&]*\bSWAYSOCK\b)[^&]*&& printf",
                    first) is not None, first[:160])
    dirs = setenv.get("XDG_CONFIG_DIRS", "").split(":")
    sd = hd.state_dir(AGENT)
    pc = hd.PORTALS_CONF
    check("P3 the desk's own config dir is FIRST on its XDG_CONFIG_DIRS", dirs[:1] == [str(sd / "xdg")], str(dirs))
    check("P3 its portals.conf pins FileChooser to gtk",
          re.search(r"^org\.freedesktop\.impl\.portal\.FileChooser=gtk$", pc, re.M) is not None)
    check("P3 ...and turns hyprland's four off (none), naming hyprland nowhere",
          all(re.search(rf"^org\.freedesktop\.impl\.portal\.{i}=none$", pc, re.M)
              for i in ("ScreenCast", "Screenshot", "GlobalShortcuts", "InputCapture")) and "hyprland" not in pc)

    print("live:")
    tools = [t for t in ("sway", "swaymsg", "wayvnc", "grim", "dbus-run-session", "dbus-update-activation-environment",
                         "gdbus", "systemd-run") if not shutil.which(t)]
    if tools or r.returncode != 0:
        unverified.append("L1/L2")
        print(f"  UNVERIFIED L1/L2: needs sway, gdbus and a user systemd manager (missing {tools or 'the manager'})")
        finish()
    if fails:                      # a pure red means the unit may carry the owner's display: never issue a chooser
        unverified.append("L1/L2")
        print("  UNVERIFIED L1/L2: a pure arm is red, so no chooser is requested (it could land on the owner's screen)")
        finish()
    # S: a desk still STARTING at a deadline is the host being slow (UNVERIFIED); a desk that DIED, or whose step
    # finished without its result, is broken (RED). Measured from the unit's processes, never from the clock (seed
    # #57429: the HOLD's load 14 turned a slow desk into a red gate). Fixture desks run no sway and draw nothing.
    real_cmd = hd._desk_cmd

    def fixture(name, script):
        hd._desk_cmd = lambda a: real_cmd(a)[:real_cmd(a).index("--") + 1] + ["bash", "-c", script]
        try:
            hd.up(name)
            return "up"
        except hd.HandsSlow as e:
            return f"slow: {e}"
        except hd.HandsError as e:
            return f"error: {e}"
        finally:
            hd._desk_cmd = real_cmd
            try:
                hd.down(name)
            except Exception:
                pass
    fx = f"{AGENT}-fx"
    fsd = hd.state_dir(fx)
    (ROOT / "wl").write_text("")
    (ROOT / "ss").write_text("")
    session = f"printf '%s %s\\n' {ROOT.name}/wl {ROOT / 'ss'} > {fsd}/session"
    got = fixture(fx, "exec sleep 60")
    check("S1 a desk whose sway hasn't run its execs at the deadline is SLOW (HandsSlow), not broken",
          got.startswith("slow:") and "startup execs" in got, got[:200])
    got = fixture(fx, "exit 3")
    check("S2 a desk that DIED is broken (HandsError), never slow", got.startswith("error:"), got[:200])
    got = fixture(fx, f"printf ok > {fsd}/execs; exec sleep 60")
    check("S3 a desk whose publish chain FINISHED without a session is broken, though its unit is up",
          got.startswith("error:"), got[:200])
    got = fixture(fx, f"{session}; exec -a hands_seat.py sleep 60")
    check("S4 a desk whose seat process runs but hasn't answered is SLOW", got.startswith("slow:") and "seat" in got,
          got[:200])
    got = fixture(fx, f"{session}; exec sleep 60")
    check("S5 a desk with a session but NO seat process is broken", got.startswith("error:"), got[:200])
    if fails:
        finish()

    t0 = time.time()
    try:
        hd.up(AGENT)
    except hd.HandsSlow as e:                     # the host is slow: say so, never read it as broken or as passing
        unverified.append("L1/L2")
        print(f"  UNVERIFIED L1/L2: {e}")
        finish()
    except hd.HandsError as e:
        check("L0 the fixture desk comes up", False, str(e)[:200])
        finish()
    got = subprocess.run(["systemctl", "--user", "show", "-p", "UnsetEnvironment", "--value", hd.unit(AGENT)],
                         capture_output=True, text=True, env=user_env).stdout.split()
    if not {"WAYLAND_DISPLAY", "DISPLAY"} <= set(got):
        unverified.append("L1/L2")
        print(f"  UNVERIFIED L1/L2: the fixture unit doesn't unset the owner's display ({got}): no chooser requested")
        finish()
    out = hd.state_dir(AGENT) / "fc.out"
    hd._sway(AGENT, "exec sh -c " + hd._q(
        "gdbus call --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop "
        f"--method org.freedesktop.portal.FileChooser.OpenFile '' 'hands-portal-oracle' '{{}}' > {out} 2>&1"))
    apps = []
    for _ in range(40):
        time.sleep(0.5)
        apps = re.findall(r'"app_id": "([^"]*)"', hd._run(AGENT, ["swaymsg", "-t", "get_tree"]).decode())
        if any("portal" in a for a in apps):
            break
    check("L1 control: the request reached the portal (it returned a request handle)",
          out.exists() and "/org/freedesktop/portal/desktop/request/" in out.read_text(),
          out.read_text()[:200] if out.exists() else "no output")
    check("L1 the file chooser is a window in the DESK's sway tree", any("xdg-desktop-portal-gtk" in a for a in apps),
          f"desk windows: {apps}")
    j = subprocess.run(["journalctl", "--user", "-u", hd.unit(AGENT), "--since", f"@{int(t0) - 1}", "--no-pager",
                        "-o", "cat"], capture_output=True, text=True, env=user_env).stdout
    check("L2 control: the desk's journal shows its portal frontend running", "xdg-desktop-portal" in j)
    check("L2 no hyprland backend was picked for the desk", "Choosing hyprland.portal" not in j,
          next((ln for ln in j.splitlines() if "hyprland.portal" in ln), "")[:160])
finally:
    try:
        if hd is not None and hasattr(hd, "down"):
            hd.down(AGENT)
    except Exception as e:                                   # a teardown failure must not mask the verdict
        print(f"  (teardown: {type(e).__name__}: {e})")
    shutil.rmtree(ROOT, ignore_errors=True)
finish()
