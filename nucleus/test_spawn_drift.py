#!/usr/bin/env python3
"""Oracle for triggers/scout/spawn_code_drift.py — the spawn-pinned deployment-drift guard.

WHAT MUST BE PROVEN, and why each of these is a real failure mode rather than a restatement
of the code: every check below that names an INVERSION is one I ran RED first, against the
naive implementation, and each of those naive implementations is the one a reasonable person
writes on the first try.

  1. mtime alone OVER-fires   — a touch with no content change must not arm anything.
  2. sha-with-changed_at=now UNDER-fires — the direction a detector must never fail in:
     a process started between the real edit and the guard's first sight of it loaded the OLD
     code, and must read STALE. Dating the change by mtime is what makes that come out right.
  3. newest-process INVERTS   — an agent holding an unreaped orphan reads CURRENT under
     `newest`, which is the live 08-14 case (scout had an 08-12 and an 08-14 server).
  4. a CLOSED band list goes silent at its last rung — the exact defect I recorded
     approvingly in someone else's instrument before catching it in my own.
  5. dedup on the (file, agent) ENTITY — a late-joining stale agent must not be swallowed by
     an earlier report about its peers.
  6. coverage must not silently shrink, and an unreadable file must be NAMED, not skipped.

Run by nucleus/check.sh. Exits 77 (SKIP, not PASS) when the gitignored trigger body is absent,
which is the honest verdict in a bare CI clone.
"""
import importlib.util
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BODY = REPO / "triggers/scout/spawn_code_drift.py"
EXIT_SKIP = 77

if not BODY.exists():
    print(f"SKIP: {BODY} absent (gitignored trigger body) — nothing verified here.")
    sys.exit(EXIT_SKIP)

sys.path.insert(0, str(REPO))                      # the trigger imports `astryx`
spec = importlib.util.spec_from_file_location("spawn_code_drift", BODY)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)                       # module __dict__ IS the fn globals: patchable

UTC = timezone.utc
NOW = datetime(2026, 8, 14, 6, 23, tzinfo=UTC)
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        fails.append(label)


def t(days_ago, hours=0):
    return NOW - timedelta(days=days_ago, hours=hours)


class Ctx:
    def __init__(self, state=None):
        self.state = state if state is not None else {}


SERVER = "channel/server.mjs"
GEO = "mcp/geoloc/server.py"

# The live 08-14 estate, reduced: server.mjs fixed ~21h ago, most agents older.
LIVE = [
    ("seed",     SERVER, t(3, 8)),
    ("vega",     SERVER, t(3, 8)),
    ("memory",   SERVER, t(2, 2)),
    ("steward",  SERVER, t(0, 4)),      # respawned AFTER the fix — the only clean one
    ("scout",    SERVER, t(0, 3)),      # newest is clean ...
    ("scout",    SERVER, t(2, 2)),      # ... but an unreaped orphan still runs the old code
]

print("PURE CORE — derive():")
by_path, watched, lost = mod.derive(LIVE, [])
check("one path derived from six processes", sorted(by_path), [SERVER])
check("server.mjs qualifies (>= 2 distinct agents)", watched, [SERVER])
check("per (agent, path) keeps the OLDEST process", by_path[SERVER]["scout"], t(2, 2))

print("\n  a transient script that merely inherited ASTRYX_AGENT must self-filter:")
_, w1, _ = mod.derive(LIVE + [("scout", "nucleus/oneoff.py", t(0, 1))], [])
check("single-agent exec does NOT qualify as spawn-pinned", w1, [SERVER])
_, w2, _ = mod.derive(LIVE + [("scout", GEO, t(1)), ("p1", GEO, t(1))], [])
check("two agents DO qualify — a new server type is covered on arrival", w2, [SERVER, GEO])

