#!/usr/bin/env python3
"""astryx · hands — an agent's own desktop, on the owner's machine (plan-7862, owner 2026-10-10).

The owner's ruling: "it should use my laptop like i can do — nothing container… let it keep going
with its own cursor… i want to participate." So an agent's hands are a REAL desktop session on
this machine, not a sandbox:

    a headless sway (wlroots) session per agent, with its own Wayland display, its own seat and
    cursor, its own D-Bus session (so its apps never pop up in the owner's session), and a
    PERSISTENT home for its apps: a browser profile it keeps, so a login the owner makes once
    (WhatsApp Web's QR, a Google account) is still there tomorrow. Agents hold onto stuff.

    wayvnc serves that desktop to whoever watches. -t gives EVERY viewer a transient seat of its
    own, so the owner clicks and types with his own cursor while the agent keeps going with
    the agent's. He watches and joins from the observatory (Hands view) or any VNC viewer.

TWO KINDS OF DESKTOP (plus the shared pool, below). `laptop` is the owner's REAL screen: his Hyprland session, his own
Chromium with his logins (WhatsApp is already there), every app he has (owner, 10-10: "why is it
not using this laptop — chrome has whatsapp already logged in here"). The agent shares his one
cursor there, so it's for work he hands over. Every other name is that agent's OWN desktop: a
second, headless session on this machine that he can't see on his monitor (only in the
observatory), with its own browser profile, so it can work in the background without touching
his cursor.

The agent sees by screenshot (grim) and acts through ITS OWN SEAT: src/astryx/hands/hands_seat.py holds a
VNC connection to the desktop for the session's life, so the agent is a participant exactly like
the owner, with its own cursor and keyboard focus. Everything is a standard wlroots tool driven at code speed; there
is no model in here. The agent IS the driver: its own session calls the hands MCP server
(mcp/hands/server.py), sees the screen, acts, and sees again.

Lifecycle: one systemd --user unit per agent (astryx-hands-<agent>). `sway` runs inside
`dbus-run-session`; the sway config starts wayvnc and writes the session's coordinates to the
state dir. Stopping the unit ends the session; the HOME (profile) stays.

OWNER STOP: the owner can stop an agent's hands from the observatory at any moment. It's a file
in the state dir. While it exists every action refuses with "the owner stopped your hands", and
the agent is told so. Resume removes it.

CAPS (plan-7862, seed's binding item): every AGENT (the resident, not the desktop) has a STEP cap and a WALL-TIME
cap per session (a run of its calls with no gap longer than HANDS_CAP_IDLE_S; a REFUSED call counts as a call), and
a DAILY step cap. At a cap every call refuses, naming it, until the agent has made no calls at all for that long (or,
for the daily cap, the UTC day turns), or the owner resets it. .env: HANDS_STEP_CAP (300), HANDS_WALL_CAP_S (3600),
HANDS_CAP_IDLE_S (600), HANDS_DAY_STEP_CAP (2000). Same-uid grade: a guard against runaway loops, not a cage.

    venv/bin/python src/astryx/hands/hands_desktop.py up <agent>
    venv/bin/python src/astryx/hands/hands_desktop.py down <agent>
    venv/bin/python src/astryx/hands/hands_desktop.py status [<agent>]
    venv/bin/python src/astryx/hands/hands_desktop.py shot <agent> <out.jpg>
    venv/bin/python src/astryx/hands/hands_desktop.py caps-reset <agent>      (a fresh session for that agent)
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

UID = os.getuid()
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{UID}")
# shared-on-purpose: the live org's desktop pool state (one pool per host); a gate sets ASTRYX_HANDS_STATE under its TMPDIR
STATE_ROOT = Path(os.environ.get("ASTRYX_HANDS_STATE") or RUNTIME / "astryx-hands")
HOME_ROOT = Path(os.environ.get("ASTRYX_HANDS_HOME")
                 or Path.home() / ".local" / "share" / "astryx-hands")
WIDTH, HEIGHT = 1440, 900
VNC_PORTS = range(5910, 5990)
SETTLE_S = 0.6            # after an action, let the app repaint before the screenshot

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


class HandsError(RuntimeError):
    pass


class Stopped(HandsError):
    pass


LAPTOP = "laptop"


def is_laptop(agent: str) -> bool:
    return agent == LAPTOP


def _hypr() -> dict | None:
    """The owner's live Hyprland session: its instance signature and Wayland socket."""
    try:
        r = subprocess.run(["hyprctl", "-j", "instances"], capture_output=True, text=True,
                           timeout=5, env=_user_env())
        inst = json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    inst = [i for i in inst if (RUNTIME / i.get("wl_socket", "-")).exists()]
    if not inst:
        return None
    i = max(inst, key=lambda i: i.get("time", 0))
    return {"HYPRLAND_INSTANCE_SIGNATURE": i["instance"], "WAYLAND_DISPLAY": i["wl_socket"]}


def _hyprctl(*args: str) -> str:
    h = _hypr()
    if not h:
        raise HandsError("the owner's Hyprland session isn't running")
    r = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=10,
                       env={**_user_env(), **h})
    if r.returncode != 0 or r.stdout.strip() not in ("", "ok") and args[0] == "dispatch":
        raise HandsError(f"hyprctl {' '.join(args[:2])}: {(r.stdout or r.stderr).strip()[:200]}")
    return r.stdout


def _hdispatch(lua: str, legacy: tuple[str, ...]) -> None:
    """A Hyprland dispatch on the owner's session. Hyprland >= 0.56 (Lua config) takes a dispatcher
    expression, e.g. hl.dsp.focus({window="address:0x…"}); older versions take `dispatch <name> <args>`.
    Try the Lua form, fall back to the legacy one, raise only if both refuse (measured on 0.56.2)."""
    try:
        _hyprctl("dispatch", lua)
    except HandsError:
        _hyprctl("dispatch", *legacy)


