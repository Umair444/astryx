#!/usr/bin/env python3
"""The pii_sweep OPEN-FINDINGS LEDGER, gated: it must not forget, and must not leak.

WHY THIS EXISTS. steward's pii_sweep is the org's detector for owner-personal data
persisted into RAG-reachable artifacts. Two properties of it are load-bearing and both
failed in the field before this gate existed:

  1. A FINDING IS A CONDITION, NOT AN EVENT. The guard used to be warn-once — a `seen`
     set of hit hashes, announced the first time and never again. On 2026-07-25 it flagged
     owner-phone shapes in three step rows; nothing was redacted, nothing was ruled, and
     the guard never spoke of them again. They were still there 22 days later. So: a
     finding is silenced ONLY by repair (the artifact no longer carries it) or by an
     explicit `pinned` ruling — never by having once been announced.

  2. A LOCATION CAN BE A VALUE. The location string embeds `messages.thread`, which is a
     routing address: `wa:<group>@g.us`, `dc:<channel>`, and for a 1:1 chat
     `wa:<phone>@s.whatsapp.net`. Unmasked, the guard printed that into its own alarm —
     msg#344 is a pii_sweep alarm carrying a group JID it rendered as part of a location,
     and it is itself one of the findings this sweep now reports. A detector that emits
     the shape it hunts is the leak it exists to catch.

Both are cheap to assert and impossible to remember, which is the whole argument for a
standing gate over a discipline. Every check proves BOTH DIRECTIONS where a direction
exists: the property holds, AND the pre-fix behaviour would have failed it.

HERMETIC: no database, no live estate. The sweep's REPO global is repointed at a temp
tree of synthetic fixtures, and ctx.sql is a stub, so this gate's verdict depends on the
CODE and nothing else. Fixtures are certified-fake — 555-reserved numbers and a
nonexistent domain, never anything owner-shaped (a PII test must not create PII).

SUBJECT ABSENCE IS CLASSIFIED, NOT ASSUMED: `triggers/` is gitignored, so in a fresh
clone or a CI runner the guard is legitimately absent and this gate verifies nothing —
exit 77 (SKIP), by name. Absent while TRACKED is rot and fails. Git unable to answer
fails too: a detector that cannot classify must not skip.
"""
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# PII_SWEEP_SRC lets nucleus/mutation_probe.py point this oracle at a MUTATED copy of the
# guard, which is how the org proves an assertion can actually fail (mutants_pii_sweep_
# ledger.py). Unset, it is the deployed guard.
SUBJECT = Path(os.environ.get("PII_SWEEP_SRC")
               or REPO / "triggers" / "steward" / "pii_sweep.py")
EXIT_SKIP = 77
VALUE_RUN = re.compile(r"\d{7,}")     # the shape a routing id / phone number takes

# Certified-fake fixtures: NANP 555-01xx is reserved for fiction, and this domain is
# registered to nobody. Nothing here is owner-shaped, and nothing here is real.
FAKE_PHONE = "15555550123"
FAKE_EMAIL = "nobody@astryx-fixture-not-a-real-domain.test"

# PII_SWEEP_SRC can point outside the repo (mutation_probe copies the subject to a temp
# dir), and relative_to() raises on such a path — a diagnostic that crashes instead of
# diagnosing. Show the short name where it is one, the full path otherwise.
try:
    SHOWN = SUBJECT.relative_to(REPO)
except ValueError:
    SHOWN = SUBJECT

fails = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        print(f"      {detail}")
        fails.append(label)


