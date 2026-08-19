#!/usr/bin/env python3
"""Oracle for triggers/steward/doorbell_proof.py — the guard on the org's escape hatch.

    venv/bin/python nucleus/test_doorbell_proof.py     (also run by nucleus/check.sh)

THE SUBJECT WATCHES ONE JOIN. A roster-wide wedge leaves no agent able to consume a wake,
so the only escalation that can survive it is a row written by a systemd-resident process
(the pulse) and carried to the owner by the bridge. The bridge half is exercised daily and
the pulse half is exercised by wedge_watch's restart sweeps; the COMPOSITION has never run
once. This guard says so, and keeps saying so until a row proves otherwise.

WHAT IS ASSERTED, and each line is the difference between this guard and a decoration:
  * BORN RED. With no proof in the substrate it speaks on its first tick — the correct
    polarity for a carrier nobody has proven, and the reason it needs no liveness proof of
    its own: a check that starts red cannot be mistaken for one that never ran.
  * THE PROOF MUST BE DELIVERED. A row that was written but never landed is the exact
    failure mode here (`send` ok proves a row exists, never that a carrier carried it), so
    a pending row must NOT satisfy the guard.
  * ATTEMPTED-AND-FAILED IS ITS OWN STATE, distinct from never-attempted. Identical
    silence from the owner's side; completely different remedies.
  * IT DOES NOT DOUBLE-ALARM on the stuck row itself — outbound_stuck owns that subject
    org-wide, and two guards shouting about one row is how an org learns to skim.
  * A PROOF GOES STALE. Past the horizon it asks for a deliberate ring, on a ladder, and
    it does not claim the path is broken — only that its last known state is old.
  * silence carries POSITIVE EVIDENCE: the id and timestamp of the proof it saw.

HERMETIC: a fake ctx whose sql() answers from fixture rows chosen by a crude match on the
query text, and timestamps written into the past. The subject lives under the gitignored
triggers/ estate, so on a clean checkout it is ABSENT: classified with `git check-ignore`
(ignored -> SKIP 77, tracked but missing -> FAIL) rather than assumed either way.
"""
import json
import os
import runpy
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("DOORBELL_PROOF_SRC") or
               (REPO / "triggers" / "steward" / "doorbell_proof.py"))
EXIT_SKIP = 77
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        if detail:
            print(f"        {detail}")
        fails.append(name)


def load_subject():
    if SUBJECT.exists():
        sys.path.insert(0, str(REPO))
        return runpy.run_path(str(SUBJECT))
    rc = subprocess.run(["git", "check-ignore", "-q", str(SUBJECT)],
                        cwd=REPO, capture_output=True).returncode
    if rc == 0:
        print(f"SKIP: {SUBJECT} is absent and GITIGNORED — this checkout deliberately does "
              f"not carry the guard estate. Nothing was verified here.")
        sys.exit(EXIT_SKIP)
    print(f"FAIL: {SUBJECT} is absent and NOT ignored ({rc=}) — a tracked guard has "
          f"vanished, which is a finding, not a skip.")
    sys.exit(1)


def ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


class FakeCtx:
    """proof = the delivered pulse->owner row (or None); tried = how many exist at all."""

    def __init__(self, proof=None, tried=0, state=None):
        self.proof, self.tried = proof, tried
        self.state = json.loads(json.dumps(state or {}))
        self.queries = []

    def sql(self, q, params=None):
        self.queries.append(q)
        if "count(*)" in q:
            return [{"n": self.tried}]
        return [self.proof] if self.proof else []


mod = load_subject()
fire = mod["doorbell_proof"]
print("the org's out-of-band escape hatch is watched by something that starts red:")

# ── never rung ─────────────────────────────────────────────────────────────────────
ctx = FakeCtx()
out = fire(ctx)
check("with no proof in the substrate the guard is BORN RED",
      out and "NEVER BEEN RUNG" in out, f"out={out!r}")
check("...and says which half is untested — the JOIN, not the bridge",
      out and "COMPOSITION" in out, f"out={out!r}")
check("...and names the one row that would close it",
      out and "to_agent='owner'" in out and "status" in out, f"out={out!r}")

out2 = fire(FakeCtx(state=ctx.state))
check("the same absence on the next tick is silent (slow ladder, not a drumbeat)",
      out2 is None, f"out={out2!r}")

aged = dict(ctx.state, never_first=ago(9).isoformat())
check("...but an older absence crosses a band and speaks again",
      fire(FakeCtx(state=aged)) is not None,
      "a carrier nobody has proven must not go quiet just because nobody acted")

# ── attempted, never landed ────────────────────────────────────────────────────────
ctx = FakeCtx(tried=2)
out = fire(ctx)
check("rows written but never delivered is its OWN state, not 'never attempted'",
      out and "ATTEMPTED AND NEVER LANDED" in out, f"out={out!r}")
check("...and it does not raise a second alarm about the stuck rows themselves",
      out and "outbound_stuck" in out and "not a second alarm" in out,
      "two guards shouting about one row is how an org learns to skim")

# ── a written-but-pending row must not satisfy the guard ───────────────────────────
# The FakeCtx models the subject's own WHERE clause: `proof` is what a delivered-only
# query returns. A pending row therefore shows up as tried>0 with proof=None — asserted
# here so the delivered filter cannot be dropped without this file noticing.
check("the guard's proof query filters on delivered, not merely on existence",
      "status='delivered'" in ctx.queries[0],
      f"queries={ctx.queries}")

# ── proven and fresh ───────────────────────────────────────────────────────────────
ctx = FakeCtx(proof={"id": 4242, "ts": ago(3)})
out = fire(ctx)
check("a recent delivered pulse->owner row makes the guard silent", out is None, f"{out!r}")
check("...and leaves POSITIVE evidence of what it saw",
      ctx.state.get("last_proof_id") == 4242 and ctx.state.get("last_proof_ts"),
      f"state={ctx.state}")

# ── proven, but the proof has gone stale ───────────────────────────────────────────
ctx = FakeCtx(proof={"id": 4242, "ts": ago(120)})
out = fire(ctx)
check("a proof older than the horizon asks for a deliberate ring",
      out and "NOT BEEN RUNG IN" in out, f"out={out!r}")
check("...and does NOT claim the path is broken (it claims the reading is old)",
      out and "nothing here says it is broken" in out, f"out={out!r}")
out2 = fire(FakeCtx(proof={"id": 4242, "ts": ago(120)}, state=ctx.state))
check("...and is silent at the same age on the next tick",
      out2 is None, f"out={out2!r}")
out3 = fire(FakeCtx(proof={"id": 4242, "ts": ago(400)}, state=ctx.state))
check("...and louder again once the staleness crosses a band",
      out3 is not None, "a bounded interval that stops being enforced is not bounded")

# ── a fresh proof re-arms the stale ladder ─────────────────────────────────────────
ctx4 = FakeCtx(proof={"id": 9001, "ts": ago(1)}, state=ctx.state)
fire(ctx4)
check("a fresh proof clears the staleness ladder, so a later drift is announced again",
      ctx4.state.get("stale_band") == -1, f"state={ctx4.state}")

# ── a proof also clears the never-rung ladder ──────────────────────────────────────
never_state = {"never_first": ago(30).isoformat(), "never_band": 3}
ctx5 = FakeCtx(proof={"id": 9002, "ts": ago(1)}, state=never_state)
fire(ctx5)
check("a first proof discharges the born-red state entirely",
      "never_first" not in ctx5.state and "never_band" not in ctx5.state,
      f"state={ctx5.state}")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
