"""Authored mutants for hooks/nudge.py (goal 4227, S4), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_nudge.py

There was no nudge hook before this one, so no pre-existing file can prove the oracle RED.
Each mutant below stands in for that proof on one invariant: it's the plausible way the hook
breaks that invariant, and the oracle has to catch each one on its own.

DELIBERATELY NOT AUTHORED: removing the hook's own label validation. The classifications
table's CHECKs enforce the same shape one layer down, so with the hook's check gone the insert
fails, the hook goes silent, and no row is written. The oracle can't tell the two layers apart
and shouldn't: the DB CHECK is the authority, and the hook's copy only saves a round-trip. That
mutant is equivalent, not a hole.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "hooks" / "nudge.py"
ORACLE = REPO / "tests" / "test_nudge.py"
ENV = "NUDGE_SRC"

MUTANTS = {
    # Exit 2 on UserPromptSubmit blocks the prompt. That's the one way to break I6 outright.
    "U1 the hook exits 2":
        ("    os._exit(0)\n", "    os._exit(2)\n"),

    # Per-socket timeouts only. A server that drips a byte every 0.4s never trips one, so only
    # the whole-hook deadline ends it.
    "U2 no whole-hook deadline":
        ("        signal.setitimer(signal.ITIMER_REAL, HARD_S)\n        main()\n",
         "        main()\n"),

    # "localhost" feels safe, but a name can be re-pointed. Only a literal loopback IP is.
    "U3 a hostname endpoint accepted":
        ("        return False                     # a hostname, not an IP",
         "        return u.hostname == \"localhost\"  # a hostname, not an IP"),

    # Private agents' prompts carry owner-personal data. They must never reach a classifier.
    "U4 content-private agents classified too":
        ("    if not is_content_public(agent):\n        return\n",
         "    if False:\n        return\n"),

    # Gate on difficulty instead of recurrence: a complex one-off gets the build-a-tool nudge,
    # and recurring simple work gets nothing.
    "U5 gated on difficulty, not recurrence":
        ('    if prior >= RECUR_N and label["tier"] != "trivial":',
         '    if label["tier"] == "complex" and prior >= 0 and False:'),

    # Prompt text persisted by the side door: an innocent-looking column.
    "U6 prompt text rides into session_id":
        ('(h.get("session_id") or None)', '(prompt[:60])'),

    # The owner flag ignored: the refusal can't be lifted, so a deliberate remote
    # classifier never works.
    "U7 the owner's allow-remote flag ignored":
        ('cfg.get("ASTRYX_CLASSIFIER_ALLOW_REMOTE") != "1"', 'True'),
}
