#!/usr/bin/env python3
"""Oracle for triggers/seed/tool_ship_watch.py — goal 3909, the vanish-masks-fresh class.

    venv/bin/python tests/test_ship_watch.py         (also run by nucleus/check.sh)

The subject is the most regression-prone file in the tree (its own comments log three prior
edit-regressions), and its defect is the silent kind: a dead announcement path presents as
QUIET, indistinguishable from "nothing shipped". This oracle drives the ACTUAL bodies with a
fake ctx (state + sql), on BOTH code sites, so the property is checked on the integrated file
and not on a paraphrase of it.

WHAT EACH ARM PINS:

  DECOUPLE (A). vanish (a capability left) and fresh (a capability arrived) are INDEPENDENT
  facts. The pre-fix code treats them as mutually exclusive: the `if gone:` branch RETURNS
  before the fresh-announcement code, so one standing deliberate-removal permanently masks
  every fresh ship (grant:geoloc masked mcp:memory + mcp:org for weeks; a self-removed
  one-shot froze org-news for 18 days). The arm plants a standing vanish AND a concurrent
  fresh ship in the same tick and asserts BOTH fire — the flag in the return AND the fresh
  row in org-news. It is RED against the pre-fix early-return (which posts nothing) and GREEN
  once fresh runs regardless of the vanish flag.

  DISCRIMINATION (B) — see the second phase below (auto-ACK on an independent trace).

HERMETIC: a fake ctx whose sql() answers from fixture rows by a crude match on the query
text and captures org-news INSERTs, so the oracle sees what the watcher actually announced.
The subject lives under the gitignored triggers/ estate, so on a clean checkout it is ABSENT:
classified with `git check-ignore` (ignored -> SKIP 77, tracked-but-missing -> FAIL) rather
than assumed either way — a green tick for a test that never ran is the vacuous-green defect
the suite exists to prevent.
"""
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("SHIP_WATCH_SRC") or
               (REPO / "triggers" / "seed" / "tool_ship_watch.py"))
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
              f"not carry the trigger estate. Nothing was verified here.")
        sys.exit(EXIT_SKIP)
    print(f"FAIL: {SUBJECT} is absent and NOT ignored ({rc=}) — a tracked guard has "
          f"vanished, which is a finding, not a skip.")
    sys.exit(1)


class FakeCtx:
    """Models the pulse ctx. state is json-roundtripped (the pulse serialises it to JSON,
    so a Decimal or int can come back a str — same trap the subject documents). sql()
    answers from fixtures by a crude substring match on the query, and INSERTs into
    org-news are captured in .posted so the oracle can read what the watcher announced."""

    def __init__(self, state=None, news=None, triggers=None, goals=None,
                 market=None, now=1_000_000.0):
        self.state = json.loads(json.dumps(state or {}))
        self.news = list(news or [])          # org-news body strings
        self.triggers = list(triggers or [])  # dict(agent, name, note, kind)
        self.goals = dict(goals or {})        # goal-id (str) -> state
        self.market = list(market or [])      # market_decay notice bodies
        self.now = now
        self.posted = []                      # captured org-news INSERT bodies
        self.queries = []

    def sql(self, q, params=None):
        self.queries.append(q)
        ql = q.strip().upper()
        if "EXTRACT(EPOCH" in ql:
            return [{"e": self.now}]
        if ql.startswith("INSERT INTO MESSAGES"):
            self.posted.append(params[0])
            return []
        if "FROM MESSAGES" in ql and "MARKET_DECAY" in ql:
            core = (params[0] if params else "").strip("%")
            return [{"ok": 1}] if any(core in m for m in self.market) else []
        if "FROM MESSAGES" in ql and "ORG-NEWS" in ql:
            return [{"body": b} for b in self.news]
        if "FROM TRIGGERS" in ql:
            return [dict(r) for r in self.triggers]
        if "FROM GOALS" in ql:
            gid = str(params[0]) if params else None
            st = self.goals.get(gid)
            return [{"state": st}] if st is not None else []
        return []


mod = load_subject()
_watch = mod["_watch"]
trigger_ship_watch = mod["trigger_ship_watch"]
_partition_gone = mod["_partition_gone"]
_capability_removal_trace = mod["_capability_removal_trace"]
_trigger_removal_trace = mod["_trigger_removal_trace"]

# ─────────────────────────────────────────────────────────────────────────────
print("DECOUPLE (A) — a standing vanish must not mask a concurrent fresh ship:")