print("\n  coverage must persist once earned, and shrinkage must be reported:")
_, w3, l3 = mod.derive(LIVE, [SERVER, GEO])
check("a path exec'd by nobody this tick is reported LOST", l3, [GEO])
check("...and is not silently dropped from the watched set", w3, [SERVER])
_, w4, l4 = mod.derive([("seed", SERVER, t(3)), ("vega", SERVER, t(3))], [SERVER])
check("a path still running with fewer agents stays watched, unreported", (w4, l4), ([SERVER], []))

print("\nBAND LADDER — the top rung must be OPEN (check 4):")
check("1d -> 1", mod.band(1), 1)
check("2-3d -> 2", [mod.band(2), mod.band(3)], [2, 2])
check("4-7d -> 3", [mod.band(4), mod.band(7)], [3, 3])
check("8-15d -> 4", [mod.band(8), mod.band(15)], [4, 4])
check("same-day (0d) does not fire", mod.band(0), 0)
print("  INVERSION — a closed list (the defect) would return its last rung forever:")
closed = lambda d: min(len([b for b in (1, 2, 4, 8, 16) if d >= b]), 5)  # noqa: E731
check("closed ladder is SILENT from 16d to 512d (the bug)", closed(16) == closed(512), True)
check("open ladder still escalates 16d -> 512d", mod.band(16) < mod.band(512), True)

print("\nASSESS — stale is ANY process, not the newest (check 3):")
changed = {SERVER: t(0, 21)}                       # the fix landed 21h ago
stale, current, _ = mod.assess(by_path, [SERVER], changed, NOW)
check("five agents stale, steward clean", sorted({a for _, a, *_ in stale}),
      ["memory", "scout", "seed", "vega"])
check("nothing counted as fully current", current, [])
print("  INVERSION — keying on the NEWEST process reads scout as CURRENT:")
newest = {SERVER: {a: max(s for ag, p, s in LIVE if ag == a and p == SERVER)
                   for a in {ag for ag, p, _ in LIVE if p == SERVER}}}
st_new, _, _ = mod.assess(newest, [SERVER], changed, NOW)
check("newest-keyed misses the orphaned scout server (the bug)",
      "scout" in {a for _, a, *_ in st_new}, False)
check("oldest-keyed catches it", "scout" in {a for _, a, *_ in stale}, True)

print("\nASSESS — boundaries:")
check("a file whose change was never observed is not judged",
      mod.assess(by_path, [SERVER], {}, NOW)[0], [])
check("a watched file nothing is running is not judged",
      mod.assess({}, [SERVER], changed, NOW)[0], [])
check("every process newer than the change -> the file is CURRENT",
      mod.assess({SERVER: {"seed": t(0, 1)}}, [SERVER], changed, NOW)[1], [SERVER])

# ─────────────────────────── trigger level: state, dedup, heal, blindness ───────────────────
print("\nTRIGGER — sha decides IF, mtime decides WHEN (checks 1 and 2):")
tmp = tempfile.mkdtemp(prefix="spawn-drift-")
fake = Path(tmp)
(fake / "channel").mkdir(parents=True)
target = fake / SERVER
mod.REPO = fake
mod._now = lambda: NOW

# The real edit, 3 days before this guard ever ran. Deliberately NOT a sub-day gap: band 0 is
# silent on purpose (a fix undeployed for a few hours is normal ops — agents respawn on their
# own cadence, and a guard that fires inside that window is a guard nobody reads). The live
# 08-14 estate sat at 21h and this trigger is correctly silent about it until tomorrow.
EDIT_AT = NOW - timedelta(days=3)


def write(content, mtime):
    target.write_text(content)
    os.utime(target, (mtime.timestamp(), mtime.timestamp()))


def run(procs, ctx, unattributable=0):
    mod.scan_procs = lambda: (procs, unattributable)
    return mod.spawn_code_drift(ctx)


write("FIXED", EDIT_AT)
ctx = Ctx()
# A process started 3h after the edit but BEFORE this guard's first ever run: it loaded the
# fixed code and must read CURRENT. One started before the edit must read STALE.
out = run([("seed", SERVER, EDIT_AT - timedelta(hours=5)),
           ("steward", SERVER, EDIT_AT + timedelta(hours=3))], ctx)
