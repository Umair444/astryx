"""The disk-space & timer-health guard — the RESOURCE the database stands on, watched
from OUTSIDE the failure domain it protects.

WHY THIS EXISTS. On 2026-08-30 snapper-cleanup.timer was silently inactive; btrfs
snapshots piled to 1265, the disk hit 100%, genesis-pg took an ENOSPC crash and stuck
six days in crash-recovery (the full disk blocked the end-of-recovery checkpoint). The
org was dead for ~6 days with ZERO proactive warning — pulse_witness caught it only
REACTIVELY, at resume. No guard watched the resource the DB depends on, and nothing
watched the janitor timer whose death was the true root. This guard closes both: the
SYMPTOM (disk filling) and the CAUSE (a critical systemd timer gone inactive), days
before the symptom crosses a threshold.

THE FAILURE-DOMAIN LAW, and the one subtlety pulse_witness does NOT face. A guard's
ALARM CARRIER must sit outside the failure domain it reports (feedback: the alarm's
reader/carrier inside the failure domain). pulse_witness rings the owner via
`wire_insert` — a DB write — which is correct for a dead *pulse timer* (the DB is still
up). It is WRONG here: at 100% disk the DB is down, so a DB-write egress fails at exactly
the moment this guard must speak. So this guard's egress MUST be a DB-free, disk-free
path — a direct `wacli` network send (see WIRING below). Its dedup/band STATE lives in
memory for the same reason: at 100% disk both a file write and a DB write fail. Re-alarm
on restart is the SAFE direction — a resource alarm is cheap to repeat, catastrophic to
swallow (feedback: amnesia polarity — forgetting is safe only for what re-accrues; a
disk-full condition re-accrues on the next df).

DETECT, two arms:
  * DISK (symptom): `df` on the root mount — cheap, works AT 100%, no write. Bands
    escalate 80 / 90 / 95%. Escalating to a higher band always speaks immediately; a
    standing band re-nags on a timer (feedback: standing failures re-nag; magnitude
    re-nag by regime).
  * TIMERS (cause): every astryx-*.timer (DERIVED from the unit glob, never hand-listed —
    a new critical timer is covered without editing this file) plus the declared externals
    {snapper-cleanup, snapper-timeline}, each `systemctl is-active`. Any inactive one is
    the disabled-reaper class — it warns days before df moves. DERIVE-not-hand-list is the
    whole point: the 09-05 root was a timer nobody watched (feedback: derive the set).

POLARITY — an ACTUATOR that pages a human, so unknown resolves QUIET, never to a false
alarm (matches pulse_witness and escalation.py's unknown->silent for an actuator;
feedback: fail-safe polarity by cost). A df that cannot be read, or a systemctl that
errors, is UNKNOWN: it does not page, and it does NOT clear an existing latch (a probe
blip must not read as recovery). The detector-vs-actuator distinction matters: for a
DETECTOR unknown->WATCHED (loud); this is an actuator whose false page costs the owner's
trust at 3am, so unknown->silent — deliberately, and cited.

FAIL-OPEN IS ABSOLUTE. This guard is a guest in the owner's lifeline (the whatsapp
bridge's listen loop). A bug here must never break message delivery: every I/O touch is
wrapped and `tick()` cannot raise.

Pure and injectable: the two reads and the send are passed in, so the whole band ladder
is tested against synthetic percentages, synthetic timer states and a fake send, with no
df, no systemctl and no wire. The default real reads live here as module functions the
wiring passes in.

WIRING (seed's seam — the one production-touching edit; NOT applied here). In
bridges/whatsapp.py lifespan(), beside the pulse witness:

    from .disk_guard import DiskGuard, read_disk_percent, read_dead_timers

    # OWNER_DM: the owner's 1:1 WhatsApp DM. SOURCE IT AT RUNTIME from
    # routes-whatsapp.json — NEVER a string literal here. A raw phone JID is
    # human-personal tier; a literal in committed (soon-public) code is an
    # irreversible leak (the tier-safety miss pii_sweep/steward caught pre-commit,
    # msg 18399). routes-whatsapp.json is a list of {chat, agent, note, ...}; the
    # owner's DM is the route noted "Umair 1:1 DM". Same discipline applies to the
    # copy of this block that lands in whatsapp.py — source it there too.
    import json, pathlib
    _routes = json.loads((pathlib.Path(__file__).parent / "routes-whatsapp.json").read_text())
    OWNER_DM = next(r["chat"] for r in _routes if r["note"].startswith("Umair 1:1 DM"))

    async def _disk_send(body: str):
        # DB-FREE / DISK-FREE: direct wacli network call, NOT wire_insert. At 100% disk
        # the DB is down and wire_insert (pulse-witness's path) would fail exactly when
        # this guard must speak. This is the load-bearing difference from the witness.
        await wacli("--json", "send", "text", "--to", OWNER_DM, "--body", body)

    guard = DiskGuard(read_disk_percent, read_dead_timers, _disk_send)

    async def _on_idle():        # chain both guests on the one loop, each fail-open
        await witness.tick()
        await guard.tick()
    task = asyncio.create_task(listen(
        DSN, "(to_agent='owner' OR to_agent LIKE 'wa-%')", deliver, on_step,
        on_idle=_on_idle))

The egress helper is deliberately the SAME one-argument async `send(body)` seam
pulse_witness already proves — no novel shared interface for a future consumer (scout's
external-reachability probe) to break; it depends on a signature that already exists.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional, Sequence

# ── calibration (tunable; see docstring for the derivation) ──────────────────────────
WARN_PCT = 80.0
ESCALATE_PCT = 90.0
CRITICAL_PCT = 95.0
RENAG_SEC = 3600            # a standing band re-nags hourly (human-actuator cadence)
CRITICAL_RENAG_SEC = 1200  # a near-full disk re-nags every 20 min until it drops
CHECK_SEC = 300            # read df/systemctl at most this often, whatever the loop rate

# the systemd timers that carry no astryx- prefix but whose death fills the disk
EXTERNAL_TIMERS = ("snapper-cleanup.timer", "snapper-timeline.timer")

# band levels — a closed, ordered set; a band outside this range is a bug, loud
OK, WARN, ESCALATE, CRITICAL = 0, 1, 2, 3

# decision verbs returned by classify() — a closed set, so an unknown verb is a bug
ALARM = "alarm"
RECOVER = "recover"
SILENT = "silent"

# the proven reclaim, carried IN the alarm so the owner acts without a lookup
RECLAIM = ("Reclaim: (1) systemctl enable --now snapper-cleanup.timer && sudo snapper "
           "-c root cleanup  (2) docker builder prune -f  (3) sudo pacman -Scc")


def disk_band(pct: Optional[float]) -> Optional[int]:
    """Pure. Map a disk-usage percentage to a band, or None if unknown."""
    if pct is None:
        return None
    if pct >= CRITICAL_PCT:
        return CRITICAL
    if pct >= ESCALATE_PCT:
        return ESCALATE
    if pct >= WARN_PCT:
        return WARN
    return OK


def classify(band: Optional[int], last_band: Optional[int], last_alarm: Optional[float],
             now: float, *, renag_sec: float = RENAG_SEC,
             critical_renag_sec: float = CRITICAL_RENAG_SEC) -> str:
    """Pure. Given the current alarm band, our latch (last_band we spoke at, when), and
    the wall clock, decide what to say NOW. Never mutates.

    band is None for UNKNOWN (a read failed): stay silent AND keep the latch — a blip is
    not recovery. band OK means below every threshold and all timers healthy."""
    if band is None:
        return SILENT                         # unknown -> quiet, and DO NOT clear the latch
    if band == OK:
        return RECOVER if last_band is not None else SILENT
    # band >= WARN: some alarm condition holds
    if last_band is None:
        return ALARM                          # first entry into any alarm band
    if band > last_band:
        return ALARM                          # escalation to a worse band -> speak now
    # same or de-escalated but still in an alarm band: standing condition, re-nag on time
    renag = critical_renag_sec if band == CRITICAL else renag_sec
    if last_alarm is None or now - last_alarm >= renag:
        return ALARM
    return SILENT


def _band_name(band: int) -> str:
    return {WARN: "WARN", ESCALATE: "ESCALATE", CRITICAL: "CRITICAL"}.get(band, "?")


def _alarm_body(band: int, pct: Optional[float], dead_timers: Sequence[str]) -> str:
    head = "\U0001F534" if band == CRITICAL else "\U0001F7E0"
    parts = [f"{head} ASTRYX disk-guard [{_band_name(band)}]"]
    if pct is not None:
        parts.append(f"root filesystem {pct:.0f}% full")
    if dead_timers:
        parts.append("INACTIVE timer(s): " + ", ".join(dead_timers) +
                     " — a stopped janitor fills the disk silently; "
                     "`systemctl enable --now <timer>`")
    if band >= ESCALATE or dead_timers:
        parts.append(RECLAIM)
    if band == CRITICAL:
        parts.append("The DB crashes on ENOSPC — act now, this repeats until it drops.")
    return " | ".join(parts) + " — disk-guard (whatsapp bridge)"


def _recover_body(pct: Optional[float]) -> str:
    tail = f" (root {pct:.0f}%)" if pct is not None else ""
    return (f"\U0001F7E2 ASTRYX disk-guard recovered{tail} — usage back under "
            f"{WARN_PCT:.0f}% and all watched timers active.")


async def _run(argv: Sequence[str], timeout: float = 20) -> Optional[str]:
    """Run a command, return stdout, or None on any failure (unknown, never raises)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode not in (0, None):
            # is-active returns non-zero for an inactive unit — callers that care read
            # stdout regardless; a truly failed exec returns None via the except below.
            return out.decode(errors="replace")
        return out.decode(errors="replace")
    except Exception:
        return None


