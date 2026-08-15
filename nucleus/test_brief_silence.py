#!/usr/bin/env python3
"""Oracle for triggers/canopus/brief_silence — both directions, every seam.

A guard is a claim, so it must be shown to FIRE when the condition holds and to go QUIET
when it does not. Positive grounding alone would pass on a guard that fires unconditionally
and on one that can never fire at all.

DELIBERATELY HERMETIC — no postgres, no .env, no network. The whole ctx is injected, so
this proves the same thing in a fresh clone as on the authoring machine, and its verdict
never depends on what the live wire happens to hold this minute. An earlier draft asserted
"fires against the live table" and passed only because a real miss was standing; the moment
that miss was fixed the assertion would have flipped to FAIL and read as a broken guard.
A state-dependent assertion in a committed suite is a time bomb, not coverage.
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SUBJECT = ROOT / "triggers" / "canopus" / "brief_silence.py"
if not SUBJECT.is_file():
    # The trigger bodies are gitignored, so a fresh clone has the oracle and not its
    # subject. SKIP LOUDLY: a not-run check is a THIRD state, and an oracle that quietly
    # exits 0 because it could not find what it verifies is the exact false-green the
    # whole suite exists to prevent.
    print("SKIP: triggers/canopus/brief_silence.py not present (gitignored body, e.g. a "
          "CI clone). Nothing was verified here.")
    sys.exit(77)          # 77 = SKIP (automake convention); check.sh counts it UNVERIFIED

_spec = importlib.util.spec_from_file_location("brief_silence", SUBJECT)
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

NOW = datetime.now(timezone.utc)
_fails: list[str] = []


class Ctx:
    """Fully injected. `last` is the fake max(ts) the guard's query would return;
    None models "no delivered message to him at all"."""

    def __init__(self, last, state=None):
        self.state = {} if state is None else state
        self._last = last

    def sql(self, q, params=()):
        assert "status='delivered'" in q, "the guard must read the DELIVERY column"
        assert params and params[0] == bs.OWNER, "the guard must anchor on the wire identity"
        return [{"last_ts": self._last}]


def ago(hours):
    return NOW - timedelta(hours=hours)


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'  ' + detail if detail else ''}")
    if not cond:
        _fails.append(name)


print("brief_silence oracle")

# ── the two directions ───────────────────────────────────────────────────────────
check("silent when he heard from me recently",
      bs.brief_silence(Ctx(ago(1))) is None)
check("fires once the floor is crossed",
      bs.brief_silence(Ctx(ago(bs.MAX_SILENCE_H + 12))) is not None)

# ── the boundary, both sides ─────────────────────────────────────────────────────
check("silent just inside the floor",
      bs.brief_silence(Ctx(ago(bs.MAX_SILENCE_H - 0.5))) is None)
check("fires just outside the floor",
      bs.brief_silence(Ctx(ago(bs.MAX_SILENCE_H + 0.5))) is not None)

# A daily duty plus slack: one late heartbeat must not trip it, a skipped day must.
check("a late-but-run brief does not trip it (24h < floor)",
      bs.brief_silence(Ctx(ago(24))) is None)
check("a fully skipped cycle does trip it (48h > floor)",
      bs.brief_silence(Ctx(ago(48))) is not None)

# ── throttle, re-nag, self-clear (guard-silence law: a CONDITION must re-nag) ────
st = {}
first = bs.brief_silence(Ctx(ago(40), st))
second = bs.brief_silence(Ctx(ago(40), st))
check("fires, then throttles inside the re-nag window",
      first is not None and second is None)

st["warned_at"] = (NOW - timedelta(hours=bs.RENAG_H + 1)).isoformat()
check("re-nags past the throttle while the condition still holds",
      bs.brief_silence(Ctx(ago(40), st)) is not None)

st = {"warned_at": (NOW - timedelta(minutes=5)).isoformat()}
bs.brief_silence(Ctx(ago(1), st))
check("resolving WIPES the throttle stamp, so the next miss is not muted",
      "warned_at" not in st)

# ── amnesia polarity: lost state must SPEAK, never silence ───────────────────────
check("state loss re-announces rather than going quiet",
      bs.brief_silence(Ctx(ago(40), {})) is not None)
check("an unparseable stamp fails toward firing",
      bs.brief_silence(Ctx(ago(40), {"warned_at": "not-a-date"})) is not None)

# ── fail-safe: a moved anchor must read as MORE silence, never a false clean ─────
out = bs.brief_silence(Ctx(None, {}))
check("no anchor at all defaults to WATCHED, not to clean", out is not None)
check("and says which two worlds it covers",
      out is not None and "routing identity" in out and "mute" in out)

# ── tier floor: a trigger's return posts to the peer-readable /api/messages ──────
bodies = [bs.brief_silence(Ctx(ago(40), {})), bs.brief_silence(Ctx(None, {}))]
leaks = ("dc:", "discord", "whatsapp", "telegram", "@")
check("no fire text names a surface, a channel id or a handle",
      all(all(tok not in (b or "").lower() for tok in leaks) for b in bodies))
check("no fire text carries a long digit run (a channel id or a phone shape)",
      all(not any(len(w.strip(".,()")) >= 11 and w.strip(".,()").isdigit()
                  for w in (b or "").split()) for b in bodies))

print("ALL PASS" if not _fails else f"FAILURES: {_fails}")
sys.exit(1 if _fails else 0)