# capability_ship_watch's shared _watch. tool:send is already named in org-news (not fresh);
# tool:brandnew is a real fresh ship org-news has never seen. tool:vanished_old sits in the
# high-water as a standing deliberate-removal — the mask.
ctx = FakeCtx(state={"tools": ["tool:send", "tool:vanished_old"]},
              news=["a receipt naming tool:send and nothing else"])
out = _watch(ctx, "tool-ship", "tools", {"tool:send", "tool:brandnew"},
             "blurb.", max_detail=4)
check("_watch: the standing vanish is still flagged",
      out is not None and "vanished_old" in out, f"out={out!r}")
check("_watch: the concurrent fresh ship IS posted to org-news (the mask is gone)",
      any("brandnew" in b for b in ctx.posted),
      f"posted={ctx.posted!r}")
check("_watch: only the genuinely-fresh key is announced, not the already-named one",
      any("brandnew" in b for b in ctx.posted) and
      not any("tool:send" in b for b in ctx.posted),
      f"posted={ctx.posted!r}")

# The inline trigger_ship_watch (its own state key `seen`, its own _mentions predicate,
# its own SQL) — same defect shape, must be fixed at the same time.
tctx = FakeCtx(state={"seen": ["seed/oldtrig"]},
               triggers=[{"agent": "seed", "name": "newtrig",
                          "note": "a brand new trigger", "kind": "python"}],
               news=["an org-news thread that mentions no trigger at all"])
tout = trigger_ship_watch(tctx)
check("trigger_ship_watch: the standing vanish is still flagged",
      tout is not None and "oldtrig" in tout, f"tout={tout!r}")
check("trigger_ship_watch: the concurrent fresh trigger IS posted to org-news",
      any("newtrig" in b for b in tctx.posted), f"posted={tctx.posted!r}")

# ─────────────────────────────────────────────────────────────────────────────
print("\nDISCRIMINATION (B) — auto-ACK a traced removal, keep a traceless one flagged:")

# THE LOAD-BEARING CONTROL (abstractor-4). The two controls are the SAME name in two classes,
# both grounded in real git: grant:geoloc was removed from the TRACKED spawn.sh (425906b,
# absent at HEAD) -> a genuine deliberate-removal trace -> auto-ACK; mcp:geoloc's source is
# GITIGNORED, so it has NO git trace for its removal — and the naive `git log -- mcp/geoloc/
# server.py` returns that same stale 425906b (the fail-open a4 flagged), which a correct
# resolver must NOT trust. The resolver gates on `git check-ignore` first.
check("_capability_removal_trace: grant:geoloc is TRACED (removed from tracked spawn.sh)",
      _capability_removal_trace("grant:geoloc") is True)
check("_capability_removal_trace: mcp:geoloc STAYS traceless (gitignored source, "
      "the stale-commit fail-open bait)",
      _capability_removal_trace("mcp:geoloc") is False)
check("_capability_removal_trace: a still-present grant is not a removal",
      _capability_removal_trace("grant:channels") is False)
check("_capability_removal_trace: an unknown kind falls to traceless (fail-safe)",
      _capability_removal_trace("weird:thing") is False)

# The partition, driven with the REAL trace-fn vs a silence-everything control. The silence-all
# control is the teeth: it must DROP the traceless key (the exact fail-open this fix replaces),
# and the real resolver must KEEP it. The disagreement between the two is the finding.
acked, flagged = _partition_gone({"grant:geoloc", "mcp:geoloc"}, _capability_removal_trace)
check("_partition_gone (real): traced grant:geoloc is auto-ACK'd", acked == {"grant:geoloc"},
      f"acked={acked}")
check("_partition_gone (real): traceless mcp:geoloc STAYS flagged", flagged == {"mcp:geoloc"},
      f"flagged={flagged}")
s_acked, s_flagged = _partition_gone({"grant:geoloc", "mcp:geoloc"}, lambda k: True)
check("_partition_gone (silence-all CONTROL): mcp:geoloc is WRONGLY dropped — proving the "
      "real resolver's discrimination is what keeps it flagged", s_flagged == set(),
      f"silence-all flagged={s_flagged}")
f_acked, f_flagged = _partition_gone({"grant:geoloc", "mcp:geoloc"}, lambda k: False)
check("_partition_gone (all-miss): everything stays flagged (fail-safe default)",
      f_acked == set() and f_flagged == {"grant:geoloc", "mcp:geoloc"})