async def read_disk_percent(mount: str = "/",
                            run: Callable[..., Awaitable[Optional[str]]] = _run
                            ) -> Optional[float]:
    """Real df read. Returns used-percent for the mount, or None (unknown) on any
    failure. `df -P` guarantees a stable single-line-per-fs POSIX format."""
    out = await run(["df", "-P", mount])
    if not out:
        return None
    try:
        line = out.strip().splitlines()[-1]           # the data row, not the header
        for tok in line.split():
            if tok.endswith("%"):
                return float(tok[:-1])
    except Exception:
        return None
    return None


async def _list_astryx_timers(run: Callable[..., Awaitable[Optional[str]]]) -> list[str]:
    """Derive the astryx-*.timer set from installed unit files (never a hand-list)."""
    out = await run(["systemctl", "list-unit-files", "--type=timer", "--no-legend",
                     "astryx-*.timer"])
    if not out:
        return []
    names = []
    for line in out.strip().splitlines():
        tok = line.split()
        if tok and tok[0].endswith(".timer"):
            names.append(tok[0])
    return names


async def read_dead_timers(run: Callable[..., Awaitable[Optional[str]]] = _run
                           ) -> list[str]:
    """Real timer-health read. Returns the INACTIVE members of (astryx-*.timer, derived)
    ∪ EXTERNAL_TIMERS. Actuator polarity: a probe that cannot run reads as 'nothing dead'
    (never page on a broken probe); the disk arm still watches independently."""
    watched = list(dict.fromkeys(list(await _list_astryx_timers(run)) +
                                 list(EXTERNAL_TIMERS)))
    dead = []
    for unit in watched:
        out = await run(["systemctl", "is-active", unit])
        if out is None:
            continue                                  # probe failed -> not 'dead', silent
        if out.strip() != "active":
            dead.append(unit)
    return dead