check("run 1 does NOT baseline away the live truth", out is not None, True)
check("the pre-edit agent is named", "seed" in (out or ""), True)
check("the post-edit agent is not", "steward" not in (out or ""), True)
print("  INVERSION — dating the change at 'now' (discovery) instead of mtime (the edit).")
print("  Sharpened after the first draft of this oracle asserted the wrong harm: the damage is")
print("  not that assess() misses a stale agent, it is that EVERY process predates 'now', so a")
print("  CLEAN agent is accused and the gap's age is reset to zero on every fresh state.")
FIXED_AGENT = {SERVER: {"steward": EDIT_AT + timedelta(hours=3)}}   # respawned WITH the fix
bad, _, _ = mod.assess(FIXED_AGENT, [SERVER], {SERVER: NOW}, NOW)
good, _, _ = mod.assess(FIXED_AGENT, [SERVER], {SERVER: EDIT_AT}, NOW)
check("changed_at=now falsely accuses an agent that HAS the fix", len(bad), 1)
check("changed_at=mtime clears it", good, [])
stale_now, _, _ = mod.assess({SERVER: {"seed": EDIT_AT - timedelta(hours=5)}}, [SERVER],
                             {SERVER: NOW}, NOW)
stale_mt, _, _ = mod.assess({SERVER: {"seed": EDIT_AT - timedelta(hours=5)}}, [SERVER],
                            {SERVER: EDIT_AT}, NOW)
check("changed_at=now understates a 3-day-old gap as 0d (band 0 = silent)",
      (stale_now[0][2], stale_now[0][3]), (0, 0))
check("changed_at=mtime dates it correctly and reaches a firing band",
      (stale_mt[0][2], stale_mt[0][3]), (3, 2))

print("\n  a pure touch must not re-arm (check 1):")
before = dict(ctx.state["files"][SERVER])
os.utime(target, ((NOW - timedelta(minutes=1)).timestamp(),) * 2)   # mtime moves, bytes do not
run([("seed", SERVER, EDIT_AT - timedelta(hours=5)),
     ("steward", SERVER, EDIT_AT + timedelta(hours=3))], ctx)
check("changed_at survives a touch", ctx.state["files"][SERVER]["changed_at"],
      before["changed_at"])
print("  ...and a real edit DOES re-date it:")
write("FIXED AGAIN", NOW - timedelta(hours=2))
run([("seed", SERVER, EDIT_AT - timedelta(hours=5)),
     ("steward", SERVER, EDIT_AT + timedelta(hours=3))], ctx)
check("changed_at moved to the new mtime",
      ctx.state["files"][SERVER]["changed_at"].startswith("2026-08-14T04:23"), True)

print("\nDEDUP — on the (file, agent) entity, and the ladder (check 5):")
write("FIXED", EDIT_AT - timedelta(days=7))         # a week-old fix: band 3
ctx = Ctx()
P_OLD = [("seed", SERVER, EDIT_AT - timedelta(days=30)),
         ("vega", SERVER, EDIT_AT - timedelta(days=30))]
first = run(P_OLD, ctx)
check("first report names both stale agents", ("seed" in first and "vega" in first), True)
check("silent inside the same band", run(P_OLD, ctx), None)
print("  a LATE JOINER must still be reported, not swallowed by the earlier fire:")
late = run(P_OLD + [("memory", SERVER, EDIT_AT - timedelta(days=30))], ctx)
# Assert on the AGENT-LIST line, not the whole body: the prose legitimately contains the word
# "seed" ("respawning is seed's call"), and a naive substring check passed the first draft of
# this oracle for the wrong reason — a check that can be satisfied by prose is not a check.
listed = [ln.split("old code:")[1].strip() for ln in (late or "").splitlines()
          if "old code:" in ln]
check("memory is reported", listed, ["memory"])
check("...and seed/vega are not repeated inside their band",
      all(a not in listed[0] for a in ("seed", "vega")), True)