def load_subject():
    if SUBJECT.is_file():
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))   # the guard imports the repo-root `astryx`
        try:
            return runpy.run_path(str(SUBJECT))
        except Exception as e:
            # Present but unloadable is RED, never a skip: on the machine that runs the
            # sweep, a guard that cannot even import is a guard that is not guarding.
            print(f"FAIL: {SHOWN} is present but did not load: "
                  f"{type(e).__name__}: {e}")
            sys.exit(1)
    try:
        rc = subprocess.run(["git", "check-ignore", "-q", str(SUBJECT)], cwd=REPO,
                            capture_output=True, timeout=10).returncode
    except Exception:
        rc = None
    if rc == 0:
        print(f"SKIP: {SHOWN} is gitignored and absent — a clean "
              f"checkout does not carry the trigger bodies. Nothing was verified here: "
              f"on a machine that RUNS the sweep, this gate is what proves it cannot "
              f"forget a finding or print a routing id.")
        sys.exit(EXIT_SKIP)
    if rc == 1:
        print(f"FAIL: {SHOWN} is absent and is TRACKED territory — "
              f"renamed or deleted?")
    else:
        print(f"FAIL: {SHOWN} is absent and git could not classify "
              f"it; refusing to skip on an unclassified absence.")
    sys.exit(1)


class FakeCtx:
    """No DB. The wire/step arms need a cursor only to establish their watermarks; the
    ledger logic under test is the same either way, and a gate that needs a live postgres
    is a gate that skips on the machine most likely to have drifted."""

    def __init__(self, state):
        self.state = state
        self.queries = []

    def sql(self, q, p=()):
        self.queries.append(q)
        return [{"m": 0}] if "MAX(id)" in q else []


def fixture_tree(tmp, journal_text):
    # TWO journals carrying the SAME value: the ledger must then report two findings over
    # ONE distinct value. That is the honest size of the work — one decision, not two —
    # and it is the only shape in which a broken value-key shows up at all.
    (tmp / "memory").mkdir(parents=True, exist_ok=True)
    for agent in ("fixture-a", "fixture-b"):
        (tmp / "homes" / agent).mkdir(parents=True, exist_ok=True)
        (tmp / "homes" / agent / "journal.md").write_text(journal_text)


def run_sweep(mod, tmp, state, journal_text):
    fixture_tree(tmp, journal_text)
    # NOT `mod["REPO"] = tmp`. runpy.run_path hands back a COPY of the executed module's
    # globals, so writing to it repoints nothing and the sweep quietly scans the REAL
    # tree — which holds no hits, so every assertion here would have passed while testing
    # nothing. The live namespace is the one the function closed over.
    mod["pii_sweep"].__globals__["REPO"] = tmp
    ctx = FakeCtx(json.loads(json.dumps(state)))
    fire = mod["pii_sweep"](ctx)
    return fire, ctx.state


def ledger_prose(state):
    """Only the HUMAN-READABLE fields of the ledger. Scanning the whole record for a long
    digit run is the wrong probe twice over: `first` is a 10-digit epoch, and a hex hash
    prefix is all-decimal about 2% of the time (14 of 76 keys in the live ledger). Either
    would fail this gate for a reason that has nothing to do with a leak — a red that
    teaches the reader to ignore reds. The values that could actually disclose anything are
    the ones a human reads: the location and the source address."""
    return json.dumps([[v.get("loc"), v.get("src"), v.get("label")]
                       for v in (state.get("open") or {}).values()])


