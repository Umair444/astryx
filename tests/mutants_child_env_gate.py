"""Authored mutants for devtools/child_env_gate.py (plan-10224 child-env-gate), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_child_env_gate.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools/child_env_gate.py"
ORACLE = REPO / "tests" / "test_child_env_gate.py"
ENV = "CHILD_ENV_GATE_SRC"
TIMEOUT = 300

MUTANTS = {
    "C1 an exemption needs no reason (`# own-env:` alone declares)":
        ('DECLARE = re.compile(r"#\\s*own-env:\\s*\\S")', 'DECLARE = re.compile(r"#\\s*own-env:")'),
    "C2 a declaration anywhere above reaches the call (the window widened)":
        ('    lo, hi = node.lineno - 1, getattr(node, "end_lineno", node.lineno)',
         '    lo, hi = node.lineno - 3, getattr(node, "end_lineno", node.lineno)'),
    "C3 a bash -c body is never read (a repo script inside it reads plain: seed #61406)":
        ("    if prog in SHELLS and any(CODE_HINT.search(x) for x in rest):\n        return False\n", ""),
    "C4 a runtime shell body is trusted (the invisible body reads plain)":
        ("    if prog in SHELLS and any(x is None for x in rest):\n        return False\n", ""),
    "C5 git's hook-running subcommands read plain":
        ('        if sub is None or "-c" in lits or any(x in ("commit", "push", "merge", "rebase", "am", "checkout", '
         '"switch",',
         '        if sub is None or False and any(x in ("commit", "push", "merge", "rebase", "am", "checkout", "switch",'),
    "C6 systemctl start reads plain":
        ("    if prog == \"systemctl\" and any(x in SYSTEMCTL_STARTS for x in rest if x is not None):",
         "    if False:"),
    "C7 an ALLOWLIST copy reads as inheriting (`k in (…)` keeps everything)":
        ("            return named if isinstance(op, ast.In) else not named",
         "            return True if isinstance(op, ast.In) else not named"),
    "C8 a negated prefix filter never drops the registry (`not k.startswith(\"ASTRYX_\")` keeps it)":
        ("            return ps is not None and not any(REGISTRY.startswith(p) for p in ps)",
         "            return ps is not None"),
    "C9 the host's live registry counts as the env's own":
        ('    return not (isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.startswith("/etc"))',
         "    return True"),
    "C10 a filtered os.environ copy is green whatever its filter drops":
        ("            return \"inherit\" if all(_filter_keeps_registry(c) for c in g.ifs) else \\",
         "            return \"inherit\" if True else \\"),
    "C11 a builder recurses into itself (a same-named wrapper reads red: the self-recursion guard gone)":
        ("            rets = [(r.value, home, d) for d, home in sc.defs[name] if id(d) not in busy for r in ast.walk(d)",
         "            rets = [(r.value, home, d) for d, home in sc.defs[name] if True for r in ast.walk(d)"),
    "C12 sibling tests/ modules are never read (OrgHomes.env is invisible)":
        ("                    out.setdefault(k, []).extend(v)", "                    pass"),
    "C13 keyword-only parameters are never resolved":
        ("    kwonly = [a.arg for a in fn.args.kwonlyargs]", "    kwonly = []"),
    "C14 for-loop rows are never read":
        ("                        for row in n.iter.elts:", "                        for row in ():"),
}
