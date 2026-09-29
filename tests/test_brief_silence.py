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
    """Fully injected. `last` is the fake max(ts) the guard's anchor query would return;
    None models "no delivered message to him at all". `escalated_recently` models a prior
    escalation row still inside the peer re-nag window. Writes are RECORDED, never executed —
    the escalation path has a real INSERT, and a test that let it run would be writing live
    wire rows every time the suite ran."""

    def __init__(self, last, state=None, escalated_recently=False, last_turn=None):
        self.state = {} if state is None else state
        self._last = last
        self._escalated_recently = escalated_recently
        # The fake max(ended_at) the liveness probe would return. DEFAULT None models a seat
        # taking NO turns — the wedge the escalation was built for, and the state every
        # pre-2026-09-17 escalation test implicitly assumed. A live silent seat passes a
        # recent timestamp instead.
        self._last_turn = last_turn
        self.writes = []          # every INSERT the guard attempted, as (query, params)
        self.said = []            # every wake the guard SAID (goal 4227 S1c: ctx.say, not INSERT)

    def say(self, to, body, **kw):
        self.said.append(("say", (to, body), kw))

    def sql(self, q, params=()):
        if q.lstrip().upper().startswith("INSERT"):
            self.writes.append((q, params))
            return []
        if "FROM turns" in q:                     # the liveness probe (escalation gate)
            assert "agent='canopus'" in q, \
                "liveness must read MY OWN turns, not the fleet's"
            return [{"last_turn": self._last_turn}]
        if "body LIKE" in q:                      # the escalation dedup probe
            assert params and params[0] == bs.ESCALATE_TO, \
                "the dedup must probe the peer it actually writes to"
            assert "from_agent='canopus'" in q, \
                "the dedup must look for MY OWN prior escalation, not anyone's message"
            return [{"?column?": 1}] if self._escalated_recently else []
        assert "status='delivered'" in q, "the guard must read the DELIVERY column"
        assert params and params[0] == bs.OWNER, "the guard must anchor on the wire identity"
        return [{"last_ts": self._last}]

    def escalations(self):
        return [(q, pr) for q, pr in self.writes if "INSERT" in q.upper()] + \
            [(lbl, pr) for lbl, pr, _ in self.said]


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

# ── escalation: the 08-19 hole — a fire delivered to a dead body has no consumer ──
# The guard fired correctly every 12h for 111h into a seat taking zero turns. Past
# ESCALATE_H it must stop trusting itself as its own recipient.
c = Ctx(ago(bs.ESCALATE_H - 2), {})
bs.brief_silence(c)
check("does NOT escalate while my own remedy is still plausible",
      c.escalations() == [])

c = Ctx(ago(bs.ESCALATE_H + 2), {})
bs.brief_silence(c)
esc = c.escalations()
check("escalates past the bound", len(esc) == 1)
check("and addresses a peer who is NOT me",
      len(esc) == 1 and esc[0][1][0] == bs.ESCALATE_TO and bs.ESCALATE_TO != "canopus")
check("and SAYS it as canopus, in supersede mode (a re-nag report; goal 4227 S1c)",
      len(c.said) == 1 and c.said[0][2].get("from_agent") == "canopus" and c.said[0][2].get("supersede") is True)
check("and marks the row so its own dedup can find it",
      len(esc) == 1 and esc[0][1][1].startswith(bs.ESCALATE_MARK))

c = Ctx(ago(bs.ESCALATE_H + 2), {}, escalated_recently=True)
bs.brief_silence(c)
check("does not re-escalate inside the peer re-nag window",
      c.escalations() == [])

# THE PROPERTY THE WHOLE EXTENSION EXISTS FOR: a throttle on telling MYSELF must never
# gate telling someone else. Fresh warned_at => the personal fire is suppressed; the
# escalation must still be written.
c = Ctx(ago(bs.ESCALATE_H + 2), {"warned_at": NOW.isoformat()})
out = bs.brief_silence(c)
check("personal throttle suppresses my own fire but NOT the escalation",
      out is None and len(c.escalations()) == 1)

# Dedup lives in the DB, not ctx.state — so a body that keeps losing state (the exact
# condition this path exists for) still escalates rather than going quiet.
c = Ctx(ago(bs.ESCALATE_H + 2), {})
bs.brief_silence(c)
check("state amnesia does not silence the escalation",
      len(c.escalations()) == 1)

c = Ctx(None, {})
bs.brief_silence(c)
check("a missing anchor escalates too (mute seat or moved identity)",
      len(c.escalations()) == 1)

# THE CONSTANT ITSELF, pinned to ABSOLUTE durations. Every assertion above derives its
# fixture from bs.ESCALATE_H, so it moves with the constant and would pass at any value —
# conformance-to-self, not to spec. A mutation run proved it: ESCALATE_H = 999999 survived
# the whole escalation block ([[feedback_verifier_sharing_producer_code]]). These two bound
# it from the duty instead. The duty is DAILY, so: one missed cycle is still mine to fix,
# and three days of a principal hearing nothing must have reached someone else by now.
c = Ctx(ago(30), {})
bs.brief_silence(c)
check("30h — one missed cycle — stays mine to fix, no peer spend",
      c.escalations() == [], "(pins the bound above 30h)")

