#!/usr/bin/env python3
"""Oracle: the phone facade (plan-8675 S1: mcp/phone, nucleus/android.py, hooks/step.py's phone strip, the HELD lease).
No phone needed: the device-driving arms are tests/test_android_device.py.

  CENSUS     the pinned upstream's LIVE tools/list equals the 33 names below, written out here from upstream 1.0.9's
             own list (not read from the facade): an upgrade that adds or renames a tool goes RED, never silently wider.
  ALLOWLIST  every facade verb maps to a live upstream tool; none of the DENIED tools (spend, pixels or logs to files,
             clipboard, installs, batch scripts…) is reachable, and naming one is refused before any process starts.
  TELEMETRY  the upstream process the facade REALLY spawns has MOBILEMCP_DISABLE_TELEMETRY=1 in /proc/<pid>/environ,
             and inherits nothing else: no ASTRYX_DSN, no ASTRYX_AGENT (control: a variable set in OUR env is absent).
  SURFACE    window-list fixtures: Settings + system decor → org; the notification shade open → personal; an unknown
             window → personal; nothing visible → personal; an unreadable list → personal.
  RACE       surface.combine: the stamp is org only if the readings BEFORE and AFTER the upstream call are both org and
             no element id in the text names an unlisted package (the probe measured content and stamp disagreeing)
  STRIP      step.py over a synthetic transcript: a phone result is kept only under an "org" stamp in its LAST block;
             a personal stamp, no stamp, a forged stamp inside the body, or a string body are not kept; typed phone
             text is never kept; images never; the hands laptop rule is unchanged (control).
  CAPS       one per-agent budget across hands and the phone: desktop steps and phone steps spend the same cap; a
             capped look, tap or boot answers CAPPED (personal stamp) and never reaches the phone; phones/done are free;
             SHUTDOWN is free and works for a capped or stopped agent (driver-only), while a stopped agent can't boot
  LEASE      on a fixture DB: HELD is accepted by the migrated schema, one holder at a time, renewal by the holder,
             an expired hold is taken, unhold only by its holder, a microphone lease can't be held, and a vm-slot hold
             whose VM is proved gone is freed for the next claimant while a live one refuses, naming the holder.
Exit 77 (after running every other arm) if node or the pinned upstream isn't installed, or there's no fixture DB.
"""
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "mcp" / "phone"))
UPSTREAM = REPO / "mcp/phone/upstream/node_modules/@mobilenext/mobile-mcp/lib/index.js"
fails, skipped = [], []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


try:                       # the MCP SDK (the facade's runtime). Without it this interpreter isn't the org's venv: under a
    from mcp import ClientSession  # noqa: F401  bare python3 `import mcp` even resolves to the repo's own mcp/ dir.
except ImportError as e:
    print(f"SKIP: the MCP SDK isn't importable here ({e}): run with the org's venv. Nothing was verified here.")
    sys.exit(77)

# The upstream is installed only where an org opted in (android_setup.sh). Without it, the arms that need a live
# upstream process (CENSUS, the live half of ALLOWLIST, TELEMETRY) are UNVERIFIED; every other arm still runs.
HAVE_UPSTREAM = bool(shutil.which("node")) and UPSTREAM.exists()

os.environ["ASTRYX_AGENT"] = "phone-oracle"
import tempfile  # noqa: E402
os.environ["ASTRYX_HANDS_STATE"] = tempfile.mkdtemp(prefix="phone-oracle-hands-")   # caps + stop flags, never the org's
os.environ["ORACLE_CANARY_ENV"] = "must-not-reach-upstream"
import importlib.util  # noqa: E402
import nucleus  # noqa: E402


def _load(modname, default, env):
    """Load a subject from its mutation seam (env path) or the repo, under the name its IMPORTERS use, so a
    mutant is the code that actually runs (android.py imports surface + ear_lease; the server imports android)."""
    path = os.environ.get(env) or str(REPO / default)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    if modname.startswith("nucleus."):
        setattr(nucleus, modname.split(".", 1)[1], mod)
    return mod


