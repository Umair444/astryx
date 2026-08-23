"""Authored mutants for triggers/seed/wedge_watch.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_wedge_watch.py

THE LIST IS THE JUDGEMENT, WHICH IS WHY IT IS AUTHORED AND NOT GENERATED. Each entry is a
way this classifier could plausibly be wrong — most of them are ways it HAS been wrong, on
this file, in the last twenty-four hours. A generic mutator would emit mostly equivalent
mutants and drown that signal; this list is reviewable precisely because someone had to
claim each entry is a real risk.

Two of these (M4, M3) went uncaught when the recovered-branch assertions were first
written, and finding that is what produced the tool. Keep them: a mutant that once slipped
through is the most valuable kind, because it documents a hole that actually existed rather
than one somebody imagined.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list. Every mutant being caught
means the authored risks are probed and nothing more — see the probe's docstring on why it
may never report an assertion as vacuous.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "seed" / "wedge_watch.py"
ORACLE = REPO / "nucleus" / "test_wedge_watch.py"
ENV = "WEDGE_WATCH_SRC"

MUTANTS = {
    # The pre-fix two-state classifier. Every recovered outage silently becomes a
    # bookkeeping gap, and the alarm affirmatively says "they were working" of an agent
    # that was down 32h. (steward, msg 4236.)
    "M1 rate gate disabled (pre-fix two-state)":
        ("WORKING_RATE = 1.0", "WORKING_RATE = 0.0"),

    # Span measured from now rather than across the drop run. Inflates every span, so a
    # short run can clear the min-span floor purely by being old.
    "M2 span measured from NOW, not across the run":
        ('span_h = max(0.001, (r["newest"] - r["oldest"]).total_seconds() / 3600.0)',
         'span_h = max(0.001, (now - r["oldest"]).total_seconds() / 3600.0)'),

    # The discriminator reading the wrong marker. steps_after is >0 for BOTH a recovered
    # outage and a working agent, so this cannot separate them — it was the original bug.
    "M3 rate uses steps_AFTER instead of steps_inside":
        ('rate = (r.get("steps_inside") or 0) / span_h',
         'rate = (r.get("steps_after") or 0) / span_h'),

    # Drop the minimum-span floor. This one SURVIVED the first version of the recovered
    # assertions, because the fixture aimed at it was excluded by the rate gate before the
    # floor was ever consulted — a fixture excluded by the wrong clause tests the wrong
    # clause. Kept as the standing regression for that mistake.
    "M4 minimum-span floor removed":
        ("if rate < WORKING_RATE and span_h >= min_quiet_h:",
         "if rate < WORKING_RATE:"),

    # Fall-through: a row could be filed in two lists at once.
    "M5 no `continue` — a row can be double-filed":
        ('                gaps.append((agent, r["drops"]))\n            continue\n',
         '                gaps.append((agent, r["drops"]))\n'),

    # A single dropped wake becomes a state. This is the false-positive wall the guard's
    # timidity was bought with.
    "M6 min_drops ignored — one dropped wake is a state":
        ('if r["drops"] < min_drops:', "if False:"),

    # Alarm on agents with no body, which is agent_dark's subject and a different remedy
    # (spawn, not kill-then-spawn). Two guards shouting different fixes at one incident.
    # ANCHORED ON THE INDENT, and that is not cosmetic: the subject's own docstring now
    # QUOTES this line ("if agent not in bodies: continue") to explain the skip, so the
    # bare pattern matched twice and mutants-wellformed went red on the live tree. The
    # target is unchanged — wedge_watch.py:178, the code — the pattern just names it in a
    # way prose about the code cannot collide with. A mutant's pattern is an address, and
    # an address that a comment can occupy is not one. (steward, 2026-08-19, mechanical
    # only: no judgement about which line carries the fault was touched.)
    "M7 body check dropped — alarms on dead agents too":
        ("        if agent not in bodies:", "        if False:"),

    # The wedged branch, which the first mutant set never probed at all — every mutant
    # above targets the steps_after>0 path, so 11 of 21 assertions looked unprobed purely
    # because nothing tested their branch. Added to close that bias in the SET, not in
    # the oracle.
    "M8 wedged threshold inverted":
        ("if quiet_h >= min_quiet_h:", "if quiet_h <= min_quiet_h:"),

    "M9 wedged branch never fires":
        ("            wedged.append((agent, r[\"drops\"], quiet_h))",
         "            pass"),

    # A never-stepped agent (last_step IS NULL) treated as quiet-forever rather than
    # skipped — would alarm on an agent that has no step history at all.
    "M10 null last_step no longer skipped":
        ("        if last is None:\n            continue",
         "        if last is None:\n            pass"),

    # ═══ BC-2, goal #2457 — one mutant per property of §1's dedup form ═══════════════
    # A DEDUP PREDICATE HAS THREE PROPERTIES: who it MATCHES, that it is EXCLUSIVE to
    # them, and that it is conditioned on the act having SUCCEEDED. Each arm below kills
    # exactly one, so a green run locates the property that rotted rather than reporting
    # "the dedup broke".
    #
    # ON "LAST OBSERVED RED AT <sha>", which this set follows and must adapt: the design
    # asks each build-confirm to name the commit where its mutant was last seen RED, so a
    # green run is legible instead of ambiguous. The subject here is `triggers/seed/
    # wedge_watch.py`, which is GITIGNORED — a trigger body has no sha to name. So each
    # arm cites the ORACLE's commit plus a date. Naming a sha the subject does not have
    # would be the same rot the convention was written to stop, one level over.

    # (i) MATCHES the discharging set. Widen authorship and any writer's row silences the
    #     org's last alarm. Proves the dedup counts only rows from the set whose emission
    #     legitimately discharges the duty.
    #     Last observed RED: pre-BC-0 (before the from_agent pin landed).
    "BC2(i) dedup admits any author — a non-guard row binds":
        ("SELECT status, ts FROM messages WHERE from_agent = 'seed' ",
         "SELECT status, ts FROM messages WHERE from_agent IS NOT NULL "),

    # (ii) EXCLUSIVE to that set. THE LIVE HALF of BC-2 until 2026-08-20: reverting to the
    #      content key restores the defect where the org DISCUSSING its own dark-org alarm
    #      silences it — observed live (a4 msg 12018), where a plan revise quoting the
    #      marker suppressed the rung and the report of the suppression became the second
    #      suppressing row. A pin naming an identity the guard SHARES (seed writes 118
    #      rows to this same address) is §1(i) applied exactly and still not sufficient.
    #      Last observed RED: oracle 93a25c8, 2026-08-20 — the first commit at which the
    #      thread key made this a red-to-green demonstration rather than a wish.
    "BC2(ii) dedup keyed on CONTENT — discussing the alarm silences it":
        ('                "AND to_agent = \'owner\' AND thread = %s AND ts > %s",\n'
         '                (ESC_THREAD, now - timedelta(hours=ESCALATE_RENAG_H)))',
         '                "AND to_agent = \'owner\' AND body LIKE %s AND ts > %s",\n'
         '                ("%<org-dark-escalation>%", now - timedelta(hours=ESCALATE_RENAG_H)))'),

    # (iii) CONDITIONED ON SUCCESS, both directions. A dedup asks "did my act already
    #       LAND", so emission-time evidence makes the retry defeat itself exactly when
    #       the carrier is broken — the state the retry exists for. Two arms, because the
    #       property has two failure directions and a set that probed one would licence
    #       the other: too loud (a delivered row stops binding) and silent forever (an
    #       undelivered row binds past any grace, which is the pre-448bf8f defect).
    #       Last observed RED: pre-448bf8f.
    "BC2(iii-a) a DELIVERED row no longer suppresses — owner pinged every tick":
        ('        if r.get("status") == "delivered":\n            return True',
         '        if False:\n            return True'),

    "BC2(iii-b) an UNDELIVERED row suppresses forever — one dead row, silence for good":
        ("        if ts is not None and (now - ts) < timedelta(minutes=grace_min):",
         "        if ts is not None:"),

    # a3's amendment to BC-2: the subject-injection arm must cover the TERMINAL rung, not
    # only an in-band one. `unconsumed(owner)` is TRUE BY CONSTRUCTION — turns.input_msg_id
    # is written by agent sessions and Umair reads on WhatsApp — so if the terminal address
    # ever entered subject formation the escalation would be monotonically self-feeding
    # with no exit state, aimed at the owner's phone. Today it cannot: subjects come from
    # tmux (`_bodies()`), and there is no ax-owner session. That is a fact about how the
    # live set HAPPENS to be derived, not a stated exclusion — which is exactly why a3
    # refused to let it stand as the protection. This mutant injects the terminal address
    # into the subject set and asks whether ANYTHING objects.
    #     A DETECTOR MUST EXCLUDE ANY SUBJECT FOR WHICH ITS PREDICATE IS A TAUTOLOGY.
    #     Last observed RED: never — this arm has not yet been demonstrated red anywhere,
    #     and if it SURVIVES the probe that is the finding, not a pass.
    #     RE-POINTED 2026-08-20 after this arm read CAUGHT for the wrong reason. The old
    #     form injected the terminal address into `bodies`, which perturbed RELAY SELECTION
    #     and died on "seed DEAD -> the in-band alarm is INSERTed to the live relay" — an
    #     assertion about the recipient, not about subject formation. It certified a clause
    #     that was entirely unenforced. It now deletes the STATED exclusion itself, so the
    #     only thing that can catch it is the arm written for it.
    #     Last observed RED: oracle d3eb14a + this re-point, 2026-08-20.
    "BC2(a3) SUBJECT_EXCLUDE emptied — a tautological subject is admitted":
        ('SUBJECT_EXCLUDE = {"owner"}', "SUBJECT_EXCLUDE = set()"),
}
