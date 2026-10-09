"""Authored mutants for nucleus/branch_check.py (plan-4918 P2), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_branch_check.py

NOT authored, and declared: (1) removing the P0-b call would run a full prod dump first, beyond mutation_probe's
per-oracle budget; require_hardened itself is mutation-tested in tests/mutants_branch_check_prep.py. (2) The
FLAKY rerun lives inside a full two-suite run; its first real exercise is the first end-to-end run.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "branch_check.py"
ORACLE = REPO / "tests" / "test_branch_check.py"
ENV = "BRANCH_CHECK_SRC"

# DECLARED, not authored: the rerun's sqlguard intersection in run() (a branch-only finding must reproduce).
# run() is exercised end to end only by a real run, never by this oracle; its arm is the next e2e run's report.
MUTANTS = {
    "O1 a statement reaching PROD doesn't fail the run":
        ("    if any(witness.values()):\n        return 1\n", ""),
    "O2 FLAKY is counted as REGRESSED":
        ("    regressed = sorted(set(b[\"failed\"]) - set(m[\"failed\"]))",
         "    regressed = sorted((set(b[\"failed\"]) | set(b.get(\"flaky\", []))) - set(m[\"failed\"]))"),
    "O3 check.sh's ANSI colour isn't stripped (a red ✗ line is missed)":
        ("    lines = re.sub(r\"\\x1b\\[[0-9;]*m\", \"\", log).splitlines()", "    lines = log.splitlines()"),
    "O4 the witness counts every statement, not just the prod database's":
        ("                if json.loads(line).get(\"db\") == prod_db:", "                if json.loads(line).get(\"db\"):"),
    "O5 summary reads any 'FAILED (' line (a gate's own output injects names)":
        ("        kind = next((k for k, rx in _HEAD.items() if rx.match(ln)), None)\n        if kind is None:\n            break",
         "        kind = next((k for k, rx in _HEAD.items() if rx.match(ln)), None)\n        if kind is None:\n            continue"),
    "O6 gates failing on BOTH sides aren't reported":
        ('    dead = sorted((set(m["failed"]) & set(b["failed"])) - ({SQLGUARD_GATE} if judged else set()))', '    dead = []'),
    "O7 the walk has no TOP edge (skips verdict()'s leading blank and reads the last gate's output)":
        ("            if out[\"failed\"] or out[\"unverified\"]:\n                break", "            if False:\n                break"),
    "O8 sqlguard's branch-only findings are ignored (a new R-NEW on the branch reads clean)":
        ("        sg_new = sorted(l for i, l in br.items() if i not in mr)", "        sg_new = []"),
    "O9 sqlguard is still listed dead when it WAS judged differentially":
        ('    dead = sorted((set(m["failed"]) & set(b["failed"])) - ({SQLGUARD_GATE} if judged else set()))',
         '    dead = sorted(set(m["failed"]) & set(b["failed"]))'),
    "O10 production scopes its sweep (only=set(): no orphan is ever reaped, a reboot strands every role again)":
        ("    for r in rs.sweep(dsn):", "    for r in rs.sweep(dsn, only=set()):"),
    "O11 an EXECUTED unlisted site (its oracle ran) is excused as dark too":
        ('g = covering_gate(mt.group(1), dark_gates, refs or {}) if mt and "UNEXECUTED" in l else None',
         'g = covering_gate(mt.group(1), dark_gates, refs or {}) if mt else None'),
    "O12 co-occurrence, not relation: any dark gate excuses any site (a2 #37119's fail-open)":
        ('        if mod in r or site_path in r:\n            return g', '        return g'),
    "O13 a dark site is dropped silently instead of named":
        ('        for x, g in dark:\n            print(f"    ? {x}\\n      ← dark gate: {g}")', '        pass'),
    "O14 a bare stem counts as a reference (an ordinary word excuses an unreferenced module)":
        ('        if mod in r or site_path in r:', '        if mod in r or site_path in r or mod.rpartition(".")[2] in r:'),
    "O15 a gate newly dark on the branch isn't counted (a2 #37112's CREATEROLE skip reads REGRESSED)":
        ('dark_gates = sorted(set(both) | (set(b["unverified"]) - set(m["unverified"])))', 'dark_gates = sorted(set(both))'),
    "O16 production never hands report() the references (the excuse is dead code)":
        ('        rc = report(sha, sums, witness, est, refs=gate_refs(repo["branch"]))', '        rc = report(sha, sums, witness, est)'),
    "O17 a nested import is missed (only module-level imports are read)":
        ('        for n in ast.walk(tree):\n            if isinstance(n, ast.Import):',
         '        for n in tree.body:\n            if isinstance(n, ast.Import):'),
    "O18 any string constant counts as a reference (data names excuse modules nothing runs: a3 #38259)":
        ('            elif isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) in LOADERS:\n'
         '                refs |= {a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}',
         '            elif isinstance(n, ast.Constant) and isinstance(n.value, str):\n'
         '                refs.add(n.value)'),
    "O19 a loader's string argument is ignored (an importlib-loaded subject is never covered)":
        ('LOADERS = frozenset({"import_module", "spec_from_file_location", "run_module", "run_path", "find_spec"})',
         'LOADERS = frozenset()'),
}
