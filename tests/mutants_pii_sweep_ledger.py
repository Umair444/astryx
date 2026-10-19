"""Authored mutants for triggers/steward/pii_sweep.py — run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_pii_sweep_ledger.py

THE LIST IS THE JUDGEMENT, WHICH IS WHY IT IS AUTHORED. Every entry below is a way this
guard HAS been wrong or was one edit away from being wrong on 2026-08-16, when its
warn-once design was replaced by an open-findings ledger. M1 and M2 are not hypotheses:
M2 is the shipped behaviour that let a live PII finding sit unmentioned for 22 days, and
M1 is the rendering that put a group JID into the guard's own alarm (msg#344).

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list; the probe reports CAUGHT or
NOT PROBED, never "vacuous". The subject is gitignored (`triggers/`), so in a clean
checkout this file names an estate the repo deliberately does not carry — which
tests/test_mutants_wellformed.py classifies rather than assumes.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)

# PII_SWEEP_STAGED names a staged copy to probe before it is applied (the body is gitignored)
SUBJECT = Path(os.environ.get("PII_SWEEP_STAGED") or ESTATE / "triggers" / "steward" / "pii_sweep.py")
ORACLE = REPO / "tests" / "test_pii_sweep_ledger.py"
ENV = "PII_SWEEP_SRC"

MUTANTS = {
    # The unit-suffix exemption widened to a delegated TLD. `.target` is a real brand TLD, so an address there could
    # be the owner's: the over-broad, under-detection direction (steward 10-19, the cog-era unit-instance class).
    "M_unit1 the systemd-unit exemption also swallows .target (a real TLD)":
        ('_SYSTEMD_UNIT_SUFFIXES = frozenset(("service", "timer",',
         '_SYSTEMD_UNIT_SUFFIXES = frozenset(("target", "service", "timer",'),

    # The exemption dropped from the scan. Every cog unit instance cries owner-email again.
    "M_unit2 the systemd-unit exemption is not consulted":
        ("                                     or _is_systemd_unit(m.group(1))\n",
         ""),

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
    # The CI-run-id context exemption (10-16): each mutant is one way it could over- or under-reach.
    "M6 the run-id exemption is never consulted (every cited run id flags again)":
        ("            if label == \"phone-bare\" and _is_ci_run_id(text, m):\n",
         "            if False:\n"),
    "M7 the 92-prefix refusal is dropped (run 92… is exempted)":
        ("    return not m.group(0).startswith((\"0\", \"92\")) and bool(",
         "    return not m.group(0).startswith(\"0\") and bool("),
    "M8 the exemption ignores context (any bare number passes)":
        ("bool(_CI_RUN_CTX.search(text[max(0, m.start() - 24):m.start()]))", "True"),
    "M9 the word boundary goes (rerun N is exempted)":
        ("(?:\\brun\\s+", "(?:run\\s+"),
    "M10 the leading-0 refusal is dropped (run 03… is exempted)":
        ("    return not m.group(0).startswith((\"0\", \"92\")) and bool(",
         "    return not m.group(0).startswith(\"92\") and bool("),
}
