"""Authored mutants for devtools/branch_check.py (plan-4918 P2), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_branch_check.py

NOT authored, and declared: (1) removing the P0-b call would run a full prod dump first, beyond mutation_probe's
per-oracle budget; require_hardened itself is mutation-tested in tests/mutants_branch_check_prep.py. (2) The
FLAKY rerun lives inside a full two-suite run; its first real exercise is the first end-to-end run.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "devtools" / "branch_check.py"
ORACLE = REPO / "tests" / "test_branch_check.py"
ENV = "BRANCH_CHECK_SRC"

# DECLARED, not authored: the rerun's sqlguard intersection in run() (a branch-only finding must reproduce).
# run() is exercised end to end only by a real run, never by this oracle; its arm is the next e2e run's report.
MUTANTS = {
    # a3 #61231 / seed #61236: a missing or unvouched trace dir is UNWITNESSED, never a clean zero
    "U1 a trace dir without run_id (or no dir at all) reads as a clean zero":
        ('    if not trace_dir.is_dir() or not (trace_dir / "run_id").is_file():\n        return None\n', ""),
    "U2 a clean differential over an unwitnessed side PASSes (rc 0)":
        ("    return 77 if unwitnessed else 0", "    return 0"),
    "U4 an unwitnessed rerun erases the first run's known prod write (a4 #61241)":
        ("    return sum(known) if any(known) or len(known) == 2 else None",
         "    return None if w1 is None or w2 is None else w1 + w2"),
    "U5 an unwitnessed part with no known write reads as a clean 0":
        ("    return sum(known) if any(known) or len(known) == 2 else None", "    return sum(known)"),
    "U6 run() bypasses combine_witness at the call site (07ab603's inline sum back: a4 #61241 advisory)":
        ('            witness["branch"] = combine_witness(witness["branch"], w2)',
         '            witness["branch"] = None if witness["branch"] is None or w2 is None else witness["branch"] + w2'),
    "U3 an unwitnessed side is never named":
        ("    gone = [side for side, n in witness.items() if n is None]", "    gone = []"),
    "O1 a statement reaching PROD doesn't fail the run":
        ("    return any(witness.values())", "    return False"),
    "O2 FLAKY is counted as REGRESSED":
        ("    regressed = sorted(set(b[\"failed\"]) - set(m[\"failed\"]))",
         "    regressed = sorted((set(b[\"failed\"]) | set(b.get(\"flaky\", []))) - set(m[\"failed\"]))"),
    # O3 (ANSI strip) and O5 (the walk stops at a non-header line) moved with summary() to devtools/check_verdict.py
    # (a4 10-25, a1 #62905): see tests/mutants_check_verdict.py, which declares both EQUIVALENT on check.sh's printer
    "O4 the witness counts every statement, not just the prod database's":
        ("    return sum(1 for r in witness_traces(str(trace_dir)) if r.get(\"db\") == prod_db)",
         "    return sum(1 for r in witness_traces(str(trace_dir)) if r.get(\"db\"))"),
    "O6 gates failing on BOTH sides aren't reported":
        ('    dead = sorted((set(m["failed"]) & set(b["failed"])) - ({SQLGUARD_GATE} if judged else set()))', '    dead = []'),
    # O7 (the walk has no top edge) moved to tests/mutants_check_verdict.py as V4, with summary()
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
        ('        rc = report(sha, sums, witness, est, refs=gate_refs(repo["branch"]), touched=touched_files(sha, repo["branch"]),',
         '        rc = report(sha, sums, witness, est, touched=touched_files(sha, repo["branch"]),'),
    "O17 a nested import is missed (only module-level imports are read)":
        ('    for n in ast.walk(tree):\n        if isinstance(n, ast.Import):',
         '    for n in tree.body:\n        if isinstance(n, ast.Import):'),
    "O18 any string constant counts as a reference (data names excuse modules nothing runs: a3 #38259)":
        ('        elif isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) in LOADERS:\n'
         '            refs |= {a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}',
         '        elif isinstance(n, ast.Constant) and isinstance(n.value, str):\n'
         '            refs.add(n.value)'),
    "O19 a loader's string argument is ignored (an importlib-loaded subject is never covered)":
        ('LOADERS = frozenset({"import_module", "spec_from_file_location", "run_module", "run_path", "find_spec"})',
         'LOADERS = frozenset()'),
    "O20 every main red is called CLEARED (a2 night-review 10-11: the per-site differential lies)":
        ("        cleared = sorted(l for i, l in mr.items() if i not in br)", "        cleared = sorted(mr.values())"),
    "O21 every red on both sides is called in-scope (an untouched file's debt is pinned on the branch)":
        ("        standing = sorted(l for i, l in br.items() if i in mr and sqlguard_module(l) in (touched or set()))",
         "        standing = sorted(l for i, l in br.items() if i in mr)"),
    "O22 production never hands report() the branch's scope (the in-scope list is dead code)":
        (', touched=touched_files(sha, repo["branch"]),', ","),
    "O23 the scope drops the modules a changed oracle imports (voice_mint::record, 10-11, falls out of scope)":
        ('        out |= {_modfile(m) for m in module_refs(tree)}', "        pass"),
    "O24 the scope diffs two trees, not from the merge-base (main's drift past the fork is pinned on the branch: a4 #45033)":
        ("[\"git\", \"diff\", \"--name-only\", f\"{sha['main']}...{sha['branch']}\"]",
         '["git", "diff", "--name-only", sha["main"], sha["branch"]]'),
    "O25 an extractor red (a FILE, no '::') never reaches the in-scope list (a4 #45033 F2)":
        (' or re.match(r"R-EXTRACT (\\S+?):?(?:\\s|$)", line)', ""),
    "O28 check.sh isn't left out (every branch that adds a gate puts half the dark list in scope)":
        ('SCOPE_NOISE = frozenset({"devtools/check.sh"})', "SCOPE_NOISE = frozenset()"),
    "O30 a label carrying \\\" is kept escaped (never matches what check.sh prints)":
        ("        label = label.replace('\\\\\"', '\"')", "        pass"),
    "O31 production never hands report() the oracles (the in-scope list is dead code)":
        ("\n                    oracles=gate_files(repo[\"branch\"]), changed=changed_files(sha), repo=repo[\"branch\"],", ""),
    "O26 a file the oracle NAMES isn't followed (only imports: the 10-11 node oracle naming server.mjs is missed)":
        ("            for name in _NAMED_RX.findall(t):\n                for q in idx.get(name, ()):\n"
         "                    seeds.setdefault(q, q)\n", ""),
    "O27 a bare WORD counts as a file reference (every oracle that says 'server' reaches server.mjs)":
        ("            for name in _NAMED_RX.findall(t):",
         "            for name in _NAMED_RX.findall(t) + [w + \".mjs\" for w in re.findall(r\"\\w+\", t)]:"),
    "O29 a CHANGED oracle isn't itself in scope":
        ("            seeds.setdefault(o, None)\n", ""),
    "O32 the name match is a SUBSTRING (reserver.mjs reads as server.mjs)":
        ("            for name in _NAMED_RX.findall(t):", "            for name in [n for n in idx if n in t]:"),
    "O33 no TRANSITIVE step (a sibling server.mjs imports is out of scope: a4 #49641)":
        ("        reached, todo = dict(seeds), list(seeds)", "        reached, todo = dict(seeds), []"),
    "O34 js/mjs imports are never read (the node side of the closure is dead)":
        ("        for spec in _JS_IMPORT_RX.findall(text):", "        for spec in []:"),
    "O35 the census is never consulted (an ADDED nucleus script with a dark reachability gate reads no line: 10-12)":
        ("        census = _census_hit(g, oracles, read, members or set())", "        census = None"),
    "O36 a REPO-WIDE census (git ls-files) isn't recognised":
        ("        if _REPO_WIDE_RX.search(t):", "        if False:"),
    "O37 a dir census matches by STRING prefix ('unitsX/' reads as 'units/')":
        ('            m = next((m for m in sorted(members) if m.startswith(d + "/")), None)',
         "            m = next((m for m in sorted(members) if m.startswith(d)), None)"),
    "O38 a MODIFIED file counts as a membership change (every edit-only branch flags every dark census)":
        ('        if parts and parts[0][:1] in "ADRC":', '        if parts and parts[0][:1] in "ADRCM":'),
    "O39 a rename keeps only its NEW side (the old path's removal from a census is missed)":
        ("            out |= set(parts[1:])", "            out |= set(parts[-1:])"),
    "O40 production never hands report() the membership changes (the census line is dead code)":
        (",\n                    members=membership_changes(sha))", ")"),
    "O41 a side with no verdict line is compared anyway (an empty branch side reads as no regression)":
        ('    dead = [s for s in ("main", "branch") if not sums[s].get("line")]', "    dead = []"),
    "O42 only the MAIN side's verdict is required (a dead branch suite still reads clean)":
        ('    dead = [s for s in ("main", "branch") if not sums[s].get("line")]',
         '    dead = [s for s in ("main",) if not sums[s].get("line")]'),
    "O43 the dead side's refusal is not a refusal (rc 0: the run reads as a pass)":
        ("        return 1 if _estate_and_witness(est, witness) else 77",
         "        return 1 if _estate_and_witness(est, witness) else 0"),
    "O44 NO VERDICT returns before the WITNESS (a suite that wrote to prod and then died reads as unknown; a4 #53077)":
        ("        return 1 if _estate_and_witness(est, witness) else 77", "        return 77"),
    "O45 a suite past SUITE_TIMEOUT is a traceback again (that side's trace, and its prod writes, never read)":
        ("    except subprocess.TimeoutExpired as e:", "    except OSError as e:"),
    "O46 a timed-out suite's partial output is dropped (its rc is still 'timeout', its sets nothing)":
        ("        return dec(e.stdout), dec(e.stderr), \"timeout\"", "        return \"\", dec(e.stderr), \"timeout\""),
    "O47 run() calls check.sh directly again, around run_suite":
        ('                stdout, stderr, rc = run_suite(a + ["bash", "devtools/check.sh"], env)',
         '                stdout, stderr, rc = (lambda p: (p.stdout, p.stderr, p.returncode))(subprocess.run(a + ["bash", '
         '"devtools/check.sh"], env=env, capture_output=True, text=True, timeout=SUITE_TIMEOUT))'),
    "O48 a run line with run()'s --cap=<s> flag is no gate again (test_relay.py dark to every dark list and the census)":
        ('_GATE_RX = re.compile(r\'^[ \\t]*run (?:--cap=\\S+\\s+)?"((?:[^"\\\\]|\\\\.)+)"\\s+(.*)$\', re.M)', '_GATE_RX = re.compile(r\'^[ \\t]*run "((?:[^"\\\\]|\\\\.)+)"\\s+(.*)$\', re.M)'),
    "O49 an INDENTED run line is no gate again (a gate inside an `if`: check.sh's media decode)":
        ('_GATE_RX = re.compile(r\'^[ \\t]*run (?:--cap=\\S+\\s+)?"((?:[^"\\\\]|\\\\.)+)"\\s+(.*)$\', re.M)', '_GATE_RX = re.compile(r\'^run (?:--cap=\\S+\\s+)?"((?:[^"\\\\]|\\\\.)+)"\\s+(.*)$\', re.M)'),
    "O50 run_calls finds a call only at LINE START again (a chained `&& run` or `then run` gate goes dark silently)":
        ('_RUN_CALL_RX = re.compile(r"(?:^|[;&|(]|\\b(?:then|do|else|elif))\\s*run\\s")', '_RUN_CALL_RX = re.compile(r"^[ \\t]*run\\s")'),
}