class DiskGuard:
    """Rides an existing periodic loop (the whatsapp bridge's listen()). Call
    `await tick()` as often as you like — it throttles its own reads to once per
    CHECK_SEC and can never raise."""

    def __init__(self, read_usage: Callable[[], Awaitable[Optional[float]]],
                 read_dead_timers: Callable[[], Awaitable[Sequence[str]]],
                 send: Callable[[str], Awaitable[None]], *,
                 renag_sec: float = RENAG_SEC,
                 critical_renag_sec: float = CRITICAL_RENAG_SEC,
                 check_sec: float = CHECK_SEC,
                 clock: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic):
        # No defaults for the three I/O seams: a guard with no way to read or ring is a
        # decoration and must fail at construction, not silently at 3am.
        self._read_usage = read_usage
        self._read_dead_timers = read_dead_timers
        self._send = send
        self.renag_sec = renag_sec
        self.critical_renag_sec = critical_renag_sec
        self.check_sec = check_sec
        self._clock = clock
        self._mono = mono
        self.last_band: Optional[int] = None          # the band we last alarmed at
        self.last_alarm: Optional[float] = None
        self._last_check: Optional[float] = None

    async def tick(self) -> None:
        """One guard beat. Fail-open: any error is swallowed so the lifeline's delivery
        loop is never disturbed."""
        try:
            m = self._mono()
            if self._last_check is not None and m - self._last_check < self.check_sec:
                return                                # throttled — cheap no-op
            self._last_check = m

            try:
                pct = await self._read_usage()
            except Exception:
                pct = None
            try:
                dead = list(await self._read_dead_timers())
            except Exception:
                dead = []

            dband = disk_band(pct)
            if dband is None and not dead:
                band: Optional[int] = None            # unknown: df unreadable, no dead timer
            else:
                band = max(dband or OK, WARN if dead else OK)

            verb = classify(band, self.last_band, self.last_alarm, self._clock(),
                            renag_sec=self.renag_sec,
                            critical_renag_sec=self.critical_renag_sec)
            if verb == SILENT:
                return
            body = _alarm_body(band, pct, dead) if verb == ALARM else _recover_body(pct)
            # Send FIRST; only latch on success, so a failed ring is retried next tick
            # rather than swallowed by a latch that thinks it already spoke.
            await self._send(body)
            if verb == ALARM:
                self.last_band = band
                self.last_alarm = self._clock()
            else:                                     # RECOVER
                self.last_band = None
                self.last_alarm = None
        except Exception:
            # Outer belt: a guest in the lifeline's loop leaves no exception behind.
            return