# The full _watch body: a traced + a traceless removal in the SAME tick. Traced quiets and is
# shrunk from the high-water PER-ENTRY; traceless stays flagged and stays in the high-water.
dctx = FakeCtx(state={"caps": ["grant:present1", "grant:geoloc", "mcp:geoloc"]},
               news=["org-news naming grant:present1 and nothing else vanished"])
dout = _watch(dctx, "capability-ship", "caps", {"grant:present1"}, "blurb.", max_detail=4)
check("_watch discrimination: the traceless mcp:geoloc is FLAGGED",
      dout is not None and "mcp:geoloc" in dout, f"out={dout!r}")
check("_watch discrimination: the traced grant:geoloc is NOT flagged (auto-ACK'd quiet)",
      dout is None or "grant:geoloc" not in dout, f"out={dout!r}")
check("_watch discrimination: grant:geoloc is shrunk from the high-water PER-ENTRY",
      "grant:geoloc" not in dctx.state["caps"], f"caps={dctx.state['caps']}")
check("_watch discrimination: mcp:geoloc STAYS in the high-water (degradation observable)",
      "mcp:geoloc" in dctx.state["caps"], f"caps={dctx.state['caps']}")

# ─────────────────────────────────────────────────────────────────────────────
print("\nONESHOT (B) — a completed one-shot auto-ACKs; a hand-deleted trigger stays flagged:")

# A trigger vanishes from the authority ONLY when its ROW is deleted. The one class with an
# independent trace is a self-removed one-shot whose served goal completed (the goal-id is in
# the name, g3360_final -> 3360). A market retirement sets enabled=false but KEEPS the row, so
# it never vanishes and needs no auto-ACK; a hand-deleted trigger has no independent record and
# correctly stays a standing nag.
octx = FakeCtx(goals={"7777": "done"})
check("_trigger_removal_trace: a completed one-shot (goal done) is TRACED",
      _trigger_removal_trace(octx, "seed", "g7777_final") is True)
octx2 = FakeCtx(goals={"8888": "active"})
check("_trigger_removal_trace: a one-shot whose goal is NOT done MISSES -> flagged",
      _trigger_removal_trace(octx2, "seed", "g8888_final") is False)
check("_trigger_removal_trace: a one-shot whose goal id isn't recoverable MISSES -> flagged",
      _trigger_removal_trace(FakeCtx(goals={"7777": "done"}), "seed", "cleanup_hack") is False)

# Full body: a completed one-shot vanishes alongside a fresh trigger. The one-shot auto-ACKs
# (no perpetual alarm, no perpetual mask) and is dropped from `seen`; the fresh trigger STILL
# posts; a hand-deleted trigger in the same set stays flagged.
tctx2 = FakeCtx(state={"seen": ["seed/keepme", "seed/g7777_final", "seed/cleanup_hack"]},
                triggers=[{"agent": "seed", "name": "keepme", "note": "x", "kind": "python"},
                          {"agent": "seed", "name": "freshtrig", "note": "new", "kind": "python"}],
                goals={"7777": "done"},
                news=["org-news naming seed/keepme only"])
tout2 = trigger_ship_watch(tctx2)
check("oneshot full-body: the completed one-shot g7777_final is NOT flagged (auto-ACK'd)",
      tout2 is None or "g7777_final" not in tout2, f"tout={tout2!r}")
check("oneshot full-body: g7777_final is dropped from `seen` (no perpetual alarm)",
      "seed/g7777_final" not in tctx2.state["seen"], f"seen={tctx2.state['seen']}")
check("oneshot full-body: the hand-deleted cleanup_hack STAYS flagged",
      tout2 is not None and "cleanup_hack" in tout2, f"tout={tout2!r}")
check("oneshot full-body: cleanup_hack STAYS in `seen` (still a standing nag)",
      "seed/cleanup_hack" in tctx2.state["seen"], f"seen={tctx2.state['seen']}")
check("oneshot full-body: the fresh trigger STILL posts (no perpetual mask)",
      any("freshtrig" in b for b in tctx2.posted), f"posted={tctx2.posted!r}")

# ─────────────────────────────────────────────────────────────────────────────
if fails:
    print(f"\nFAIL: {len(fails)} assertion(s): {', '.join(fails)}")
    sys.exit(1)
print("\nOK: ship_watch invariants hold.")
