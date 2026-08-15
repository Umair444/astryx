"""Authored mutants for triggers/steward/pii_sweep.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_pii_sweep_ledger.py

THE LIST IS THE JUDGEMENT, WHICH IS WHY IT IS AUTHORED. Every entry below is a way this
guard HAS been wrong or was one edit away from being wrong on 2026-08-16, when its
warn-once design was replaced by an open-findings ledger. M1 and M2 are not hypotheses:
M2 is the shipped behaviour that let a live PII finding sit unmentioned for 22 days, and
M1 is the rendering that put a group JID into the guard's own alarm (msg#344).

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list; the probe reports CAUGHT or
NOT PROBED, never "vacuous". The subject is gitignored (`triggers/`), so in a clean
checkout this file names an estate the repo deliberately does not carry — which
nucleus/test_mutants_wellformed.py classifies rather than assumes.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "steward" / "pii_sweep.py"
ORACLE = REPO / "nucleus" / "test_pii_sweep_ledger.py"
ENV = "PII_SWEEP_SRC"

MUTANTS = {
    # The pre-fix rendering. `messages.thread` is a routing address, so the alarm text and
    # the durable ledger carry a group JID or a phone number — the detector emitting the
    # shape it hunts. Live instance: msg#344.
    "M1 location mask removed (the guard leaks the shape it hunts)":
        ('    return _ID_RUN.sub(lambda m: "#" + hashlib.sha256(m.group().encode()).hexdigest()[:6], s)',
         "    return s"),

    # WARN-ONCE RESTORED. Findings still enter the ledger and still discharge on repair,
    # but nothing ever crosses a band again, so an un-redacted finding is announced once
    # and then silent forever. This is exactly the 2026-07-25 failure.
    "M2 re-nag disabled — a standing finding speaks only once":
        ('        if b > rec.get("band", 0):',
         "        if b > 99:"),

    # Discharge without observation: a finding vanishes because its artifact could not be
    # READ, not because it was repaired. The guard's silence would then prove nothing —
    # and it fails in exactly the conditions (missing file, unreachable row) where the
    # ledger matters most.
    "M3 discharge no longer requires having observed the artifact":
        ('              if rec.get("src") in observed and h not in found]:',
         "              if h not in found]:"),

    # A ruling stops binding. Pinned findings re-enter the ledger and re-announce, which
    # is how an alarm the owner has already decided becomes noise that trains a reader to
    # skim the whole channel.
    "M4 pinned rulings ignored":
        ("        if h in pinned or h in open_:",
         "        if h in open_:"),

    # The value key degenerates into the row key, so N rows carrying ONE value read as N
    # distinct decisions. The live ledger is 76 findings over 23 values: this mutation
    # more than triples the apparent size of the work, and an unreadably large alarm is
    # the failure mode this guard's whole rendering exists to avoid.
    "M5 value key := row key (rows counted as decisions)":
        ('                    "vh": hashlib.sha256(snippet.encode()).hexdigest()[:8]}',
         '                    "vh": h}'),
}