def _lua_str(s: str) -> str:
    level = "=" * next(n for n in range(1, 10) if f"]{'=' * n}]" not in s)
    return f"[{level}[{s}]{level}]"


def _monitor() -> dict:
    mons = json.loads(_hyprctl("-j", "monitors") or "[]")
    if not mons:
        raise HandsError("no monitor on the owner's session")
    return next((m for m in mons if m.get("focused")), mons[0])


def size(agent: str) -> tuple[int, int]:
    if is_laptop(agent):
        m = _monitor()
        return int(m["width"] / m.get("scale", 1)), int(m["height"] / m.get("scale", 1))
    return WIDTH, HEIGHT


def _name(agent: str) -> str:
    if not NAME_RE.match(agent or ""):
        raise HandsError(f"bad agent name {agent!r}")
    return agent


UNIT_PREFIX = os.environ.get("ASTRYX_HANDS_UNIT_PREFIX") or "astryx-hands-"   # tests set their own


def unit(agent: str) -> str:
    return f"{UNIT_PREFIX}{_name(agent)}"


def state_dir(agent: str) -> Path:
    return STATE_ROOT / _name(agent)


def home_dir(agent: str) -> Path:
    return HOME_ROOT / _name(agent)


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_port(agent: str) -> int:
    taken = set()
    if STATE_ROOT.exists():
        for d in STATE_ROOT.iterdir():
            if d.name != agent and (d / "port").exists():
                try:
                    taken.add(int((d / "port").read_text()))
                except ValueError:
                    pass
    prev = state_dir(agent) / "port"
    if prev.exists():
        p = int(prev.read_text())
        if p not in taken and _port_free(p):
            return p
    for p in VNC_PORTS:
        if p not in taken and _port_free(p) and _port_free(p + 100):
            return p
    raise HandsError("no free VNC port in 5910-5989")


def _user_env() -> dict:
    # callable from a system service too (the observatory): reach the owner's user manager
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", str(RUNTIME))
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={RUNTIME}/bus")
    return env


def _systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                          check=check, timeout=30, env=_user_env())


def alive(agent: str) -> bool:
    if _systemctl("is-active", "--quiet", unit(agent)).returncode != 0:
        return False
    if is_laptop(agent):
        return _hypr() is not None and (state_dir(agent) / "seat.sock").exists()
    return _session(agent, required=False) is not None


def _session(agent: str, required: bool = True) -> dict | None:
    """The live session's coordinates, written by sway's own exec at startup."""
    if is_laptop(agent):
        h = _hypr()
        if not h and required:
            raise HandsError("the owner's Hyprland session isn't running")
        if h:
            h["SWAYSOCK"] = ""
        return h
    f = state_dir(agent) / "session"
    try:
        wayland, swaysock = f.read_text().split()
    except (OSError, ValueError):
        if required:
            raise HandsError(f"{agent}'s desktop is not running (hands up first)")
        return None
    if not (RUNTIME / wayland).exists() or not Path(swaysock).exists():
        if required:
            raise HandsError(f"{agent}'s desktop session is gone")
        return None
    return {"WAYLAND_DISPLAY": wayland, "SWAYSOCK": swaysock}


def _sway_config(agent: str, port: int) -> str:
    sd = state_dir(agent)
    return f"""# generated by src/astryx/hands/hands_desktop.py — {agent}'s desktop
output HEADLESS-1 resolution {WIDTH}x{HEIGHT} position 0 0
output * bg #11111b solid_color
default_border normal 2
default_floating_border normal 2
font pango:sans 10
focus_follows_mouse no
mouse_warping none
workspace_layout tabbed
exec sh -c 'printf "%s %s\\n" "$WAYLAND_DISPLAY" "$SWAYSOCK" > {sd}/session'
exec wayvnc -r -S {sd}/wayvnc.sock 127.0.0.1 {port}
exec {sys.executable} {Path(__file__).resolve().parent / "hands_seat.py"} {port} {sd}/seat.sock
exec {sys.executable} {Path(__file__).resolve().parent / "hands_proxy.py"} {port + 100}
"""