print("  the ladder escalates rather than going quiet:")
mod._now = lambda: NOW + timedelta(days=30)
esc = run(P_OLD, ctx)
check("a standing failure speaks again at the next rung", esc is not None, True)
mod._now = lambda: NOW

print("\nHEAL — a respawn past the change re-arms the ladder:")
ctx2 = Ctx()
run(P_OLD, ctx2)
check("stale recorded", sorted(ctx2.state["reported"]), [f"{SERVER}|seed", f"{SERVER}|vega"])
run([("seed", SERVER, NOW - timedelta(hours=1)), ("vega", SERVER, NOW - timedelta(hours=1))],
    ctx2)
check("dedup entries cleared once current", ctx2.state["reported"], {})
check("and it stays silent while healthy",
      run([("seed", SERVER, NOW - timedelta(hours=1)),
           ("vega", SERVER, NOW - timedelta(hours=1))], ctx2), None)

print("\nBLIND, NOT QUIET:")
ctx3 = Ctx()
check("one empty scan is a fluke, not a fact", run([], ctx3), None)
blind = run([], ctx3)
check("a persisting empty scan announces itself", "BLIND, NOT QUIET" in (blind or ""), True)
check("it says the past silence meant nothing", "meant NOTHING" in blind, True)
check("deduped, not a drumbeat", run([], ctx3), None)
print("  recovery re-arms the blindness watchdog:")
write("FIXED", EDIT_AT)
run(P_OLD, ctx3)
check("blind state cleared on recovery", "blind_since" in ctx3.state, False)

print("\nUNREADABLE IS NAMED, NOT SKIPPED (check 6):")
ctx4 = Ctx()
mod.REPO = fake / "nowhere"                        # watched path no longer resolvable
out4 = run(P_OLD, ctx4)
check("the file is reported UNVERIFIED", "UNREADABLE ON DISK" in (out4 or ""), True)
check("...by name", SERVER in (out4 or ""), True)
mod.REPO = fake

print("\nSCAN-RACE COVERAGE — the hazard must be counted, not assumed away:")
# seed argued the race is polarity-safe because a drop can only shrink the observed set. That
# holds for a dropped NEW process and INVERTS for a dropped OLD one, which is the direction
# that matters. Both halves are asserted here so nobody re-derives only the reassuring one.
OLD, NEW = EDIT_AT - timedelta(days=1), EDIT_AT + timedelta(hours=2)
ch = {SERVER: EDIT_AT}
check("losing the NEW process is safe — still reads STALE (seed's half)",
      len(mod.assess({SERVER: {"seed": OLD}}, [SERVER], ch, NOW)[0]), 1)
check("losing the OLD process reads CURRENT — the unsafe half he did not have",
      mod.assess({SERVER: {"seed": NEW}}, [SERVER], ch, NOW)[0], [])
ctx5 = Ctx()
out5 = run([("seed", SERVER, OLD), ("vega", SERVER, OLD)], ctx5, unattributable=2)
check("an unattributable live process is REPORTED", "COVERAGE CAVEAT" in (out5 or ""), True)
check("...and names the direction of the error", "too CURRENT" in out5, True)
check("...and forbids the tempting wrong fix", "oscillates" in out5, True)
ctx6 = Ctx()
run([("seed", SERVER, NEW), ("vega", SERVER, NEW)], ctx6)          # nothing stale
check("a caveat alone still breaks silence (it is a coverage claim, not a finding)",
      "COVERAGE CAVEAT" in (run([("seed", SERVER, NEW), ("vega", SERVER, NEW)],
                                ctx6, unattributable=1) or ""), True)
check("zero unattributable adds no noise",
      run([("seed", SERVER, NEW), ("vega", SERVER, NEW)], ctx6), None)

print("\nPOSTURE — this guard must never be an actuator:")
src = BODY.read_text()
banned = [w for w in ("spawn.sh", "refresh.sh", "tmux", "subprocess", "os.system", "kill(")
          if w in src.split('"""')[2]]              # body only; the docstring names them
check("no respawn/kill machinery in the executable body", banned, [])

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