surface = _load("surface", "mcp/phone/surface.py", "PHONE_SURFACE_SRC")
_load("nucleus.ear_lease", "nucleus/ear_lease.py", "EAR_LEASE_SRC")
_load("nucleus.android", "nucleus/android.py", "ANDROID_SRC")
srv = _load("phone_server", "mcp/phone/server.py", "PHONE_SERVER_SRC")

# Upstream @mobilenext/mobile-mcp 1.0.9's tools/list, as measured 2026-10-10 (33 names).
KNOWN_UPSTREAM = {
    "mobile_list_available_devices", "mobile_login_to_cloud_provider", "mobile_list_remote_devices",
    "mobile_allocate_remote_device", "mobile_release_remote_device", "mobile_list_apps", "mobile_get_foreground_app",
    "mobile_launch_app", "mobile_terminate_app", "mobile_install_app", "mobile_uninstall_app",
    "mobile_get_screen_size", "mobile_click_on_screen_at_coordinates", "mobile_double_tap_on_screen",
    "mobile_long_press_on_screen_at_coordinates", "mobile_list_elements_on_screen", "mobile_press_button",
    "mobile_open_url", "mobile_swipe_on_screen", "mobile_type_keys", "mobile_save_screenshot",
    "mobile_take_screenshot", "mobile_set_orientation", "mobile_fold_device", "mobile_set_location",
    "mobile_clipboard", "mobile_get_device_logs", "mobile_get_orientation", "mobile_start_screen_recording",
    "mobile_stop_screen_recording", "mobile_list_crashes", "mobile_get_crash", "mobile_batch_commands",
}
DENIED = {
    "mobile_login_to_cloud_provider", "mobile_list_remote_devices", "mobile_allocate_remote_device",
    "mobile_release_remote_device",                                    # a paid cloud
    "mobile_save_screenshot", "mobile_start_screen_recording", "mobile_stop_screen_recording",  # pixels to files
    "mobile_get_device_logs", "mobile_clipboard", "mobile_list_crashes", "mobile_get_crash",   # app data, codes
    "mobile_install_app", "mobile_uninstall_app", "mobile_batch_commands", "mobile_set_location",
}


# ── CENSUS + TELEMETRY: one real upstream process, opened the way the facade opens it ─────────────────────────
async def census_and_env():
    async with srv.upstream_session() as s:
        live = {t.name for t in (await s.list_tools()).tools}
        env = None
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            try:
                argv = (p / "cmdline").read_bytes().split(b"\0")
                if str(UPSTREAM).encode() in argv and p.stat().st_uid == os.getuid():
                    raw = (p / "environ").read_bytes().split(b"\0")
                    env = dict(x.decode(errors="replace").split("=", 1) for x in raw if b"=" in x)
            except OSError:
                continue
        return live, env

want("ALLOWLIST: no denied tool is reachable through the facade", not (srv.REVIEWED & DENIED),
     f"reachable={sorted(srv.REVIEWED & DENIED)}")
want("ALLOWLIST: the facade reaches 13 tools, no more", len(srv.REVIEWED) == 13, str(len(srv.REVIEWED)))
try:
    asyncio.run(srv.call_upstream("mobile_clipboard", {"device": "x"}))
    want("ALLOWLIST: naming a denied tool is refused", False, "it ran")
except srv.droid.AndroidError:
    want("ALLOWLIST: naming a denied tool is refused", True)
if not HAVE_UPSTREAM:
    print("  UNVERIFIED CENSUS, live ALLOWLIST, TELEMETRY: node or the pinned upstream isn't installed here "
          "(nucleus/android_setup.sh install, or mcp/phone/upstream: npm ci --ignore-scripts)")
    skipped.append("CENSUS/TELEMETRY (no upstream)")
else:
    live, env = asyncio.run(census_and_env())
    want("CENSUS: upstream's live tools/list is exactly the 33 reviewed-for names", live == KNOWN_UPSTREAM,
         f"added={sorted(live - KNOWN_UPSTREAM)} gone={sorted(KNOWN_UPSTREAM - live)}")
    want("ALLOWLIST: every facade verb names a live upstream tool", srv.REVIEWED <= live,
         f"missing={sorted(srv.REVIEWED - live)}")
    want("TELEMETRY: the spawned upstream process was found (control for the arms below)", env is not None)
    if env is not None:
        want("TELEMETRY: MOBILEMCP_DISABLE_TELEMETRY=1 in the spawned process's environ",
             env.get("MOBILEMCP_DISABLE_TELEMETRY") == "1", str(env.get("MOBILEMCP_DISABLE_TELEMETRY")))
        want("TELEMETRY: our environment doesn't leak in (canary, DSN, agent name absent)",
             not ({"ORACLE_CANARY_ENV", "ASTRYX_DSN", "ASTRYX_AGENT"} & set(env)), sorted(env))