def up(agent: str) -> dict:
    """Start the agent's desktop if it isn't running. Idempotent."""
    for tool in ("sway", "swaymsg", "wayvnc", "grim", "dbus-run-session"):
        if not shutil.which(tool):
            raise HandsError(f"missing {tool} (sudo pacman -S sway wayvnc grim)")
    if alive(agent):
        return status(agent)
    if is_laptop(agent):
        return _up_laptop()
    sd, hd = state_dir(agent), home_dir(agent)
    sd.mkdir(parents=True, exist_ok=True)
    hd.mkdir(parents=True, exist_ok=True)
    os.chmod(sd, 0o700)
    os.chmod(hd, 0o700)
    (sd / "session").unlink(missing_ok=True)
    _systemctl("reset-failed", unit(agent))
    port = _pick_port(agent)
    (sd / "port").write_text(str(port))
    (sd / "sway.conf").write_text(_sway_config(agent, port))
    env = {
        "WLR_BACKENDS": "headless", "WLR_LIBINPUT_NO_DEVICES": "1", "WLR_RENDERER": "pixman",
        "XDG_RUNTIME_DIR": str(RUNTIME), "XDG_CURRENT_DESKTOP": "sway",
        "HOME": str(Path.home()), "ASTRYX_HANDS_AGENT": agent,
        "HANDS_LOCAL_ALLOW": os.environ.get("HANDS_LOCAL_ALLOW") or "8006",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    cmd = ["systemd-run", "--user", f"--unit={unit(agent)}", "--collect",
           f"--description=astryx hands desktop for {agent}",
           "-p", "KillMode=control-group", "-p", "TimeoutStopSec=10",
           f"--working-directory={hd}"]
    for k, v in env.items():
        cmd += ["--setenv", f"{k}={v}"]
    # WAYLAND_DISPLAY/DISPLAY must be ABSENT: sway would nest into them instead of going headless
    cmd += ["--", "dbus-run-session", "--", "sway", "-c", str(sd / "sway.conf")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=_user_env())
    if r.returncode != 0:
        raise HandsError(f"could not start the desktop: {r.stderr.strip()[:300]}")
    deadline = time.time() + 15
    while time.time() < deadline:
        if _session(agent, required=False):
            break
        time.sleep(0.2)
    else:
        down(agent)
        raise HandsError("the desktop did not come up within 15s (journalctl --user -u "
                         f"{unit(agent)})")
    # wayvnc starts with the session, then the agent's seat connects to it. Return only when the
    # seat answers: the FIRST action on a fresh desktop raced it (a measured flake).
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            _seat(agent, {"op": "ping"})
            break
        except HandsError:
            time.sleep(0.2)
    else:
        raise HandsError(f"{agent}'s seat never answered (journalctl --user -u {unit(agent)})")
    return status(agent)


def _up_laptop() -> dict:
    """Attach to the owner's REAL screen: wayvnc on his Hyprland session (his focused monitor)
    and the agent's seat as its client. No new session, nothing launched on his desktop."""
    h = _hypr()
    if not h:
        raise HandsError("the owner's Hyprland session isn't running")
    sd = state_dir(LAPTOP)
    sd.mkdir(parents=True, exist_ok=True)
    os.chmod(sd, 0o700)
    _systemctl("reset-failed", unit(LAPTOP))
    port = _pick_port(LAPTOP)
    (sd / "port").write_text(str(port))
    out = _monitor()["name"]
    seat = Path(__file__).resolve().parent / "hands_seat.py"
    script = (f"wayvnc -r -o {out} -S {sd}/wayvnc.sock 127.0.0.1 {port} & "
              f"exec {sys.executable} {seat} {port} {sd}/seat.sock")
    cmd = ["systemd-run", "--user", f"--unit={unit(LAPTOP)}", "--collect",
           "--description=astryx hands on the owner's screen",
           "-p", "KillMode=control-group", "-p", "TimeoutStopSec=10"]
    for k, v in {**h, "XDG_RUNTIME_DIR": str(RUNTIME),
                 "PATH": os.environ.get("PATH", "/usr/bin:/bin")}.items():
        cmd += ["--setenv", f"{k}={v}"]
    cmd += ["--", "sh", "-c", script]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=_user_env())
    if r.returncode != 0:
        raise HandsError(f"could not attach to the owner's screen: {r.stderr.strip()[:300]}")
    for _ in range(50):
        if (sd / "seat.sock").exists():
            break
        time.sleep(0.2)
    else:
        down(LAPTOP)
        raise HandsError("couldn't attach to the owner's screen within 10s (journalctl --user "
                         f"-u {unit(LAPTOP)})")
    return status(LAPTOP)


def down(agent: str) -> bool:
    r = _systemctl("stop", unit(agent))
    for f in ("session", "seat.sock"):
        (state_dir(agent) / f).unlink(missing_ok=True)
    return r.returncode == 0


def stopped(agent: str) -> str | None:
    f = state_dir(agent) / "stopped"
    try:
        return f.read_text().strip() or "the owner stopped your hands"
    except FileNotFoundError:
        return None
    except OSError:          # unreadable is not "not stopped": fail closed (a3 #42085)
        return "the stop flag can't be read, so your hands are stopped"


def _append(path: Path, line: str, keep: int = 5000) -> None:
    """Append one line, keeping the last `keep`. Names and times only, never text."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(line.rstrip("\n") + "\n")
        if path.stat().st_size > keep * 120:
            lines = path.read_text().splitlines()[-keep:]
            path.write_text("\n".join(lines) + "\n")
    except OSError:
        pass


def stop(agent: str, why: str = "") -> None:
    sd = state_dir(agent)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "stopped").write_text(why or "the owner stopped your hands")
    _append(sd / "owner_log", f"{time.time():.3f} stop")


def resume(agent: str) -> None:
    (state_dir(agent) / "stopped").unlink(missing_ok=True)
    _append(state_dir(agent) / "owner_log", f"{time.time():.3f} resume")


def owner_log(agent: str) -> list[tuple[float, str]]:
    """This desktop's stop/resume history: [(ts, "stop"|"resume")]."""
    out = []
    try:
        for line in (state_dir(agent) / "owner_log").read_text().splitlines():
            ts, verb = line.split()[:2]
            out.append((float(ts), verb))
    except (OSError, ValueError):
        pass
    return out


def laptop_acts() -> list[tuple[float, str, str]]:
    """Every agent ACTION on the owner's real screen: [(ts, action name, agent)]. Never the action's text. A resume of
    a phone's desktop near one of these may have been clicked by that agent, not the owner (plan-8675 C2)."""
    out = []
    try:
        for line in (state_dir(LAPTOP) / "acts.log").read_text().splitlines():
            ts, act, who = (line.split() + ["?", "?"])[:3]
            out.append((float(ts), act, who))
    except (OSError, ValueError):
        pass
    return out


