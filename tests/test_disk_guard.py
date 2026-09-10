#!/usr/bin/env python3
"""Oracle for bridges/disk_guard.py — the disk-space & timer-health guard.

    venv/bin/python tests/test_disk_guard.py      (also run by nucleus/check.sh)

The guard is an ACTUATOR that pages the owner when the resource the DB stands on is
running out, or when the janitor timer that keeps it clear has gone silent — riding the
whatsapp bridge's loop, out of the failure domain it watches. A page nobody can trust —
one that cries at a healthy disk, or stays mute at 96% — is worse than none. So this
proves the ways it must not misfire AND that it can actually FIRE:

  * IT CAN FIRE (RED-first). A 96% read makes the fake send record a CRITICAL page that
    carries the measured percentage and the reclaim playbook; a 42% read stays silent.
    Neuter classify() and the fire arms flip — the oracle has teeth.
  * BANDS + MAGNITUDE RE-NAG. First entry into a band pages; escalating to a worse band
    pages immediately (even inside the re-nag window); a standing band re-nags on a timer,
    CRITICAL faster than WARN; de-escalation inside the window stays quiet.
  * WATCH-THE-CAUSE. A dead snapper timer pages even with the disk near-empty, naming the
    timer — the arm that would have caught the 2026-08-30 root days early.
  * POLARITY (actuator). UNKNOWN (a df/systemctl read that fails) -> SILENT, and does NOT
    clear an existing latch: a probe blip is not recovery. A broken timer probe reads as
    'nothing dead', never a manufactured page.
  * RE-ARM. Recovery below the warn floor clears the latch so the next fill rings again.
  * FAIL-OPEN. A send that raises does not raise out of tick(), and does NOT latch (so it
    retries next tick). The lifeline invariant: the guard is a guest in the bridge's
    delivery loop and never breaks it.
  * DERIVE-NOT-HAND-LIST. read_dead_timers derives the astryx-*.timer set from unit files
    and unions the declared externals; parsing is proven against fake df/systemctl output.

Pure stdlib (asyncio + plain asserts), no df, no systemctl, no wire — the I/O seams are
injected. Subject is overridable via DISK_GUARD_SRC for mutation_probe (default: the real
module, which is the dependency check.sh's reachability parser sees).
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_override = os.environ.get("DISK_GUARD_SRC")
if not _override:
    from bridges import disk_guard as W          # noqa: E402  the real binding
    SUBJECT = Path(W.__file__)
else:
    SUBJECT = Path(_override)
    _spec = importlib.util.spec_from_file_location("disk_guard_under_test", SUBJECT)
    W = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = W
    _spec.loader.exec_module(W)                   # under mutation this REPLACES the import

# bind the subject's symbols locally so the arms read plainly
DiskGuard, classify, disk_band = W.DiskGuard, W.classify, W.disk_band
read_disk_percent, read_dead_timers = W.read_disk_percent, W.read_dead_timers
OK, WARN, ESCALATE, CRITICAL = W.OK, W.WARN, W.ESCALATE, W.CRITICAL
ALARM, RECOVER, SILENT = W.ALARM, W.RECOVER, W.SILENT
WARN_PCT, CRITICAL_PCT = W.WARN_PCT, W.CRITICAL_PCT
RENAG_SEC, CRITICAL_RENAG_SEC, EXTERNAL_TIMERS = W.RENAG_SEC, W.CRITICAL_RENAG_SEC, W.EXTERNAL_TIMERS

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _failures.append(msg)


class Clock:
    """A hand-cranked wall clock so re-nag timing is deterministic."""
    def __init__(self, t: float = 1000.0):
        self.t = t
    def __call__(self) -> float:
        return self.t


def make_guard(usage, dead, sends, *, clock=None, mono=None):
    """A DiskGuard whose reads return fixed values and whose send appends to `sends`.
    `usage`/`dead` may be a value or a zero-arg callable (to vary across ticks)."""
    async def read_usage():
        return usage() if callable(usage) else usage
    async def read_dead():
        return dead() if callable(dead) else dead
    async def send(body):
        sends.append(body)
    return DiskGuard(read_usage, read_dead, send,
                     clock=clock or Clock(), mono=mono or Clock())


# ── pure band mapping ────────────────────────────────────────────────────────────────
def test_disk_band():
    check(disk_band(None) is None, "None pct -> unknown band")
    check(disk_band(10) == OK, "10% -> OK")
    check(disk_band(79.9) == OK, "just under warn -> OK")
    check(disk_band(WARN_PCT) == WARN, "at warn threshold -> WARN")
    check(disk_band(90) == ESCALATE, "90 -> ESCALATE")
    check(disk_band(CRITICAL_PCT) == CRITICAL, "at critical -> CRITICAL")
    check(disk_band(100) == CRITICAL, "100 -> CRITICAL")


# ── pure classify ladder ──────────────────────────────────────────────────────────────
def test_classify_ladder():
    now = 1000.0
    check(classify(OK, None, None, now) == SILENT, "healthy, never alarmed -> silent")
    check(classify(WARN, None, None, now) == ALARM, "first entry to WARN -> alarm")
    check(classify(CRITICAL, WARN, now, now) == ALARM,
          "escalate WARN->CRITICAL within renag -> alarm immediately")
    check(classify(WARN, WARN, now, now) == SILENT,
          "same band inside renag window -> silent")
    check(classify(WARN, WARN, now - RENAG_SEC, now) == ALARM,
          "same band past renag -> re-nag")
    check(classify(CRITICAL, CRITICAL, now - (RENAG_SEC - 1), now) == ALARM,
          "critical re-nags faster than the WARN renag window")
    check(classify(CRITICAL, CRITICAL, now - (CRITICAL_RENAG_SEC - 1), now) == SILENT,
          "critical inside its own tighter window -> silent")
    check(classify(WARN, CRITICAL, now, now) == SILENT,
          "de-escalated but still in alarm band, inside renag -> silent (no spam)")
    check(classify(OK, CRITICAL, now, now) == RECOVER,
          "back to OK after alarm -> recover")
    check(classify(None, CRITICAL, now, now) == SILENT, "unknown -> silent")


# ── the RED-first arm: the guard FIRES at a real critical condition ───────────────────
def test_fires_at_critical():
    sends: list[str] = []
    g = make_guard(96.0, [], sends)
    asyncio.run(g.tick())
    check(len(sends) == 1, f"96% must produce exactly one alarm, got {len(sends)}")
    check("CRITICAL" in sends[0], "critical body must name the band")
    check("96%" in sends[0], "body carries the measured percentage")
    check("Reclaim" in sends[0], "critical alarm carries the reclaim playbook")
    check(g.last_band == CRITICAL, "latch set to CRITICAL after firing")


# ── the CONTROL: a healthy disk stays silent (would catch a guard stuck-on) ───────────
def test_silent_when_healthy():
    sends: list[str] = []
    g = make_guard(42.0, [], sends)
    asyncio.run(g.tick())
    check(sends == [], f"healthy disk must not page, got {sends}")
    check(g.last_band is None, "no latch when healthy")


# ── the watch-the-cause arm: a dead timer pages even at low disk ──────────────────────
def test_dead_timer_at_low_disk_fires():
    sends: list[str] = []
    g = make_guard(30.0, ["snapper-cleanup.timer"], sends)
    asyncio.run(g.tick())
    check(len(sends) == 1, "a dead reaper must page even with the disk near-empty")
    check("snapper-cleanup.timer" in sends[0], "alarm names the dead timer")


# ── escalation across ticks, then recovery ────────────────────────────────────────────
def test_escalate_then_recover():
    clk = Clock(1000.0)
    box = {"pct": 82.0}
    sends: list[str] = []
    g = make_guard(lambda: box["pct"], [], sends,
                   clock=clk, mono=lambda: clk.t)  # mono==wall so throttle advances with clk
    asyncio.run(g.tick())                          # enter WARN
    check(len(sends) == 1 and "WARN" in sends[-1], "tick1: WARN alarm")
    clk.t += 400; box["pct"] = 96.0                # past CHECK_SEC so the read is not throttled
    asyncio.run(g.tick())                          # escalate -> immediate CRITICAL
    check(len(sends) == 2 and "CRITICAL" in sends[-1], "tick2: immediate escalation alarm")
    clk.t += 400; box["pct"] = 20.0
    asyncio.run(g.tick())                          # recover
    check(len(sends) == 3 and "recovered" in sends[-1], "tick3: recovery message")
    check(g.last_band is None, "latch cleared on recovery")


# ── unknown does NOT clear an existing latch (a blip is not recovery) ──────────────────
def test_unknown_preserves_latch():
    clk = Clock(1000.0)
    box = {"pct": 96.0}
    sends: list[str] = []
    g = make_guard(lambda: box["pct"], [], sends, clock=clk, mono=lambda: clk.t)
    asyncio.run(g.tick())                          # CRITICAL alarm, latch set
    check(g.last_band == CRITICAL, "latched critical")
    clk.t += 400; box["pct"] = None                # past CHECK_SEC; df read fails -> unknown
    asyncio.run(g.tick())
    check(g.last_band == CRITICAL, "unknown must NOT clear the latch")
    check(len(sends) == 1, "unknown must not page and must not send recovery")


# ── a failed send must NOT latch (retried next tick) and must not raise ───────────────
def test_send_failure_does_not_latch():
    async def read_usage(): return 96.0
    async def read_dead(): return []
    async def boom(body): raise RuntimeError("wacli down")
    g = DiskGuard(read_usage, read_dead, boom, clock=Clock(), mono=Clock())
    asyncio.run(g.tick())                          # must not raise (fail-open)
    check(g.last_band is None, "a failed send must not set the latch (retry next tick)")


# ── throttle: two ticks inside CHECK_SEC read once ────────────────────────────────────
def test_throttle():
    reads = {"n": 0}
    async def read_usage():
        reads["n"] += 1
        return 96.0
    async def read_dead(): return []
    sends: list[str] = []
    async def send(b): sends.append(b)
    mono = Clock(500.0)
    g = DiskGuard(read_usage, read_dead, send, clock=Clock(), mono=mono, check_sec=300)
    asyncio.run(g.tick())
    mono.t += 5                                    # well inside check_sec
    asyncio.run(g.tick())
    check(reads["n"] == 1, f"throttle must collapse rapid ticks to one read, got {reads['n']}")


# ── detector parsing against fake subprocess output ───────────────────────────────────
def test_read_disk_percent_parses_df():
    async def fake_run(argv, timeout=20):
        return ("Filesystem     1024-blocks     Used Available Capacity Mounted on\n"
                "/dev/mapper/root 248896512 81234567 155000000      34% /\n")
    pct = asyncio.run(read_disk_percent(run=fake_run))
    check(pct == 34.0, f"df parse must yield 34.0, got {pct}")

    async def fake_fail(argv, timeout=20):
        return None
    check(asyncio.run(read_disk_percent(run=fake_fail)) is None,
          "a failed df read must be unknown (None)")


def test_read_dead_timers_derives_and_reports():
    async def fake_run(argv, timeout=20):
        if "list-unit-files" in argv:
            return "astryx-pulse.timer enabled\nastryx-backup.timer enabled\n"
        if argv[:2] == ["systemctl", "is-active"]:
            unit = argv[2]
            inactive = {"astryx-backup.timer", "snapper-cleanup.timer"}
            return "inactive\n" if unit in inactive else "active\n"
        return ""
    dead = asyncio.run(read_dead_timers(run=fake_run))
    check("astryx-backup.timer" in dead, "derived astryx timer, inactive -> reported")
    check("snapper-cleanup.timer" in dead, "external inactive timer -> reported")
    check("astryx-pulse.timer" not in dead, "active timer -> not reported")
    check(set(EXTERNAL_TIMERS) <= {"snapper-cleanup.timer", "snapper-timeline.timer"},
          "externals are the two snapper timers")

    async def fake_broken(argv, timeout=20):      # systemctl exec fails entirely
        return None
    check(asyncio.run(read_dead_timers(run=fake_broken)) == [],
          "a broken timer probe must not manufacture dead timers (actuator polarity)")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t()
        except Exception as e:                    # a test that itself throws is a failure
            _failures.append(f"{t.__name__} raised {e!r}")
    if _failures:
        print(f"FAIL ({len(_failures)}):")
        for f in _failures:
            print("  -", f)
        return 1
    print(f"PASS — {len(tests)} arms; disk-guard fires on threshold, stays silent when healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