# ── SURFACE ───────────────────────────────────────────────────────────────────────────────────────────────────
def dump(*wins):
    """A `dumpsys window windows`-shaped text: (title, package, visible)."""
    out = ["WINDOW MANAGER WINDOWS (dumpsys window windows)"]
    for i, (t, p, v) in enumerate(wins):
        out += [f"  Window #{i} Window{{{i:07x} u0 {t}}}:", f"    mOwnerUid=10{i:03d} package={p} appop=NONE",
                f"    isVisible={'true' if v else 'false'}"]
    return "\n".join(out)

BASE = [("ScreenDecorOverlayBottom", "com.android.systemui", True), ("ScreenDecorOverlay", "com.android.systemui", True),
        ("StatusBar", "com.android.systemui", True), ("Taskbar", "com.google.android.apps.nexuslauncher", True),
        ("com.android.settings/com.android.settings.Settings", "com.android.settings", True),
        ("NotificationShade", "com.android.systemui", False), ("com.example.chat/.Inbox", "com.example.chat", False)]
c = surface.classify(surface.windows(dump(*BASE)))
want("SURFACE: Settings + system decor (shade closed, a chat app hidden) → org", c["tier"] == "org", json.dumps(c))
c = surface.classify(surface.windows(dump(*[(t, p, True if t == "NotificationShade" else v) for t, p, v in BASE])))
want("SURFACE: the notification shade open → personal", c["tier"] == "personal" and any("NotificationShade" in u
     for u in c["unlisted"]), json.dumps(c))
c = surface.classify(surface.windows(dump(*[(t, p, True if p == "com.example.chat" else v) for t, p, v in BASE])))
want("SURFACE: an unlisted app window visible → personal", c["tier"] == "personal", json.dumps(c))
want("SURFACE: nothing visible → personal", surface.classify(surface.windows(dump(*[(t, p, False) for t, p, _ in BASE])))
     ["tier"] == "personal")
want("SURFACE: an empty / unparseable window list → personal", surface.classify(surface.windows("garbage"))["tier"]
     == "personal")
noline = dump(*BASE[:5]) + "\n  Window #9 Window{0000009 u0 com.example.chat/.Inbox}:\n    package=com.example.chat"
want("SURFACE: a window block with no isVisible line counts as visible (unknown → personal)",
     surface.classify(surface.windows(noline))["tier"] == "personal")
want("SURFACE: a title that only CONTAINS a public title isn't public (full match)",
     surface.classify(surface.windows(dump(*BASE[:5], ("PopupStatusBarOverlay", "com.android.systemui", True))))
     ["tier"] == "personal")
want("SURFACE: a public title owned by ANOTHER package isn't public (the package is checked)",
     surface.classify(surface.windows(dump(*BASE[:5], ("StatusBar", "com.example.chat", True))))["tier"] == "personal")
want("SURFACE: droid.surface() on an unreachable device → personal (fails closed)",
     srv.droid.surface("emulator-0000")["tier"] == "personal")

ORG_R = {"tier": "org", "packages": ["com.android.settings"], "unlisted": []}
PERS_R = {"tier": "personal", "packages": ["com.example.chat"], "unlisted": ["com.example.chat:x"]}
want("RACE: a personal reading BEFORE the call taints the result even if the screen is public after",
     surface.combine(PERS_R, ORG_R)["tier"] == "personal")
want("RACE: a personal reading AFTER taints it too", surface.combine(ORG_R, PERS_R)["tier"] == "personal")
want("RACE: org before and after, content with only framework + Settings ids → org (positive control)",
     surface.combine(ORG_R, ORG_R, content='@e1 TextView id="android:id/title" @e2 id="com.android.settings:id/x"')
     ["tier"] == "org")
