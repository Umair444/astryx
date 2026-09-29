"""Authored mutants for nucleus/toolreg.py (goal 4227), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_toolreg.py

toolreg decides what counts as a CALL and who AUTHORED a tool, which are the two numbers
usage-GDP is made of. Each mutant is a way those could plausibly go wrong. T1 is not
hypothetical: it is the version that ran live for the ledger's first minutes, and a review of
the live rows is what caught it, not the oracle, which had no arm for it yet.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "toolreg.py"
ORACLE = REPO / "tests" / "test_tool_ledger.py"
ENV = "TOOLREG_SRC"

MUTANTS = {
    # The first live version: any token that names a script is a call, so `git add x.py` and
    # `grep … x.py` inflate usage with every commit and every review.
    "T1 a mention counts as a call (the first live version)":
        ("        rid = _invoked(words)\n",
         "        rid = next((script_id(w) for w in words if script_id(w)), None)\n"),

    # Test the root before resolving '..', and nucleus/../<anything> becomes a tool.
    "T2 '..' not resolved before the root test":
        ("    p = os.path.normpath(p)\n", "    p = p\n"),

    # The door's id comes from a model. Trusting it lets any string into the ledger.
    "T3 the door trusts its untrusted id":
        ('return {"registry_id": rid} if valid_id(rid) else {"registry_id": "mcp:tools/run"}',
         'return {"registry_id": rid or "mcp:tools/run"}'),

    # Any server name accepted. Every external MCP a home happens to load becomes an "org tool".
    "T4 unregistered MCP servers accepted":
        ("    if server not in servers() and server not in CORE_SERVERS:\n        return None\n",
         ""),

    # Authorship from ANY Write, not the first event. A file that predates the ledger gets
    # whoever last overwrote it as its "author".
    "T5 a later Write claims authorship of an older file":
        ("        if ev and ev[0][1] in WRITE_TOOLS:\n            author = ev[0][0]\n",
         "        firsts = [e for e in ev if e[1] in WRITE_TOOLS]\n"
         "        if firsts:\n            author = firsts[0][0]\n"),

    # The author counted among its own contributors, so self-use looks like altruism.
    "T6 the author is its own contributor":
        ("            contributors = sorted({a for a, _ in ev[1:] if a != author})\n",
         "            contributors = sorted({a for a, _ in ev[1:]})\n"),

    # A Write/Edit counted as a call of the tool it edits.
    "T7 an edit is recorded as a call":
        ('        return {"edits": rid} if rid else {}\n',
         '        return {"registry_id": rid} if rid else {}\n'),

    # abstractor-4's catch on review: heredoc bodies parsed as commands. It's both directions
    # at once: body lines naming a script inflate, and one apostrophe in a body drops the real
    # call in front of it.
    "T8 heredoc bodies parsed as commands (strip reverted)":
        ("    lex = shlex.shlex(_strip_heredocs(cmd).replace(",
         "    lex = shlex.shlex((cmd).replace("),

    "T9 bash -n counted as a run":
        ('        if a == "-n" and os.path.basename(head) in _SHELLS:',
         '        if False and os.path.basename(head) in _SHELLS:'),
}