# ---- caps: a STEP cap and a WALL-TIME cap per agent session (plan-7862, seed's binding item #38260, #44137) ----
# Keyed by the AGENT (the resident), not the desktop: a pool desk is shared, and one agent's runaway loop must not stop
# another's work. A SESSION is a run of an agent's actions with no gap longer than CAP_IDLE_S; a new session starts
# fresh. A loop never idles, so a capped loop stays refused; an agent that pauses gets a fresh session. The caps
# protect the owner's time (and tokens), not a cage: the owner can reset an agent's session at any moment.
# Every tool call is a step (a look costs tokens too); a multi-step `do` charges its steps.
CAPS_DIR = STATE_ROOT / ".caps"            # a name the desktop list never shows (NAME_RE can't start with ".")


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None:
        try:
            for line in (repo_root(__file__) / ".env").read_text().splitlines():
                if line.startswith(f"{key}="):
                    v = line.split("=", 1)[1].strip()
        except OSError:
            pass
    try:
        n = int(v) if v not in (None, "") else default
        return n if n > 0 else default
    except ValueError:
        return default


def caps() -> dict:
    """The caps in force: .env (HANDS_STEP_CAP, HANDS_WALL_CAP_S, HANDS_CAP_IDLE_S, HANDS_DAY_STEP_CAP) over defaults."""
    return {"steps": _env_int("HANDS_STEP_CAP", 300), "wall_s": _env_int("HANDS_WALL_CAP_S", 3600),
            "idle_s": _env_int("HANDS_CAP_IDLE_S", 600), "day_steps": _env_int("HANDS_DAY_STEP_CAP", 2000)}


class Capped(HandsError):
    pass