c = surface.combine(ORG_R, ORG_R, content='@e1 TextView text="hi" id="com.example.bank:id/balance"')
want("RACE: an element id from an unlisted package taints an all-org reading (content is evidence)",
     c["tier"] == "personal" and "element id: com.example.bank" in c["unlisted"], json.dumps(c))
want("RACE: no readings at all → personal", surface.combine(content="")["tier"] == "personal")

# ── STRIP ─────────────────────────────────────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(REPO / "hooks"))
_s = importlib.util.spec_from_file_location("step_hook", os.environ.get("STEP_SRC") or REPO / "hooks/step.py")
step = importlib.util.module_from_spec(_s)
_s.loader.exec_module(step)
ORG = srv.STAMP + json.dumps({"tier": "org", "packages": ["com.android.settings"], "unlisted": []})
PERS = srv.STAMP + json.dumps({"tier": "personal", "packages": ["com.example.chat"], "unlisted": ["x"]})
T = lambda t: {"type": "text", "text": t}  # noqa: E731
msgs = [
    {"type": "tool_use", "id": "p1", "name": "mcp__phone__look", "input": {"device": "d", "text": True}},
    {"type": "tool_result", "tool_use_id": "p1", "content": [T("Settings: Network & internet"), T(ORG)]},
    {"type": "tool_use", "id": "p2", "name": "mcp__phone__look", "input": {"device": "d", "text": True}},
    {"type": "tool_result", "tool_use_id": "p2", "content": [T("Inbox: hello from the bank"), T(PERS)]},
    {"type": "tool_use", "id": "p3", "name": "mcp__phone__act", "input": {"action": "foreground", "device": "d"}},
    {"type": "tool_result", "tool_use_id": "p3", "content": [T("com.example.chat")]},
    {"type": "tool_use", "id": "p4", "name": "mcp__phone__look", "input": {"device": "d", "text": True}},
    {"type": "tool_result", "tool_use_id": "p4", "content": [T(ORG + " page text"), T("secret body")]},
    {"type": "tool_use", "id": "p5", "name": "mcp__phone__act", "input": {"action": "type", "device": "d",
                                                                           "text": "hunter2"}},
    {"type": "tool_result", "tool_use_id": "p6x", "content": "unrelated"},
    {"type": "tool_use", "id": "p6", "name": "mcp__phone__look", "input": {"device": "d"}},
    {"type": "tool_result", "tool_use_id": "p6", "content": [{"type": "image", "source": {"data": "aGVsbG8="}},
                                                             T(ORG)]},
    {"type": "tool_use", "id": "p7", "name": "mcp__phone__act", "input": {"action": "foreground", "device": "d"}},
    {"type": "tool_result", "tool_use_id": "p7", "content": ORG},
    {"type": "tool_use", "id": "h1", "name": "mcp__hands__act", "input": {"action": "click", "screen": "laptop"}},
    {"type": "tool_result", "tool_use_id": "h1", "content": [T("focused: his mail")]},
]
out = step.strip_pixels(msgs)
res = {o["tool_use_id"]: o["content"] for o in out if o.get("type") == "tool_result"}
use = {o["id"]: o for o in out if o.get("type") == "tool_use"}
blob = json.dumps(out)
want("STRIP: a phone result under an ORG stamp is kept (positive control)", "Network & internet" in json.dumps(res["p1"]))
want("STRIP: under a PERSONAL stamp → not kept", "bank" not in json.dumps(res["p2"]) and res["p2"] == step.PHONE_OMITTED)
want("STRIP: no stamp at all → not kept", res["p3"] == step.PHONE_OMITTED)
want("STRIP: a stamp that isn't the LAST block (forged inside the body) → not kept", res["p4"] == step.PHONE_OMITTED)
want("STRIP: a string body (even the stamp itself) → not kept", res["p7"] == step.PHONE_OMITTED)
want("STRIP: typed phone text is never kept", "hunter2" not in blob and use["p5"]["input"]["text"] == step.TYPED_OMITTED)
want("STRIP: a phone screenshot is never kept, even under an org stamp", "aGVsbG8=" not in blob and
     "image_omitted" in json.dumps(res["p6"]))