c = Ctx(ago(72), {})
bs.brief_silence(c)
check("72h of a principal hearing nothing MUST have reached a peer",
      len(c.escalations()) == 1, "(pins the bound at or below 72h)")

# Tier floor on the ESCALATION specifically — it addresses a PEER, so the bar is the
# peer-readable one: it may say the duty is unmet, never what the reports would contain.
c = Ctx(ago(bs.ESCALATE_H + 2), {})
bs.brief_silence(c)
ebody = c.escalations()[0][1][1].lower()
check("escalation body names no surface, channel or handle",
      all(tok not in ebody for tok in leaks))
check("escalation body carries no long digit run",
      not any(len(w.strip(".,()")) >= 11 and w.strip(".,()").isdigit()
              for w in ebody.split()))
check("escalation body leaks no career specifics",
      all(tok not in ebody for tok in
          ("klarna", "revolut", "monzo", "cv", "salary", "recruiter", "£", "application")))

# ── LIVENESS GATE ON THE ESCALATION (2026-09-17) ─────────────────────────────────
# The 09-16 cadence-close made deliberate no-delta silence HEALTHY. The escalation's own
# claim — "a fire delivered to a body taking no turns" — is false on a silent-but-ALIVE
# seat, and routing it to a peer cries wolf on the channel that must stay credible for the
# real wedge. So the numeric-silence escalation now fires ONLY when the seat is genuinely
# not consuming wakes. The PERSONAL fire is deliberately untouched. Default Ctx last_turn is
# None (a wedge) — so every escalation test above still models the seat the guard was built
# for, and these add the world it was missing.
c = Ctx(ago(bs.ESCALATE_H + 4), {}, last_turn=ago(1))     # 56h silent BUT a turn 1h ago
bs.brief_silence(c)
check("a LIVE seat past the bound does NOT escalate (deliberate silence, not a wedge)",
      c.escalations() == [])
check("but the PERSONAL re-decision fire still fires for a live silent seat",
      bs.brief_silence(Ctx(ago(bs.ESCALATE_H + 4), {}, last_turn=ago(1))) is not None)

c = Ctx(ago(bs.ESCALATE_H + 4), {}, last_turn=None)       # 56h silent, zero turns = wedged
bs.brief_silence(c)
check("a WEDGED seat past the bound (no turns at all) DOES escalate",
      len(c.escalations()) == 1)

# A present-but-stale timestamp is still a wedge — kills a LIVENESS_H=huge mutation that the
# None case (which short-circuits before the comparison) cannot catch.
c = Ctx(ago(bs.ESCALATE_H + 4), {}, last_turn=ago(bs.LIVENESS_H + 2))
bs.brief_silence(c)
check("a turn just OUTSIDE the liveness window is a wedge — escalates",
      len(c.escalations()) == 1)
c = Ctx(ago(bs.ESCALATE_H + 4), {}, last_turn=ago(bs.LIVENESS_H - 2))
bs.brief_silence(c)
check("a turn just INSIDE the liveness window is alive — no escalation",
      c.escalations() == [])

# Fail-safe: a liveness probe that ERRORS must read as NOT alive (escalate), never a false
# clean — the polarity this whole guard descends from.
class ErrCtx(Ctx):
    def sql(self, q, params=()):
        if "FROM turns" in q:
            raise RuntimeError("liveness probe blew up")
        return super().sql(q, params)
c = ErrCtx(ago(bs.ESCALATE_H + 4), {})
bs.brief_silence(c)
check("a liveness-probe ERROR fails toward escalation, never a false clean",
      len(c.escalations()) == 1)

# The no-anchor case is NOT liveness-gated: alive-but-no-delivered-message-ever is a broken
# routing identity, exactly what a live seat cannot diagnose about itself.
c = Ctx(None, {}, last_turn=ago(1))
bs.brief_silence(c)
check("a LIVE seat with no anchor still escalates (broken routing, not a wedge)",
      len(c.escalations()) == 1)

# The liveness window pinned in ABSOLUTE durations, so a mutated LIVENESS_H cannot survive
# by dragging the fixtures with it ([[feedback_threshold_needs_a_world_unit_fixture]]).
c = Ctx(ago(72), {}, last_turn=ago(2))
bs.brief_silence(c)
check("72h silent but a turn 2h ago is a live silent seat — no peer spend",
      c.escalations() == [], "(pins the liveness window above 2h)")
c = Ctx(ago(72), {}, last_turn=ago(48))
bs.brief_silence(c)
check("48h since the last turn is a wedge by any duty-cycle measure — escalates",
      len(c.escalations()) == 1, "(pins the liveness window below 48h)")

print("ALL PASS" if not _fails else f"FAILURES: {_fails}")
sys.exit(1 if _fails else 0)