def charge(agent: str, n: int = 1, now: float | None = None) -> dict:
    """Count `n` steps for `agent`'s session, or raise Capped naming the cap that's spent. Atomic per agent (a file
    lock: an agent's hands and phone servers share one count).

    A refused charge counts no STEPS, but it IS activity: it moves `last`, so an agent hammering at its cap is never
    "idle" and never earns a fresh session (a3 #47653 F1: refusals that didn't touch `last` let a loop that never
    paused come back every idle window, metered forever). Only true silence for HANDS_CAP_IDLE_S starts a session.
    A DAILY ceiling (per UTC date) bounds a loop that does pause past the idle window between bursts (a3 N2).
    GRADE: same-uid, like the stop flag. A resident with Bash can reset or delete its own count, so this guards
    against RUNAWAY LOOPS and accidents, not against an agent that means to get round it (owner ruling 10-09: agents
    are trusted)."""
    import fcntl
    if not agent:
        raise HandsError("no agent to charge: ASTRYX_AGENT is not set")
    c = caps()
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    CAPS_DIR.mkdir(parents=True, exist_ok=True)
    f = CAPS_DIR / f"{_name(agent)}.json"

    def save(st: dict) -> None:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(st))
        tmp.replace(f)

    with open(CAPS_DIR / f"{_name(agent)}.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            st = json.loads(f.read_text())
            assert isinstance(st.get("start"), (int, float)) and isinstance(st.get("steps"), int)
        except FileNotFoundError:
            st = None
        except (OSError, ValueError, AssertionError):
            # an unreadable count is not a fresh session: fail closed, like the stop flag (a3 #42085)
            raise Capped("your hands' step count can't be read, so they're stopped. Tell the owner "
                         f"(`src/astryx/hands/hands_desktop.py caps-reset {agent}` clears it).")
        if st is None:
            st = {"start": now, "last": now, "steps": 0}
        elif now - st.get("last", st["start"]) > c["idle_s"]:      # true silence: a fresh session, the day carries
            st = {**st, "start": now, "last": now, "steps": 0}
        if now < st["start"]:                                       # the clock stepped back: restart the wall clock
            st["start"] = now
        if st.get("day") != day:
            st["day"], st["day_steps"] = day, 0
        come_back = (f"They come back after {c['idle_s'] // 60} minutes with no calls at all, or when the owner "
                     f"resets them.")
        why = None
        if st["steps"] + n > c["steps"]:
            why = (f"your hands hit the STEP cap: {st['steps']} steps this session (cap {c['steps']}). "
                   f"Stop here and tell the owner where you were. {come_back}")
        elif now - st["start"] > c["wall_s"]:
            why = (f"your hands hit the WALL-TIME cap: this session is {int(now - st['start']) // 60} minutes old "
                   f"(cap {c['wall_s'] // 60}). Stop here and tell the owner where you were. {come_back}")
        elif st.get("day_steps", 0) + n > c["day_steps"]:
            why = (f"your hands hit the DAILY cap: {st.get('day_steps', 0)} steps today, UTC (cap {c['day_steps']}). "
                   f"Stop here and tell the owner where you were; they come back tomorrow (UTC) or when the owner "
                   f"resets them.")
        st["last"] = max(now, st.get("last", now))                  # a refusal is activity too (F1)
        if why:
            save(st)
            raise Capped(why)
        st["steps"] += n
        st["day_steps"] = st.get("day_steps", 0) + n
        save(st)
        return {**st, **{f"cap_{k}": v for k, v in c.items()}}


def caps_reset(agent: str) -> None:
    (CAPS_DIR / f"{_name(agent)}.json").unlink(missing_ok=True)


def session(agent: str) -> dict | None:
    """An agent's current cap session, for the observatory and status: {start, last, steps} or None."""
    try:
        return json.loads((CAPS_DIR / f"{_name(agent)}.json").read_text())
    except (OSError, ValueError):
        return None


# ---- the shared pool of background desktops (owner, 10-10) ----------------------------------
# "the private desktop should be common for all agents — if one agent is using it already then
# create a new one, but if it is free, the agent should use it." Desktops desk-1, desk-2, … are
# HELD by one agent at a time: a hold lasts while the agent acts and lapses after HOLD_IDLE_S
# without an action (or on release). desk-1 keeps the main browser profile, with the logins; a new
# desk starts from a COPY of it (cookies carry over; WhatsApp Web, one session per device, doesn't).
POOL_PREFIX = "desk-"
HOLD_IDLE_S = 300


def pool() -> list[str]:
    names = []
    if STATE_ROOT.exists():
        names += [d.name for d in STATE_ROOT.iterdir() if d.name.startswith(POOL_PREFIX)]
    if HOME_ROOT.exists():
        names += [d.name for d in HOME_ROOT.iterdir() if d.name.startswith(POOL_PREFIX)]
    return sorted(set(n for n in names if NAME_RE.match(n)), key=lambda n: int(n[len(POOL_PREFIX):])
                  if n[len(POOL_PREFIX):].isdigit() else 10**9)


def holder(desk: str) -> tuple[str, float] | None:
    """Who holds a desk, if the hold is live."""
    try:
        who, ts = (state_dir(desk) / "holder").read_text().split()
        ts = float(ts)
    except (OSError, ValueError):
        return None
    return (who, ts) if time.time() - ts < HOLD_IDLE_S else None


def _hold(desk: str, agent: str) -> None:
    state_dir(desk).mkdir(parents=True, exist_ok=True)
    (state_dir(desk) / "holder").write_text(f"{agent} {time.time():.0f}")


def acquire(agent: str) -> str:
    """The background desktop this agent works on: the one it holds, else the first free one,
    else a new one. The hold is refreshed by every action (_guard)."""
    import fcntl
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with open(STATE_ROOT / ".pool.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        desks = pool()
        mine = next((d for d in desks if (holder(d) or ("",))[0] == agent), None)
        free = next((d for d in desks if holder(d) is None), None)
        desk = mine or free
        if desk is None:
            n = 1 + max([int(d[len(POOL_PREFIX):]) for d in desks
                         if d[len(POOL_PREFIX):].isdigit()] or [0])
            desk = f"{POOL_PREFIX}{n}"
        _hold(desk, agent)
    if not alive(desk):
        _seed_profile(desk)
        up(desk)
    return desk


def release(agent: str) -> list[str]:
    out = []
    for d in pool():
        h = holder(d)
        if h and h[0] == agent:
            (state_dir(d) / "holder").unlink(missing_ok=True)
            out.append(d)
    return out


def _seed_profile(desk: str) -> None:
    """A new desk starts from a copy of desk-1's browser profile (its logins), once."""
    first = home_dir(f"{POOL_PREFIX}1") / "browser"
    mine = home_dir(desk) / "browser"
    if desk == f"{POOL_PREFIX}1" or mine.exists() or not first.is_dir():
        return
    home_dir(desk).mkdir(parents=True, exist_ok=True)
    shutil.copytree(first, mine, symlinks=True, ignore_dangling_symlinks=True,
                    ignore=shutil.ignore_patterns("Singleton*", "lockfile", "*.lock", "Crash*"))


def status(agent: str | None = None) -> dict | list:
    if agent is None:
        names = sorted(d.name for d in STATE_ROOT.iterdir()) if STATE_ROOT.exists() else []
        return [status(n) for n in names if NAME_RE.match(n)]
    sd = state_dir(agent)
    port = None
    try:
        port = int((sd / "port").read_text())
    except (OSError, ValueError):
        pass
    live = alive(agent)
    la = last_act(agent)
    out = {"agent": agent, "running": live, "vnc_port": port if live else None,
           "stopped": stopped(agent), "size": list(size(agent)) if live else [WIDTH, HEIGHT],
           "kind": "laptop" if is_laptop(agent) else "pool" if agent.startswith(POOL_PREFIX)
           else "own",
           "holder": (holder(agent) or (None,))[0] if agent.startswith(POOL_PREFIX) else None,
           "last_act": {"ts": la[0], "action": la[1], "by": la[2]} if la else None}
    if live:
        try:
            out["windows"] = windows(agent)
        except HandsError:
            out["windows"] = []
    return out


# ---- the senses and the hands ----------------------------------------------------------

def _env(agent: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY",
                                                           "SWAYSOCK", "I3SOCK")}
    env.update(_session(agent))
    env["XDG_RUNTIME_DIR"] = str(RUNTIME)
    return env


# What a signal death means for the tools run here. grim takes the frame through a SHARED-MEMORY buffer: SIGBUS is
# that buffer's page failing to fault in (host memory or /dev/shm exhausted), measured 10-12 on desk-1 (rc -7, empty
# stderr, canopus #50568) while the host was over its commit limit.
_SIGNAL_HINT = {"SIGBUS": "a shared-memory page couldn't be backed: host memory or /dev/shm is exhausted",
                "SIGKILL": "killed, often by the OOM killer: host memory is exhausted",
                "SIGSEGV": "it crashed"}


def _failure(argv0: str, rc: int, stderr: bytes) -> str:
    """The error for a failed tool: its exit code or signal ALWAYS, then stderr. A signal death leaves stderr empty,
    and "grim failed: " with nothing after it is undiagnosable."""
    import signal
    if rc < 0:
        try:
            name = signal.Signals(-rc).name
        except ValueError:
            name = f"signal {-rc}"
        how = f"killed by {name}" + (f" ({_SIGNAL_HINT[name]})" if name in _SIGNAL_HINT else "")
    else:
        how = f"exit {rc}"
    err = stderr.decode(errors="replace").strip()[:300]
    return f"{argv0} failed: {how}" + (f": {err}" if err else ", no stderr")


def _run(agent: str, argv: list[str], timeout: float = 20, inp: bytes | None = None) -> bytes:
    r = subprocess.run(argv, env=_env(agent), capture_output=True, timeout=timeout, input=inp)
    if r.returncode != 0:
        raise HandsError(_failure(argv[0], r.returncode, r.stderr))
    return r.stdout


def _sway(agent: str, command: str) -> list:
    out = _run(agent, ["swaymsg", "--raw", command])
    res = json.loads(out or b"[]")
    bad = [r.get("error") for r in res if isinstance(r, dict) and not r.get("success", True)]
    if bad:
        raise HandsError(f"sway refused {command!r}: {bad[0]}")
    return res


def _guard(agent: str, act: str = "") -> None:
    why = stopped(agent)
    if why:
        raise Stopped(why)
    _session(agent)
    who = os.environ.get("ASTRYX_AGENT", "")
    if act and who and agent.startswith(POOL_PREFIX):
        _hold(agent, who)
    if act:          # who did what last, and when: the action's NAME only, never its text
        try:
            (state_dir(agent) / "last_act").write_text(
                f"{time.time():.0f} {act} {os.environ.get('ASTRYX_AGENT', '') or agent}")
        except OSError:
            pass
        if is_laptop(agent):            # a history for the laptop only: the owner's screen (plan-8675 C2)
            _append(state_dir(agent) / "acts.log",
                    f"{time.time():.3f} {act} {os.environ.get('ASTRYX_AGENT', '') or '?'}")


def last_act(agent: str) -> tuple[float, str, str] | None:
    try:
        ts, act, *who = (state_dir(agent) / "last_act").read_text().split()
        return float(ts), act, (who[0] if who else agent)
    except (OSError, ValueError):
        return None


VIEW_W = 960              # the agent's view is at most 960 px wide (960×600 = ~770 image tokens
                          # vs ~1700 full size); its pixels are the agent's coordinates


def view_scale(agent: str) -> float:
    return max(1.0, size(agent)[0] / VIEW_W)


def _output_args(agent: str) -> list[str]:
    return ["-o", _monitor()["name"]] if is_laptop(agent) else []


def screenshot(agent: str, quality: int = 70, region: tuple[int, int, int, int] | None = None,
               full: bool = False) -> bytes:
    """A JPEG of the desktop. Default: scaled to the VIEW (≤960 wide), whose pixels are the
    agent's coordinates. region=(x, y, w, h) in VIEW pixels returns that part at full
    resolution, to read small text without paying for a full-size image."""
    _session(agent)
    w, h = size(agent)
    sc = view_scale(agent)
    argv = ["grim", "-t", "jpeg", "-q", str(quality)]
    if region:
        x, y, rw, rh = (int(round(v * sc)) for v in region)
        if is_laptop(agent):
            m = _monitor()
            x, y = x + m.get("x", 0), y + m.get("y", 0)
        x, y = max(0, x), max(0, y)
        argv += ["-g", f"{x},{y} {max(1, min(w, rw))}x{max(1, min(h, rh))}"]
    else:
        argv += _output_args(agent)
        if not full and sc > 1:
            argv += ["-s", f"{1 / sc:.4f}"]
    return _run(agent, argv + ["-"])


def fingerprint(agent: str) -> str:
    """A cheap digest of what's on screen (a tiny grayscale-ish capture), to wait for change."""
    import hashlib
    argv = ["grim", "-t", "ppm", *_output_args(agent), "-s", "0.0625", "-"]
    return hashlib.sha1(_run(agent, argv)).hexdigest()


def wait_change(agent: str, timeout: float, settle: float = 0.6) -> bool:
    """Block until the screen changes (then let it settle), or timeout. True if it changed."""
    end = time.time() + timeout
    base = fingerprint(agent)
    while time.time() < end:
        time.sleep(0.35)
        if fingerprint(agent) != base:
            time.sleep(settle)
            return True
    return False


def view_to_desktop(agent: str, x: float, y: float) -> tuple[int, int]:
    sc = view_scale(agent)
    return int(round(x * sc)), int(round(y * sc))


def _clamp(x: int, y: int, agent: str = "") -> tuple[int, int]:
    w, h = size(agent) if agent else (WIDTH, HEIGHT)
    return max(0, min(w - 1, int(x))), max(0, min(h - 1, int(y)))


# ---- input: the agent's own seat (src/astryx/hands/hands_seat.py, a VNC participant) -----------

def _seat(agent: str, *msgs: dict) -> None:
    path = str(state_dir(agent) / "seat.sock")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(path)
            f = s.makefile("rwb")
            for m in msgs:
                f.write((json.dumps(m) + "\n").encode())
            f.flush()
            for _ in msgs:
                r = json.loads(f.readline() or b'{"ok": false, "error": "no reply"}')
                if not r.get("ok"):
                    raise HandsError(f"seat: {r.get('error')}")
    except OSError as e:
        raise HandsError(f"{agent}'s seat is not answering ({e}); hands down + up restarts it")


_pos: dict[str, tuple[int, int]] = {}
BUTTONS = {"left": 1, "middle": 2, "right": 4}


def _ptr(agent: str, x: int, y: int, mask: int = 0) -> dict:
    _pos[agent] = (x, y)
    return {"op": "pointer", "x": x, "y": y, "mask": mask}


def move(agent: str, x: int, y: int) -> None:
    _guard(agent, "move")
    _seat(agent, _ptr(agent, *_clamp(x, y, agent)))


def click(agent: str, x: int, y: int, button: str = "left", count: int = 1) -> None:
    _guard(agent, "click")
    b = BUTTONS.get(button)
    if not b:
        raise HandsError(f"button must be one of {sorted(BUTTONS)}")
    x, y = _clamp(x, y, agent)
    msgs = [_ptr(agent, x, y)]
    for _ in range(max(1, min(3, int(count)))):
        msgs += [_ptr(agent, x, y, b), _ptr(agent, x, y)]
    _seat(agent, *msgs)


def drag(agent: str, x1: int, y1: int, x2: int, y2: int) -> None:
    _guard(agent, "drag")
    x1, y1 = _clamp(x1, y1, agent)
    x2, y2 = _clamp(x2, y2, agent)
    steps = 10
    msgs = [_ptr(agent, x1, y1), _ptr(agent, x1, y1, 1)]
    msgs += [_ptr(agent, x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps, 1)
             for i in range(1, steps + 1)]
    msgs.append(_ptr(agent, x2, y2))
    _seat(agent, *msgs)


def scroll(agent: str, x: int, y: int, dy: int) -> None:
    """dy > 0 scrolls down, < 0 up; one unit is one wheel notch."""
    _guard(agent, "scroll")
    x, y = _clamp(x, y, agent)
    b = 16 if dy > 0 else 8
    msgs = [_ptr(agent, x, y)]
    for _ in range(max(1, min(30, abs(int(dy))))):
        msgs += [_ptr(agent, x, y, b), _ptr(agent, x, y)]
    _seat(agent, *msgs)


KEYSYMS = {"Return": 0xff0d, "Escape": 0xff1b, "Tab": 0xff09, "BackSpace": 0xff08,
           "Delete": 0xffff, "Home": 0xff50, "Left": 0xff51, "Up": 0xff52, "Right": 0xff53,
           "Down": 0xff54, "Prior": 0xff55, "Next": 0xff56, "End": 0xff57, "Insert": 0xff63,
           "space": 0x20, "Menu": 0xff67, "Print": 0xff61,
           **{f"F{i}": 0xffbe + i - 1 for i in range(1, 13)}}
MODS = {"ctrl": 0xffe3, "control": 0xffe3, "shift": 0xffe1, "alt": 0xffe9,
        "super": 0xffeb, "meta": 0xffeb, "win": 0xffeb, "cmd": 0xffeb, "logo": 0xffeb}
KEY_ALIASES = {"enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
               "tab": "Tab", "backspace": "BackSpace", "delete": "Delete", "del": "Delete",
               "space": "space", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
               "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
               "insert": "Insert", "menu": "Menu",
               # punctuation by name ("+" splits a chord, so "ctrl+minus", not "ctrl+-")
               "minus": "-", "plus": "+", "equal": "=", "comma": ",", "period": ".",
               "slash": "/", "backslash": "\\", "semicolon": ";", "apostrophe": "'",
               "grave": "`", "bracketleft": "[", "bracketright": "]"}


def _sym(ch: str) -> int:
    if ch == "\n":
        return KEYSYMS["Return"]
    if ch == "\t":
        return KEYSYMS["Tab"]
    o = ord(ch)
    return o if 0x20 <= o <= 0x7e or 0xa0 <= o <= 0xff else 0x01000000 | o


def _tap(sym: int) -> list[dict]:
    return [{"op": "key", "keysym": sym, "down": True},
            {"op": "key", "keysym": sym, "down": False}]


def type_text(agent: str, text: str) -> None:
    _guard(agent, "type_text")
    for i in range(0, len(text), 64):              # small batches keep a long text interruptible
        if i:
            _guard(agent)
        msgs = []
        for ch in text[i:i + 64]:
            msgs += _tap(_sym(ch))
        _seat(agent, *msgs)


def key(agent: str, combo: str) -> None:
    """One chord, e.g. "ctrl+l", "Return", "ctrl+shift+t", "F5"."""
    _guard(agent, "key")
    parts = [p for p in combo.replace(" ", "").split("+") if p]
    if not parts:
        raise HandsError("empty key")
    *mods, k = parts
    held = []
    for m in mods:
        sym = MODS.get(m.lower())
        if sym is None:
            raise HandsError(f"unknown modifier {m!r}")
        held.append(sym)
    k = KEY_ALIASES.get(k.lower(), k)
    if k in KEYSYMS:
        sym = KEYSYMS[k]
    elif len(k) == 1:
        sym = _sym(k.lower() if held else k)
    else:
        raise HandsError(f"unknown key {k!r}")
    msgs = [{"op": "key", "keysym": m, "down": True} for m in held]
    msgs += _tap(sym)
    msgs += [{"op": "key", "keysym": m, "down": False} for m in reversed(held)]
    _seat(agent, *msgs)


def windows(agent: str) -> list[dict]:
    if is_laptop(agent):
        out = []
        for c in json.loads(_hyprctl("-j", "clients") or "[]"):
            if not c.get("mapped") or c.get("hidden"):
                continue
            out.append({"id": int(c["address"], 16), "app": c.get("class", ""),
                         "title": (c.get("title") or "")[:200],
                         "focused": c.get("focusHistoryID") == 0,
                         "workspace": (c.get("workspace") or {}).get("name"),
                         "rect": [*c.get("at", [0, 0]), *c.get("size", [0, 0])]})
        return out
    tree = json.loads(_run(agent, ["swaymsg", "-t", "get_tree", "--raw"]))
    out: list[dict] = []

    def walk(n):
        if n.get("pid") and n.get("type") in ("con", "floating_con"):
            r = n.get("rect") or {}
            out.append({"id": n["id"], "app": n.get("app_id") or
                        (n.get("window_properties") or {}).get("class") or "",
                        "title": (n.get("name") or "")[:200], "focused": n.get("focused", False),
                        "rect": [r.get("x"), r.get("y"), r.get("width"), r.get("height")]})
        for c in n.get("nodes", []) + n.get("floating_nodes", []):
            walk(c)
    walk(tree)
    return out


def focus(agent: str, window_id: int) -> None:
    _guard(agent, "focus")
    if is_laptop(agent):
        addr = f"address:0x{int(window_id):x}"
        _hdispatch(f'hl.dsp.focus({{window="{addr}"}})', ("focuswindow", addr))
        return
    _sway(agent, f"[con_id={int(window_id)}] focus")


# The agent's OWN browser goes out only through src/astryx/hands/hands_proxy.py, which refuses loopback and
# private addresses (a3 #42085 F1). Its port sits beside the VNC port.
def proxy_port(agent: str) -> int:
    return int((state_dir(agent) / "port").read_text()) + 100


def browser_argv(agent: str, url: str = "") -> list[str]:
    exe = shutil.which("chromium") or shutil.which("google-chrome-stable") or "chromium"
    argv = [exe, f"--user-data-dir={home_dir(agent) / 'browser'}", "--ozone-platform=wayland",
            "--no-first-run", "--no-default-browser-check", "--password-store=basic",
            "--disable-features=TranslateUI", "--hide-crash-restore-bubble",
            f"--proxy-server=http://127.0.0.1:{proxy_port(agent)}",
            "--proxy-bypass-list=<-loopback>",
            f"--window-size={WIDTH},{HEIGHT}"]
    if url:
        argv.append(url)
    return argv


# ---- the Windows VM, on demand (plan-8675 C5, a4 #42255 / #48958) -------------------------------------------------
# Opening the Windows VM's viewer (127.0.0.1:<HANDS_WINDOWS_PORT>, the port the proxy already allows) first HOLDS the
# vm-slot for "windows" (the same atomic claim the phone uses: the phone and Windows measured not to fit in RAM
# together), then starts the container if it's stopped. If the phone holds the slot, the open is refused, naming it.
# A start made HERE is recorded (WINDOWS_STARTED): only such a run is ever stopped for being idle
# (src/astryx/pulse/shipped_triggers/windows_idle_stop.py). A VM that was already running is held, never auto-stopped.
WINDOWS_PORT = int(os.environ.get("HANDS_WINDOWS_PORT") or 8006)
WINDOWS_STARTED = STATE_ROOT / ".windows_started"


def is_windows_viewer(what: str) -> bool:
    m = re.match(r"^(?:https?://)?(?:127\.0\.0\.1|localhost):(\d+)(?:[/?#]|$)", (what or "").strip())
    return bool(m) and int(m.group(1)) == WINDOWS_PORT


def windows_up(agent: str) -> bool:
    """Hold the vm-slot for Windows and start its container if it's stopped. True iff THIS call started it."""
    from astryx.hands import android
    try:
        android.claim_slot("windows")
    except android.AndroidError as e:
        raise HandsError(f"can't open the Windows VM: {e}")
    if android.windows_running():
        return False
    r = subprocess.run(["docker", "start", android.WINDOWS_CONTAINER], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        android.free_slot("windows")
        raise HandsError(f"the Windows VM wouldn't start: {(r.stderr or r.stdout).strip()[:200]}")
    # The record is bound to THIS run by the container's own start identity: a later run (the owner's restart, or a
    # host reboot bringing the container back by its restart policy) has another StartedAt, and is never taken for
    # ours (a4 #49102).
    started_at = container_started_at(android.WINDOWS_CONTAINER)
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        WINDOWS_STARTED.write_text(json.dumps({"ts": time.time(), "by": os.environ.get("ASTRYX_AGENT", "") or agent,
                                               "container": android.WINDOWS_CONTAINER, "started_at": started_at}))
    except OSError:
        pass
    return True


def container_started_at(name: str) -> str | None:
    """The container's own start identity (docker's State.StartedAt), or None if docker can't say."""
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", name], capture_output=True, text=True,
                           timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def open_(agent: str, what: str) -> None:
    """A URL opens in the agent's browser (its own, persistent profile); anything else is run as
    a program inside the agent's desktop (e.g. "libreoffice --calc", "nautilus", "foot")."""
    _guard(agent, "open")
    what = (what or "").strip()
    if not what:
        raise HandsError("open what?")
    if is_windows_viewer(what):
        windows_up(agent)
    is_url = re.match(r"^(https?|file)://", what) or re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", what)
    if is_laptop(agent):
        # on his screen, in HIS browser and apps: a URL opens as a tab in his own browser
        cmd = "xdg-open " + _q(what if not is_url or "://" in what else f"https://{what}") \
            if is_url else what
        _hdispatch(f"hl.dsp.exec_cmd({_lua_str(cmd)})", ("exec", cmd))
        return
    if is_url:
        url = what if "://" in what else f"https://{what}"
        argv = browser_argv(agent, url)
    elif what in ("browser", "chromium", "chrome"):
        argv = browser_argv(agent)
    else:
        argv = ["sh", "-c", what]
    # launched by sway's exec, so it joins the agent's session: its D-Bus, its display
    _sway(agent, "exec " + " ".join(_q(a) for a in argv))


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def settle() -> None:
    time.sleep(SETTLE_S)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "up":
            print(json.dumps(up(rest[0])))
        elif cmd == "down":
            print("stopped" if down(rest[0]) else "not running")
        elif cmd == "status":
            print(json.dumps(status(rest[0] if rest else None), indent=1))
        elif cmd == "shot":
            Path(rest[1]).write_bytes(screenshot(rest[0]))
            print(rest[1])
        elif cmd == "stop":
            stop(rest[0], " ".join(rest[1:]))
        elif cmd == "resume":
            resume(rest[0])
        elif cmd == "caps-reset":
            caps_reset(rest[0])
            print(f"{rest[0]}: a fresh session (caps {caps()})")
        else:
            print(f"unknown command {cmd}", file=sys.stderr)
            return 2
    except HandsError as e:
        print(f"hands: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