want("STRIP: an unrelated tool result is untouched (control)", res["p6x"] == "unrelated")
want("STRIP: the hands laptop rule is unchanged (control)", res["h1"] == step.LAPTOP_OMITTED)

# ── CAPS: one per-agent budget across hands and the phone (plan-7862 caps; seed #47660) ─────────────────────────
hdm = srv.hd
os.environ["HANDS_STEP_CAP"] = "3"
reached = []
_real_guard, _real_boot = srv._guard, srv.droid.boot


def _sentinel_guard(device):
    reached.append(("guard", device))
    raise srv.droid.AndroidError("reached-guard")


def _sentinel_boot(device, agent):
    reached.append(("boot", device))
    raise srv.droid.AndroidError("reached-boot")


srv._guard, srv.droid.boot = _sentinel_guard, _sentinel_boot
hdm.caps_reset("phone-oracle")
out = asyncio.run(srv.look("phone-x", text=True))
want("CAPS: an uncapped phone look reaches the phone layer (positive control)",
     reached == [("guard", "phone-x")] and "reached-guard" in str(out[0]), str(out))
hdm.charge("phone-oracle")                    # two steps spent on the DESKTOP, as the hands server charges them
hdm.charge("phone-oracle")
reached.clear()
out = asyncio.run(srv.look("phone-x", text=True))
want("CAPS: desktop steps + phone steps share ONE budget: after 2 hands steps and 1 phone look (cap 3) the next look "
     "is CAPPED and never reaches the phone", str(out[0]).startswith("CAPPED") and not reached, f"{out} {reached}")
want("CAPS: ...and the CAPPED answer ends with a PERSONAL stamp", out[-1].startswith(srv.STAMP)
     and json.loads(out[-1][len(srv.STAMP):])["tier"] == "personal", str(out[-1:]))
reached.clear()
out = asyncio.run(srv.act("tap", device="phone-x", x=1, y=1))
want("CAPS: a capped tap never reaches the phone", str(out[0]).startswith("CAPPED") and not reached, f"{out} {reached}")
reached.clear()
out = asyncio.run(srv.act("boot", device="phone-x"))
want("CAPS: a capped boot never starts a phone", str(out[0]).startswith("CAPPED") and not reached, f"{out} {reached}")
before_steps = (hdm.session("phone-oracle") or {}).get("steps")
asyncio.run(srv.act("phones"))
asyncio.run(srv.act("done", device="phone-x"))
want("CAPS: listing phones and `done` are free", (hdm.session("phone-oracle") or {}).get("steps") == before_steps,
     f"{before_steps} → {(hdm.session('phone-oracle') or {}).get('steps')}")
# SHUTDOWN is free and allowed when stopped or capped (a4 #47955): it only lowers capability. Still driver-only.
_real_drive, _real_shutdown = srv.droid.drive, srv.droid.shutdown
srv.droid.drive = lambda device, agent: reached.append(("drive", device))
srv.droid.shutdown = lambda device: reached.append(("shutdown", device)) or True
reached.clear()
steps0 = (hdm.session("phone-oracle") or {}).get("steps")
out = asyncio.run(srv.act("shutdown", device="phone-x"))                 # this agent is CAPPED (above)
want("SHUTDOWN: a CAPPED agent can still switch off the phone it drives, at no cost",
     str(out[0]).startswith("stopped phone-x") and ("shutdown", "phone-x") in reached
     and (hdm.session("phone-oracle") or {}).get("steps") == steps0, f"{out} {reached}")
want("SHUTDOWN: ...still through the driver hold (driver-only)", ("drive", "phone-x") in reached, str(reached))
hdm.caps_reset("phone-oracle")
hdm.stop("phone-oracle", "the owner stopped your hands (oracle)")
reached.clear()
out = asyncio.run(srv.act("shutdown", device="phone-x"))
want("SHUTDOWN: a STOPPED agent can still switch off its phone", str(out[0]).startswith("stopped phone-x"), str(out))
reached.clear()
out = asyncio.run(srv.act("boot", device="phone-x"))
want("SHUTDOWN: ...but a stopped agent can't BOOT one", str(out[0]).startswith("STOPPED") and
     ("boot", "phone-x") not in reached, f"{out} {reached}")
