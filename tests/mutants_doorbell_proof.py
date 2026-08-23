"""Authored mutants for triggers/steward/doorbell_proof.py — run by mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_doorbell_proof.py

THE LIST IS THE JUDGEMENT. This guard watches the org's only escape hatch from a
roster-wide wedge, and its whole value is that it is BORN RED and stays red until one row
proves the path. So every mutation below makes it quieter or makes it lie about what it
has seen, while still returning cleanly — the direction that would leave the org believing
it can reach its owner when it cannot.

NOT A CLAIM OF COMPLETENESS: coverage is bounded by this list, and the probe reports
CAUGHT or NOT PROBED, never "vacuous". The subject is gitignored (`triggers/`), so in a
clean checkout this file names an estate the repo deliberately does not carry.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "steward" / "doorbell_proof.py"
ORACLE = REPO / "tests" / "test_doorbell_proof.py"
ENV = "DOORBELL_PROOF_SRC"

MUTANTS = {
    # The delivered filter dropped: a row that was WRITTEN now satisfies the guard. This
    # is the exact failure being watched for — `send` ok proves a row exists, never that a
    # carrier carried it — restored inside the instrument that exists to catch it.
    "M1 a written-but-undelivered row counts as proof":
        ("WHERE from_agent='pulse' AND to_agent='owner' AND status='delivered' ",
         "WHERE from_agent='pulse' AND to_agent='owner' "),

    # Born red becomes born silent. The guard reports nothing until somebody happens to
    # ring the bell, which is the state it exists to end.
    "M2 the never-rung state is silent (born green instead of born red)":
        ("    first = st.get(\"never_first\")", "    return None\n    first = st.get(\"never_first\")"),

    # Warn-once: the first tick speaks and nothing ever speaks again, however long the
    # carrier stays unproven. The 22-day pii_sweep shape, on the escape hatch.
    "M3 the never-rung state never re-nags":
        ('    if b <= st.get("never_band", -1):', "    if st.get(\"never_band\") is not None:"),

    # Attempted-and-failed collapses into never-attempted: identical silence from the
    # owner's side, completely different remedy, and the louder of the two is lost.
    "M4 rows that were attempted and died read as 'nobody has tried'":
        ("    if tried:", "    if False:"),

    # The staleness horizon deleted, so a proof from any distance in the past reads as
    # current. A carrier verified once is a carrier whose last known state is old news.
    "M5 a proof never goes stale":
        ("        if age is None or age <= PROOF_HORIZON:",
         "        if True:"),

    # Positive evidence removed: the guard's silence no longer carries what it saw, so a
    # later reader cannot tell 'proof observed' from 'never looked'.
    "M6 a proven carrier leaves no record of the proof":
        ('        st["last_proof_id"] = int(row["id"])', "        pass"),
}
