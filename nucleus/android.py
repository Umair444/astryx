#!/usr/bin/env python3
"""astryx · android — the phone under an agent's hands (plan-8675): an Android emulator (AVD) on this machine.

Opt-in (ANDROID_ENABLED=1 in .env; nucleus/android_setup.sh installs it user-locally). Agents drive it through
mcp/phone (two tools, the same shape as hands). This module is the device layer under that facade:

  boot(avd, agent)      start the AVD headless, AFTER an atomic hold of 'vm-slot' (the Android emulator and the
                        Windows VM measured not to fit in RAM together, S0 #42371). Refused while another VM holds
                        the slot, naming the holder.
  shutdown(avd)         stop it and free 'vm-slot'
  serial(avd)           the emulator serial (emulator-5554…) running that AVD, or None
  drive(avd, agent)     hold 'android:<avd>': ONE agent drives a phone at a time (a4 #42240 C4). Refused, naming
                        the holder, while another agent's hold is live. Each action refreshes it; idle, it lapses.
  release(avd, agent)   give the phone back
  surface(serial)       {tier, packages, unlisted}: which windows are visible, classified by mcp/phone's public
                        manifest (C3)

The owner's STOP is Hands' own stop flag (nucleus/hands_desktop.stopped): one stop covers an agent's desktop and
its phone. Nothing here stores screen content.

    venv/bin/python nucleus/android.py status
    venv/bin/python nucleus/android.py boot <avd> <agent>
    venv/bin/python nucleus/android.py shutdown <avd>
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "mcp" / "phone"))
from nucleus import ear_lease as L  # noqa: E402
import surface as _surface  # noqa: E402

VM_SLOT = "vm-slot"
DRIVE_TTL_S = 300               # a driver's hold lapses 5 minutes after its last action (like a pool desk)
SLOT_TTL_S = 6 * 3600           # the VM slot is renewed by every action; a crashed VM is detected, not waited out
BOOT_MAX_S = 600                # a cold boot measured 214–486 s on a 2-core laptop (S0); quickboot 9 s
WINDOWS_CONTAINER = os.environ.get("WINDOWS_CONTAINER") or "windows"


class AndroidError(Exception):
    pass


def _env_file() -> dict:
    out = {}
    try:
        for line in (REPO / ".env").read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def sdk() -> Path:
    """ANDROID_SDK_ROOT (env, then .env), else the per-user default the setup installs to."""
    v = os.environ.get("ANDROID_SDK_ROOT") or _env_file().get("ANDROID_SDK_ROOT")
    return Path(v).expanduser() if v else Path.home() / "Android" / "Sdk"


def default_avd() -> str:
    return os.environ.get("ANDROID_AVD") or _env_file().get("ANDROID_AVD") or "astryx-phone"


def adb(*args: str, timeout: float = 30, serial: str | None = None) -> subprocess.CompletedProcess:
    """adb, bounded. A phone that doesn't answer in time raises AndroidError (callers handle that one type): a slow
    emulator just after boot, under a loaded host, measured >20 s for a `settings put`."""
    cmd = [str(sdk() / "platform-tools" / "adb"), *(["-s", serial] if serial else []), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AndroidError(f"the phone didn't answer `adb {' '.join(args[:3])}` within {timeout:.0f}s")


def _db():
    import psycopg
    dsn = os.environ.get("ANDROID_DSN") or _env_file().get("ASTRYX_DSN")
    if not dsn:
        raise AndroidError("no database: ASTRYX_DSN is not set")
    return psycopg.connect(dsn, autocommit=True)


# ---- which VM is resident ------------------------------------------------------------------------------------

def emulator_pids(avd: str) -> list[int]:
    """The emulator processes running `avd`, read from /proc (never `pgrep -f`, which matches its own caller)."""
    pids = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            argv = (p / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if argv and b"qemu-system" in argv[0] and b"-avd" in argv and \
                argv[argv.index(b"-avd") + 1:argv.index(b"-avd") + 2] == [avd.encode()]:
            pids.append(int(p.name))
    return pids


def windows_running() -> bool:
    r = subprocess.run(["docker", "inspect", "--format", "{{.State.Running}}", WINDOWS_CONTAINER],
                       capture_output=True, text=True, timeout=20)
    return r.returncode == 0 and r.stdout.strip() == "true"


def _vm_alive(holder: str) -> bool:
    """Is the VM named by a vm-slot holder actually resident? 'android:<avd>' or 'windows'."""
    if holder.startswith("android:"):
        return bool(emulator_pids(holder.split(":", 1)[1]))
    if holder == "windows":
        return windows_running()
    return True                                  # an unknown holder is never presumed gone


def claim_slot(holder: str) -> None:
    """Hold 'vm-slot' for `holder` or raise, naming who has it. A hold whose VM is PROVED gone (its process or
    container isn't running) is freed first: a crashed emulator must not lock the slot for SLOT_TTL_S."""
    with _db() as c:
        row = L.get(c, VM_SLOT)
        if row and row["state"] == "HELD" and row["holder"] != holder and not _vm_alive(row["holder"]):
            L.unhold(c, VM_SLOT, row["holder"])
        got = L.hold(c, VM_SLOT, holder, SLOT_TTL_S)
        if got is None:
            row = L.get(c, VM_SLOT)
            raise AndroidError(f"the VM slot is held by {row['holder'] if row else '?'}: the Android emulator and "
                               f"the Windows VM don't fit in this machine's RAM together")


def free_slot(holder: str) -> None:
    with _db() as c:
        L.unhold(c, VM_SLOT, holder)


# ---- the device ----------------------------------------------------------------------------------------------

def serial(avd: str) -> str | None:
    r = adb("devices", timeout=20)
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and parts[0].startswith("emulator-"):
            name = adb("emu", "avd", "name", serial=parts[0], timeout=10).stdout.splitlines()
            if name and name[0].strip() == avd:
                return parts[0]
    return None


def booted(s: str) -> bool:
    return adb("shell", "getprop", "sys.boot_completed", serial=s, timeout=10).stdout.strip() == "1"


def boot(avd: str, agent: str) -> str:
    """Start `avd` headless if it isn't running, holding the VM slot first. Returns its serial when booted."""
    if not (sdk() / "emulator" / "emulator").exists():
        raise AndroidError(f"no Android emulator at {sdk()}: run nucleus/android_setup.sh (ANDROID_ENABLED=1)")
    holder = f"android:{avd}"
    if windows_running():
        raise AndroidError("the Windows VM is running: the Android emulator and the Windows VM don't fit in this "
                           "machine's RAM together. Stop it first, or ask the owner.")
    claim_slot(holder)
    if not emulator_pids(avd):
        log = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / f"astryx-android-{avd}.log"
        subprocess.Popen([str(sdk() / "emulator" / "emulator"), "-avd", avd, "-no-window", "-no-audio",
                          "-gpu", "swiftshader_indirect", "-no-boot-anim"],
                         stdout=open(log, "ab"), stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < BOOT_MAX_S:
        s = serial(avd)
        if s and booted(s):
            return s
        time.sleep(3)
    raise AndroidError(f"{avd} didn't finish booting in {BOOT_MAX_S}s")


# Notifications must not render a PERSONAL app's text over a public one (a4 #42240 C3's belt): no heads-up pop-ups,
# no notification content on the lock screen. Re-applied on every boot (three cheap calls), so a phone made anywhere
# gets them, and a changed setting comes back.
QUIET = (("global", "heads_up_notifications_enabled", "0"),
         ("secure", "lock_screen_show_notifications", "0"),
         ("secure", "lock_screen_allow_private_notifications", "0"),
         # Awake while running: a phone agents drive must not doze between their actions (measured: the display
         # slept, every window went invisible, and a dozing phone answers nothing useful). 7 = on AC/USB/wireless.
         ("global", "stay_on_while_plugged_in", "7"))


def harden(avd: str, s: str, patience_s: float = 180) -> list[str]:
    """Apply QUIET and owner-only file modes. Returns the settings it could NOT apply (empty = all applied). A phone
    just booted can be too slow to answer for a while, so each setting is retried until `patience_s` runs out."""
    missed = []
    deadline = time.time() + patience_s
    for ns, key, val in QUIET:
        while True:
            try:
                adb("shell", "settings", "put", ns, key, val, serial=s, timeout=30)
                if adb("shell", "settings", "get", ns, key, serial=s, timeout=30).stdout.strip() == val:
                    break
            except AndroidError:
                pass
            if time.time() > deadline:
                missed.append(key)
                break
            time.sleep(5)
    for cmd in (("input", "keyevent", "KEYCODE_WAKEUP"), ("wm", "dismiss-keyguard")):
        try:
            adb("shell", *cmd, serial=s, timeout=30)
        except AndroidError:
            pass
    # The phone's data (its userdata image, its snapshots) holds app sessions: the emulator creates them readable by
    # everyone (S0: userdata-qemu.img.qcow2 0644, snapshots/ 0755). Owner-only, re-asserted every boot (a1 A7).
    home = Path(os.environ.get("ANDROID_AVD_HOME") or Path.home() / ".android" / "avd") / f"{avd}.avd"
    for p in [home, *home.rglob("*")]:
        try:
            p.chmod(0o700 if p.is_dir() else 0o600)
        except OSError:
            pass
    return missed


def shutdown(avd: str) -> bool:
    s = serial(avd)
    if s:
        adb("emu", "kill", serial=s, timeout=20)
    for _ in range(60):
        if not emulator_pids(avd):
            break
        time.sleep(1)
    gone = not emulator_pids(avd)
    if gone:
        free_slot(f"android:{avd}")
        with _db() as c:                         # nobody drives a phone that isn't there
            row = L.get(c, f"android:{avd}")
            if row and row["state"] == "HELD":
                L.unhold(c, f"android:{avd}", row["holder"])
    return gone


def drive(avd: str, agent: str) -> None:
    """Hold 'android:<avd>' for `agent` (and renew the VM slot), or raise naming the agent that has it."""
    with _db() as c:
        if L.hold(c, f"android:{avd}", agent, DRIVE_TTL_S) is None:
            row = L.get(c, f"android:{avd}")
            raise AndroidError(f"{avd} is being driven by {row['holder'] if row else '?'}; one agent drives a "
                               f"phone at a time (its hold lapses {DRIVE_TTL_S // 60} minutes after its last action)")
        L.hold(c, VM_SLOT, f"android:{avd}", SLOT_TTL_S)


def release(avd: str, agent: str) -> None:
    with _db() as c:
        L.unhold(c, f"android:{avd}", agent)


def surface(s: str) -> dict:
    """C3: the visible windows, classified. If the window list can't be read, the surface is PERSONAL."""
    try:
        r = adb("shell", "dumpsys", "window", "windows", serial=s, timeout=20)
        if r.returncode != 0 or "Window #" not in r.stdout:
            raise AndroidError("no window list")
        return _surface.classify(_surface.windows(r.stdout))
    except Exception as e:  # noqa: BLE001 — an unreadable surface is never called public (a1 BC-2)
        return {"tier": "personal", "packages": [], "unlisted": [f"unreadable: {type(e).__name__}"]}


def status() -> dict:
    avd = default_avd()
    out = {"sdk": str(sdk()), "installed": (sdk() / "emulator" / "emulator").exists(), "avd": avd,
           "kvm": os.access("/dev/kvm", os.R_OK | os.W_OK), "running": bool(emulator_pids(avd))}
    try:
        with _db() as c:
            out["vm_slot"] = (L.get(c, VM_SLOT) or {}).get("holder")
            out["driver"] = (L.get(c, f"android:{avd}") or {}).get("holder")
    except Exception as e:  # noqa: BLE001
        out["db"] = f"unreachable ({type(e).__name__})"
    return out


if __name__ == "__main__":
    import json
    cmd, rest = (sys.argv[1] if len(sys.argv) > 1 else "status"), sys.argv[2:]
    try:
        if cmd == "status":
            print(json.dumps(status(), indent=1, default=str))
        elif cmd == "boot":
            print(boot(rest[0] if rest else default_avd(), rest[1] if len(rest) > 1 else "owner"))
        elif cmd == "shutdown":
            print("stopped" if shutdown(rest[0] if rest else default_avd()) else "still running")
        else:
            sys.exit(f"unknown command {cmd!r}")
    except AndroidError as e:
        sys.exit(f"refused: {e}")