def main():
    mod = load_subject()
    print("pii_sweep ledger — a finding is silenced by repair or by ruling, never by age:")

    # ---- 2) a location must never carry a routing value ---------------------------
    row = {"id": 1, "thread": f"wa:{FAKE_PHONE}@s.whatsapp.net", "from_agent": "fixture"}
    loc = mod["_msg_loc"](row)
    unmasked = f"wire msg#{row['id']} (thread {row['thread']}, from {row['from_agent']})"
    check("a location built from a wa:/dc: thread carries no value-shaped digit run",
          not VALUE_RUN.search(loc), f"location leaked digits: {loc!r}")
    check("...and the pre-fix rendering WOULD have failed that (the check can fail)",
          bool(VALUE_RUN.search(unmasked)),
          "the unmasked control no longer contains a digit run — this check has gone "
          "vacuous and now proves nothing")
    check("masking is stable and keeps distinct chats distinct",
          mod["_mask"]("wa:15555550123@x") == mod["_mask"]("wa:15555550123@x")
          and mod["_mask"]("wa:15555550123@x") != mod["_mask"]("wa:15555550124@x"),
          "mask is unstable or collides — the ledger key would drift or two chats merge")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dirty = f"contact sheet: {FAKE_PHONE} and {FAKE_EMAIL}\n"
        clean = "contact sheet: redacted\n"

        # ---- 1a) a new finding is announced --------------------------------------
        fire1, st1 = run_sweep(mod, tmp, {}, dirty)
        check("a fresh hit fires and enters the ledger",
              bool(fire1) and "NEW" in (fire1 or "") and len(st1["open"]) >= 1,
              f"fire={fire1!r} open={len(st1.get('open') or {})}")

        # ---- 1b) it does not re-announce on the next tick (no spam) ---------------
        fire2, st2 = run_sweep(mod, tmp, st1, dirty)
        check("the same standing hit is silent on the next tick",
              fire2 is None, f"re-announced immediately: {fire2!r}")

        # ---- 1c) but it SPEAKS AGAIN once it crosses an age band ------------------
        aged = json.loads(json.dumps(st2))
        for rec in aged["open"].values():
            rec["first"] = int(time.time()) - 45 * 86400
            rec["band"] = 0
        fire3, st3 = run_sweep(mod, tmp, aged, dirty)
        check("an un-repaired finding RE-NAGS after crossing an age band",
              bool(fire3) and "STILL OPEN" in (fire3 or ""),
              f"a 45-day-old un-redacted finding said nothing: {fire3!r} — this is the "
              f"2026-07-25 failure, where a live finding went quiet for 22 days")
        check("the re-nag counts DISTINCT VALUES, not rows (2 rows, 1 value -> '1')",
              "2 finding(s) over 1 distinct value(s)" in (fire3 or ""),
              f"the same value in two artifacts must read as ONE decision: {fire3!r}")

        # ---- 2b) nothing the guard emits or stores may carry a value --------------
        for name, blob in (("alarm text", fire3 or ""),
                           ("ledger state", ledger_prose(st3))):
            check(f"no value-shaped digit run in the {name}",
                  not VALUE_RUN.search(blob),
                  f"{name} carried a long digit run: {blob[:200]!r}")

        # ---- 1d) repair discharges it, silently ----------------------------------
        fire4, st4 = run_sweep(mod, tmp, st3, clean)
        check("redacting the artifact discharges the finding, with no alarm",
              fire4 is None and not st4["open"],
              f"fire={fire4!r} open={st4.get('open')}")

        # ---- 1e) but an artifact that could NOT be read discharges nothing --------
        ghost = {"open": {"c0ffee": {"loc": "homes/ghost/journal.md", "label": "email",
                                     "src": "file:homes/ghost/journal.md",
                                     "vh": "deadbeef",
                                     "first": int(time.time()) - 3 * 86400, "band": 9}}}
        _, st5 = run_sweep(mod, tmp, ghost, clean)
        check("a finding whose artifact was never observed stays OPEN",
              len(st5["open"]) == 1,
              "absence of observation was treated as evidence of repair — the guard's "
              "silence would then prove nothing at all")

        # ---- 1f) a pinned ruling silences that row, and only that row -------------
        fire6, st6 = run_sweep(mod, tmp, {}, dirty)
        pinned = {"pinned": {h: "fixture ruling" for h in st6["open"]}}
        fire7, st7 = run_sweep(mod, tmp, pinned, dirty)
        check("a pinned finding is never reported and never re-enters the ledger",
              fire7 is None and not st7["open"], f"fire={fire7!r} open={st7.get('open')}")

        # ---- migration: the v1 warn-once set is dropped and COUNTED --------------
        _, st8 = run_sweep(mod, tmp, {"seen": ["a" * 16, "b" * 16]}, clean)
        check("a v1 `seen` set is dropped and the loss is recorded, not swallowed",
              st8.get("v1_seen_dropped") == 2 and "seen" not in st8,
              f"state={ {k: v for k, v in st8.items() if k != 'open'} }")

    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