hdm.resume("phone-oracle")
srv.droid.drive, srv.droid.shutdown = _real_drive, _real_shutdown
srv.AGENT = ""
out = asyncio.run(srv.look("phone-x", text=True))
want("AGENT unset: a stamped 'whose hands are these?' answer, not an unstamped crash",
     "ASTRYX_AGENT is not set" in str(out[0]) and out[-1].startswith(srv.STAMP), str(out))
srv.AGENT = "phone-oracle"
srv._guard, srv.droid.boot = _real_guard, _real_boot
os.environ.pop("HANDS_STEP_CAP", None)

# ── LEASE ─────────────────────────────────────────────────────────────────────────────────────────────────────
try:
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db
    L = sys.modules["nucleus.ear_lease"]
    with fixture_db() as fx:
        os.environ["ANDROID_DSN"] = fx["dsn"]                      # the axis, set explicitly
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            R = "android:oracle-phone"
            want("LEASE: the first holder gets it", L.hold(c, R, "agent-a", 60) is not None)
            want("LEASE: a second holder is refused while it's live", L.hold(c, R, "agent-b", 60) is None)
            g0 = L.get(c, R)["granted_at"]
            time.sleep(0.05)
            r = L.hold(c, R, "agent-a", 60)
            want("LEASE: the holder renews (same granted_at, later expiry)", r is not None and r["granted_at"] == g0)
            want("LEASE: unhold by a non-holder does nothing", L.unhold(c, R, "agent-b") is None and
                 L.get(c, R)["holder"] == "agent-a")
            c.execute("UPDATE leases SET expires_at = now() - interval '1 second' WHERE resource=%s", (R,))
            want("LEASE: an expired hold is taken by the next holder", (L.hold(c, R, "agent-b", 60) or {})
                 .get("holder") == "agent-b")
            want("LEASE: unhold by its holder frees it", (L.unhold(c, R, "agent-b") or {}).get("state") == "free")
            try:
                L.hold(c, "ear:room", "agent-a", 60)
                want("LEASE: a microphone lease can't be held", False, "it was")
            except ValueError:
                want("LEASE: a microphone lease can't be held", True)
            try:
                c.execute("UPDATE leases SET state='HELD', holder='x', expires_at=NULL WHERE resource=%s", (R,))
                want("LEASE: the schema refuses a HELD row with no TTL", False, "accepted")
            except psycopg.errors.CheckViolation:
                want("LEASE: the schema refuses a HELD row with no TTL", True)
            # vm-slot: a hold whose VM is PROVED gone (no such emulator process) is freed for the next claimant
            L.hold(c, "vm-slot", "android:no-such-avd-oracle", 600)
            try:
                srv.droid.claim_slot("android:oracle-two")
                want("LEASE: vm-slot held by a VM that isn't running is freed for the next claimant",
                     L.get(c, "vm-slot")["holder"] == "android:oracle-two")
            except srv.droid.AndroidError as e:
                want("LEASE: vm-slot held by a VM that isn't running is freed for the next claimant", False, str(e))
            # …and a live holder (an unknown holder is never presumed gone) refuses, naming itself
            L.unhold(c, "vm-slot", "android:oracle-two")
            L.hold(c, "vm-slot", "oracle-live-vm", 600)
            try:
                srv.droid.claim_slot("android:oracle-two")
                want("LEASE: a live vm-slot hold refuses the next claimant, naming the holder", False, "claimed")
            except srv.droid.AndroidError as e:
                want("LEASE: a live vm-slot hold refuses the next claimant, naming the holder",
                     "oracle-live-vm" in str(e), str(e))
except Exception as e:  # noqa: BLE001
    if type(e).__name__ == "FixtureUnavailable":
        print(f"  UNVERIFIED LEASE arms: no fixture database ({e})")
        skipped.append("LEASE")
    else:
        raise

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
if skipped:
    print(f"NOT VERIFIED: {', '.join(skipped)} (the rest passed)")
    sys.exit(77)
print("PASS: phone facade (census, allowlist, telemetry, surface, strip, lease)")
