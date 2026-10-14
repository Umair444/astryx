#!/usr/bin/env python3
"""branch_check orchestrator oracle (plan-4918 P2): the verdict is check.sh's own sets compared (never a verdict of
the tool's own), FLAKY is not REGRESSED, a prod-reaching statement fails the run, and on an UNHARDENED host the run
REFUSES (rc 77, naming seed's P0-a) and leaves nothing behind. Exits 77 without a DSN.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


LOG = ("\x1b[36m▶\x1b[0m gate a\n  ✓ gate a\n"
       "FAILED (2):\n  \x1b[31m✗\x1b[0m gate b\n  ✗ gate c\n"
       "UNVERIFIED (1) — this run did NOT check these; they are not evidence of anything:\n  ○ gate d\n"
       "\ncheck: 40 verified, 2 FAILED, 1 UNVERIFIED\n")


def main():
    # The subject imports psycopg at module top (via prep/runscope too). An estate-absent tree (pushed_tree_check:
    # committed files, PY=python3, no venv) has none, and that's NOT SEARCHED, never a FAIL (seed #33386). Probed
    # alone, so the subject's own import errors still fail loudly.
    try:
        import psycopg  # noqa: F401
    except ModuleNotFoundError as e:                                  # absent → 77; INSTALLED but broken → FAIL (a3)
        if e.name != "psycopg":
            raise
        print(f"NOT SEARCHED: psycopg is not importable by {sys.executable} ({e}); no arm ran.")
        return 77
    src = os.environ.get("BRANCH_CHECK_SRC")                          # mutation_probe points this at a mutant copy
    if src:
        import importlib.util
        spec = importlib.util.spec_from_file_location("bc_under_test", src)
        bc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bc)
    else:
        from devtools import branch_check as bc
    s = bc.summary(LOG)
    check("summary: check.sh's own FAILED/UNVERIFIED sets and verdict line, ANSI stripped",
          s["failed"] == ["gate b", "gate c"] and s["unverified"] == ["gate d"] and s["line"].startswith("check: 40"),
          str(s))
    # a GATE's own output can look like the summary (econ provenance prints "FAILED (3): …", first e2e #33638)
    # …and one in check.sh's EXACT shape (test_check_verdict drives check.sh's own summary() and prints one)
    noisy = ("\x1b[36m▶\x1b[0m gate e\nFAILED (3): x; y; z\n  ✗ injected by a gate\n  ✗ gate e\n"
             "\x1b[36m▶\x1b[0m gate v\nFAILED (1):\n  ✗ injected in check.sh's own shape\n  ✓ gate v\n" + LOG)
    s = bc.summary(noisy)
    check("summary reads ONLY check.sh's final block: a gate's own 'FAILED (n): …' and ✗ lines are never read",
          s["failed"] == ["gate b", "gate c"] and s["unverified"] == ["gate d"], str(s))
    # the LAST gate's output ending in check.sh's exact shape, directly above verdict()'s blank (a3 S1 #33654)
    tail = ("\x1b[36m▶\x1b[0m last gate\nFAILED (1):\n  ✗ injected-name\n  ✗ last gate\n"
            "\nFAILED (1):\n  ✗ last gate\n\ncheck: FAILURES above — a committed invariant regressed\n")
    s = bc.summary(tail)
    check("the walk stops at verdict()'s leading blank: the last gate's own block above it is never read",
          s["failed"] == ["last gate"], str(s))
    s = bc.summary("  ✗ stray\ncheck: ALL CODE INVARIANTS PASS (3 gates verified)\n")
    check("…and a clean run's summary has no FAILED set even after stray ✗ output", s["failed"] == [], str(s))
    est = {"branch": {"skipped_credential": []}}
    sha = {"main": "a" * 40, "branch": "b" * 40}
    def rep(main, branch, witness=None, refs=None, touched=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bc.report(sha, {"main": main, "branch": branch}, witness or {"main": 0, "branch": 0}, est, refs=refs,
                           touched=touched)
        return rc, buf.getvalue()
    base = {"failed": ["x"], "unverified": ["u"], "line": "check: m"}
    rc, out = rep(base, {"failed": ["x", "y"], "unverified": ["u"], "line": "check: b"})
    check("a gate failing on the branch but not main is REGRESSED → rc 1", rc == 1 and "REGRESSED" in out and "    y" in out,
          out)
    rc, out = rep(base, {"failed": ["x"], "flaky": ["y"], "unverified": ["u"], "line": "check: b"})
    check("a failure that didn't reproduce is FLAKY: named, not counted → rc 0", rc == 0 and "FLAKY" in out and "    y" in out,
          out)
    rc, out = rep(base, {"failed": ["x"], "unverified": ["u"], "line": "check: b"}, {"main": 0, "branch": 3})
    check("any statement reaching the PROD database fails the run → rc 1", rc == 1 and "WITNESS" in out, out)
    rc, out = rep(base, dict(base))
    check("identical sides → rc 0, each side's check.sh verdict line quoted, the shared VERIFIED NOTHING listed",
          rc == 0 and "check: m" in out and "VERIFIED NOTHING under branch_check" in out and "○ u" in out, out)
    check("a gate FAILING ON BOTH SIDES is listed by name (\"no regression\" over dead gates isn't coverage)",
          "FAILED ON BOTH SIDES" in out and "    ✗ x" in out, out)
    # ── steward 10-15: a side whose suite never printed check.sh's verdict compares NOTHING ─────────────────────────
    dead = {"failed": [], "unverified": [], "line": "", "rc": -9}
    rc, out = rep(base, dict(dead))
    check("an empty BRANCH side (no verdict line) is NO VERDICT → rc 77, never 'no regression' (rc 0)",
          rc == 77 and "NO VERDICT from the branch suite" in out and "rc -9" in out and "fixed by the branch" not in out,
          out)
    rc, out = rep(dict(dead), {"failed": ["x", "y"], "unverified": ["u"], "line": "check: b"})
    check("an empty MAIN side is NO VERDICT → rc 77, its branch failures never named REGRESSED",
          rc == 77 and "NO VERDICT from the main suite" in out and "REGRESSED" not in out, out)
    # ── a3 D1 #35480: PRODUCTION sweeps org-wide (only=None); only an oracle scopes its sweep to its own roles ─────
    import ast
    srcp = Path(os.environ.get("BRANCH_CHECK_SRC") or (REPO / "devtools" / "branch_check.py"))
    runfn = next(n for n in ast.walk(ast.parse(srcp.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "run")
    sweeps = [c for c in ast.walk(runfn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
              and c.func.attr == "sweep"]
    reps = [c for c in ast.walk(runfn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "report"]
    check("branch_check.run passes report() the BRANCH's oracle references (refs=gate_refs(repo['branch']))",
          len(reps) == 1 and any(k.arg == "refs" and "gate_refs" in ast.dump(k.value) and "'branch'" in ast.unparse(k.value)
                                 for k in reps[0].keywords), ast.dump(reps[0]) if reps else "no report call in run()")
    check("branch_check.run calls sweep() with NO `only` (the org-wide orphan sweep production needs)",
          len(sweeps) == 1 and not any(k.arg == "only" for k in sweeps[0].keywords),
          ast.dump(sweeps[0]) if sweeps else "no sweep call in run()")

    # ── sqlguard judged DIFFERENTIALLY by identity (plan-4918 D4, a3 C4) ─────────────────────────────────────
    sg = bc.SQLGUARD_GATE
    base_sg = {"failed": [sg], "unverified": [], "line": "check: m", "sqlguard_red": {"id1": "R-BLIND a.py::f (line 10)"}}
    shifted = {"failed": [sg], "unverified": [], "line": "check: b", "sqlguard_red": {"id1": "R-BLIND a.py::f (line 99)"}}
    rc, out = rep(base_sg, shifted)
    check("C4: two sides differing only by a LINE offset → no regression, and sqlguard isn't listed as dead",
          rc == 0 and "REGRESSED" not in out and "judged DIFFERENTIALLY" in out
          and f"    ✗ {sg}" not in out, out)
    grown = {**shifted, "sqlguard_red": {"id1": "R-BLIND a.py::f", "id2": "R-NEW b.py::g :: select 2"}}
    rc, out = rep(base_sg, grown)
    check("D4: a RED only on the branch is a REGRESSION, named by its line → rc 1",
          rc == 1 and "REGRESSED" in out and "R-NEW b.py::g :: select 2" in out, out)
    # a2 night-review 10-11: the per-site differential — main's reds the branch clears, and reds left in touched files
    two = {**base_sg, "sqlguard_red": {"id1": "R-BLIND a.py::f", "k1": "R-NEW k.py::g :: select 7", "s1": "R-NEW s.py::h :: select 8"}}
    one = {**shifted, "sqlguard_red": {"id1": "R-BLIND a.py::f", "s1": "R-NEW s.py::h :: select 8"}}
    rc, out = rep(two, one, touched={"s.py", "k.py"})
    check("a site RED on main and gone on the branch is listed as CLEARED, rc 0",
          rc == 0 and "sqlguard sites the branch CLEARS: 1" in out and "    R-NEW k.py::g :: select 7" in out, out)
    check("…a site RED on both sides in a file the branch touches is listed as still RED; one in an untouched file is not",
          "sqlguard sites still RED in the branch's scope (files it changes, modules they import): 1" in out and "    R-NEW s.py::h :: select 8" in out
          and "R-BLIND a.py::f" not in out.split("still RED in the branch")[1], out)
    rc, out = rep(two, one)
    check("…with no touched set, nothing is called still-RED-in-touched (never a guess)",
          rc == 0 and "still RED in the branch" not in out, out)
    check("branch_check.run passes report() the branch's scope (touched=touched_files(sha, repo['branch']))",
          len(reps) == 1 and any(k.arg == "touched" and "touched_files" in ast.dump(k.value)
                                 and "'branch'" in ast.unparse(k.value) for k in reps[0].keywords),
          ast.dump(reps[0]) if reps else "no report call in run()")
    tsc = Path(tempfile.mkdtemp(prefix="bc-scope-"))
    (tsc / "tests").mkdir()
    (tsc / "tests" / "test_x.py").write_text("from astryx.hearing import voice_mint as V\nimport nucleus.other\n")
    real = subprocess.run
    diffs = []
    def fake_git(argv, **kw):
        if argv[:3] == ["git", "diff", "--name-only"]:
            diffs.append(argv[3:])
            return subprocess.CompletedProcess(argv, 0, "tests/test_x.py\nREADME.md\n", "")
        return real(argv, **kw)
    bc.subprocess.run = fake_git
    try:
        scope = bc.touched_files({"main": "m", "branch": "b"}, tsc)
    finally:
        bc.subprocess.run = real
    check("the scope is the changed files PLUS the modules a changed .py imports (a red the new oracle drives)",
          {"tests/test_x.py", "README.md", "src/astryx/hearing/voice_mint.py", "nucleus/other.py"} <= scope, sorted(scope))
    check("…diffed from the MERGE-BASE (main...branch, three dots), so main's drift past the fork isn't the branch's (a4 #45033)",
          diffs == [["m...b"]], diffs)
    ext = {"x1": "R-EXTRACT tests/test_x.py: listed 9d > 7d (trip: g)", "x2": "R-EXTRACT tests/test_y.py builds an UNSTAMPED fixture"}
    rc, out = rep({**base_sg, "sqlguard_red": ext}, {**shifted, "sqlguard_red": ext}, touched={"tests/test_x.py", "tests/test_y.py"})
    check("an R-EXTRACT red (a FILE, no '::', either form) in the branch's scope is listed as still RED (a4 #45033 F2)",
          "still RED in the branch's scope (files it changes, modules they import): 2" in out, out)
    # a2 night-review 10-12: a DARK gate whose oracle references a file the branch changes is named, to be run directly
    # (10-11: seed/trigger-name-guard PASSed while the ear/wake/doorbell oracles, which stage channel/server.mjs, were dark)
    dk = Path(tempfile.mkdtemp(prefix="bc-dark-"))
    for d in ("nucleus", "tests", "channel", "devtools"):
        (dk / d).mkdir()
    (dk / "devtools" / "check.sh").write_text(
        'run "ear gate" "$PY" tests/test_ear.py\n'
        'run "node gate" node tests/t_node.mjs\n'
        'run "bash gate" bash tests/t_sh.sh\n'
        'run "word gate" "$PY" tests/test_word.py\n'
        'run "own gate" "$PY" -m tests.test_own\n'
        'run "quoted \\"=ax\\" gate" "$PY" tests/test_word.py\n')
    (dk / "tests" / "test_ear.py").write_text("from nucleus import subj\n")
    (dk / "nucleus" / "subj.py").write_text("from nucleus import deep\n")
    (dk / "nucleus" / "deep.py").write_text("x = 1\n")
    (dk / "channel" / "server.mjs").write_text("import { f } from './sib.mjs'\nconst g = await import('./lazy.mjs')\n")
    (dk / "channel" / "sib.mjs").write_text("export const f = 1\n")
    (dk / "channel" / "lazy.mjs").write_text("export const g = 1\n")
    (dk / "tests" / "t_node.mjs").write_text("const s = new URL('../channel/server.mjs', import.meta.url)\n")
    (dk / "tests" / "t_sh.sh").write_text("grep -c ^run devtools/check.sh\n")   # names check.sh, as many oracles do
    (dk / "tests" / "test_word.py").write_text("# the server answers; reserver.mjs is another file\n")
    (dk / "tests" / "test_own.py").write_text("x = 1\n")
    of = bc.gate_files(dk)
    check("gate_files: every run line maps to its oracle file(s), any language, -m included, a \\\" label unescaped",
          of.get("ear gate") == {"tests/test_ear.py"} and of.get("node gate") == {"tests/t_node.mjs"}
          and of.get("own gate") == {"tests/test_own.py"} and 'quoted "=ax" gate' in of, of)
    gates = ["ear gate", "node gate", "bash gate", "word gate", "own gate"]
    ds = {g: f for g, f, _ in bc.dark_scope(gates, of, {"nucleus/subj.py", "channel/server.mjs", "tests/test_own.py"}, dk)}
    check("dark_scope: a python oracle IMPORTING a changed module, a node oracle NAMING a changed file, and a changed "
          "oracle itself are each in scope", ds.get("ear gate") == "nucleus/subj.py"
          and ds.get("node gate") == "channel/server.mjs" and ds.get("own gate") == "tests/test_own.py", ds)
    check("…a bare stem ('server') or a longer name containing the file's ('reserver.mjs') is NOT a reference, and an "
          "unrelated oracle isn't named", "word gate" not in ds and "bash gate" not in ds, ds)
    check("…a branch that only touches check.sh (every branch adding a gate does) puts no dark gate in scope",
          bc.dark_scope(gates, of, {"devtools/check.sh"}, dk) == [], bc.dark_scope(gates, of, {"devtools/check.sh"}, dk))
    tr = {g: (f, v) for g, f, v in bc.dark_scope(gates, of, {"channel/sib.mjs", "nucleus/deep.py"}, dk)}
    check("a4 #49641: TRANSITIVE — a node oracle naming server.mjs reaches a sibling server.mjs IMPORTS, and a python "
          "oracle reaches a module its import imports; each named with the file it came through",
          tr.get("node gate") == ("channel/sib.mjs", "channel/server.mjs")
          and tr.get("ear gate") == ("nucleus/deep.py", "nucleus/subj.py") and "bash gate" not in tr, tr)
    lz = {g: f for g, f, _ in bc.dark_scope(gates, of, {"channel/lazy.mjs"}, dk)}
    check("…a DYNAMIC import('./x.mjs') is followed too", lz.get("node gate") == "channel/lazy.mjs", lz)
    # a2 night-review 10-14: a CENSUS oracle reaches files by ENUMERATING (git ls-files, a dir glob), not by name;
    # only a MEMBERSHIP change (add/delete/rename) changes its set. 10-12: reachability was dark when review_range.sh
    # was ADDED invoked-by-nothing.
    cz = Path(tempfile.mkdtemp(prefix="bc-census-"))
    for d in ("nucleus", "tests", "units", "devtools"):
        (cz / d).mkdir()
    (cz / "devtools" / "check.sh").write_text('run "repo census" "$PY" tests/test_rw.py\n'
                                             'run "units census" "$PY" tests/test_units.py\n'
                                             'run "plain gate" "$PY" tests/test_plain.py\n')
    (cz / "tests" / "test_rw.py").write_text('import subprocess\nfiles = subprocess.run(["git", "ls-files"]).stdout\n')
    (cz / "tests" / "test_units.py").write_text('for f in (REPO / "units").glob("*.service"):\n    pass\n')
    (cz / "tests" / "test_plain.py").write_text("x = 1\n")
    cof = bc.gate_files(cz)
    cg = ["repo census", "units census", "plain gate"]
    added = {g: (f, why) for g, f, why in bc.dark_scope(cg, cof, {"nucleus/new_tool.sh"}, cz, members={"nucleus/new_tool.sh"})}
    check("an ADDED file puts a dark REPO-WIDE census in scope (git ls-files), named as a census; a dir census of "
          "another dir and a plain oracle are not", set(added) == {"repo census"}
          and added["repo census"][0] == "nucleus/new_tool.sh" and "REPO-WIDE census" in added["repo census"][1], added)
    unit = {g for g, _, _ in bc.dark_scope(cg, cof, {"units/x.service"}, cz, members={"units/x.service"})}
    check("…a file added under the dir a census globs puts THAT census in scope", unit == {"repo census", "units census"}, unit)
    edit = bc.dark_scope(cg, cof, {"nucleus/new_tool.sh", "units/x.service"}, cz, members=set())
    check("…a MODIFIED file (no membership change) puts no census in scope: edit-only branches stay quiet", edit == [], edit)
    near = {g for g, _, _ in bc.dark_scope(cg, cof, {"unitsX/y.service"}, cz, members={"unitsX/y.service"})}
    check("…a dir census matches its dir by PATH PREFIX, not a string prefix ('unitsX/' isn't 'units/')",
          "units census" not in near, near)
    check("branch_check.run passes report() the branch's membership changes (members=membership_changes(sha))",
          len(reps) == 1 and any(k.arg == "members" and "membership_changes" in ast.dump(k.value)
                                 for k in reps[0].keywords), ast.dump(reps[0]) if reps else "no report call in run()")
    real = subprocess.run
    def fake_status(argv, **kw):
        if argv[:3] == ["git", "diff", "--name-status"]:
            return subprocess.CompletedProcess(argv, 0, "M\ta.py\nA\tb.sh\nD\tc.py\nR087\told.py\tnew.py\n", "")
        return real(argv, **kw)
    bc.subprocess.run = fake_status
    try:
        mem = bc.membership_changes({"main": "m", "branch": "b"})
    finally:
        bc.subprocess.run = real
    check("membership_changes: added, deleted and BOTH sides of a rename; a modified file is not a membership change",
          mem == {"b.sh", "c.py", "old.py", "new.py"}, mem)
    dm = {"failed": [], "unverified": ["node gate", "bash gate"], "line": "check: m"}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = bc.report(sha, {"main": dm, "branch": dict(dm)}, {"main": 0, "branch": 0}, est,
                       oracles=of, changed={"channel/server.mjs"}, repo=dk)
    out = buf.getvalue()
    check("report names the dark gate IN SCOPE with the file it references, and the rc is unchanged (report-only)",
          rc == 0 and "VERIFIED NOTHING and IN SCOPE" in out and "    ○ node gate\n      ← channel/server.mjs" in out
          and "○ bash gate\n      ←" not in out, out)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bc.report(sha, {"main": dm, "branch": dict(dm)}, {"main": 0, "branch": 0}, est)
    check("…with no changed set, nothing is called in scope (never a guess)", "IN SCOPE" not in buf.getvalue(),
          buf.getvalue())
    check("branch_check.run passes report() the branch's oracles and changed files (oracles=gate_files(repo['branch']), "
          "changed=changed_files(sha))",
          len(reps) == 1 and any(k.arg == "oracles" and "gate_files" in ast.dump(k.value)
                                 and "'branch'" in ast.unparse(k.value) for k in reps[0].keywords)
          and any(k.arg == "changed" and "changed_files" in ast.dump(k.value) for k in reps[0].keywords),
          ast.dump(reps[0]) if reps else "no report call in run()")
    # a4 #36860 + a2 #37119: an UNEXECUTED branch-only R-NEW is UNVERIFIABLE HERE only when a gate that verified
    # nothing has an ORACLE REFERENCING the site's module (a relation, not co-occurrence); else it's REGRESSED
    unex = "R-NEW c.py::h :: select 3: UNEXECUTED and not in the ledger. Make it RESPONSIVE, or admit it"
    exed = "R-NEW c.py::k :: select 4: EXECUTED and not in the ledger. Make it RESPONSIVE, or admit it"
    orphan = "R-NEW z.py::q :: select 5: UNEXECUTED and not in the ledger. Make it RESPONSIVE, or admit it"
    refs = {"prep gate": {"c", "os"}, "other gate": {"y"}}
    darkm = {**base_sg, "unverified": ["prep gate", "other gate"]}
    darkb = {**shifted, "unverified": ["prep gate", "other gate"]}
    rc, out = rep(darkm, {**darkb, "sqlguard_red": {"id1": "R-BLIND a.py::f", "u": unex}}, refs=refs)
    check("an UNEXECUTED R-NEW whose module a DARK gate's oracle references is UNVERIFIABLE HERE, naming that gate "
          "and the live decider → rc 0", rc == 0 and "UNVERIFIABLE HERE" in out and f"? {unex}" in out
          and "← dark gate: prep gate" in out and "REGRESSED" not in out and "sqlguard.judge" in out, out)
    rc, out = rep(darkm, {**darkb, "sqlguard_red": {"id1": "R-BLIND a.py::f", "o": orphan}}, refs=refs)
    check("a2 RED: an UNEXECUTED R-NEW in a module NO dark oracle references is REGRESSED, though gates are dark → rc 1",
          rc == 1 and "REGRESSED" in out and orphan in out and "UNVERIFIABLE" not in out, out)
    rc, out = rep(darkm, {**darkb, "sqlguard_red": {"id1": "R-BLIND a.py::f", "e": exed}}, refs=refs)
    check("…an EXECUTED unlisted one (its oracle ran) stays REGRESSED → rc 1",
          rc == 1 and "REGRESSED" in out and exed in out and "UNVERIFIABLE" not in out, out)
    rc, out = rep(base_sg, {**shifted, "sqlguard_red": {"id1": "R-BLIND a.py::f", "u": unex}}, refs=refs)
    check("…and with NO dark gate, a referenced UNEXECUTED one is REGRESSED → rc 1",
          rc == 1 and "REGRESSED" in out and unex in out and "UNVERIFIABLE" not in out, out)
    rc, out = rep(base_sg, {**shifted, "unverified": ["prep gate"], "sqlguard_red": {"id1": "R-BLIND a.py::f", "u": unex}},
                  refs=refs)
    check("a gate NEWLY unverified on the branch (a2 #37112: CREATEROLE missing) counts as dark → UNVERIFIABLE, rc 0",
          rc == 0 and "← dark gate: prep gate" in out and "REGRESSED" not in out, out)
    # the relation, read statically from a repo's check.sh and oracle files
    tdr = Path(tempfile.mkdtemp(prefix="bc-refs-"))
    (tdr / "nucleus").mkdir()
    for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
        (tdr / _d).mkdir(parents=True, exist_ok=True)
    (tdr / "tests").mkdir()
    (tdr / "devtools" / "check.sh").write_text('run "g1" "$PY" tests/t1.py\nrun "g2" "$PY" -m nucleus.t2\n'
                                             'run "g3" "$PY" tests/broken.py\nrun "g4" bash tests/t4.sh\n')
    (tdr / "tests" / "t1.py").write_text("import importlib\ndef f():\n    from nucleus import foo\n"
                                         "B = importlib.import_module('nucleus.bar')\nW = 'canvas'\n"
                                         "T = importlib.import_module('canvas')  # a TOP-LEVEL canvas, not astryx.core.canvas\n"
                                         "SCRIPTS = ('nucleus.qux', 'nucleus/qux.py')\nPATHS = {'k': 'nucleus/qux.py'}\n"
                                         "def g(cg):\n    return cg('nucleus/zed.py')\n")
    (tdr / "nucleus" / "t2.py").write_text("import nucleus.baz as b\n")
    (tdr / "tests" / "broken.py").write_text("def (:\n")
    gr = bc.gate_refs(tdr)
    cg = lambda f: bc.covering_gate(f, ["g1", "g2", "g3", "g4"], gr)
    check("gate_refs: a NESTED `from nucleus import foo`, a LOADER's string argument, and `-m` gates are read; an "
          "unparseable or non-python oracle is omitted (its sites stay RED)",
          cg("nucleus/foo.py") == "g1" and cg("nucleus/bar.py") == "g1" and cg("nucleus/baz.py") == "g2"
          and set(gr) == {"g1", "g2"}, str({k: sorted(v) for k, v in gr.items()}))
    check("covering_gate never matches a BARE WORD ('canvas' in an oracle doesn't cover src/astryx/core/canvas.py)",
          cg("src/astryx/core/canvas.py") is None, str(cg("src/astryx/core/canvas.py")))
    check("a3 #38259: a module named only as DATA (a tuple or dict of names, or a non-loader call's argument) is NOT "
          "covered", cg("nucleus/qux.py") is None and cg("nucleus/zed.py") is None,
          f"qux={cg('nucleus/qux.py')} zed={cg('nucleus/zed.py')}")
    self_refs = bc.gate_refs(REPO).get("branch_check: differential verdict, prod witness, clean refusal", set())
    check("this oracle's own test literals never make it 'cover' what they name (src/astryx/core/canvas.py)",
          "src/astryx/core/canvas.py" not in self_refs and "astryx.core.canvas" not in self_refs, str(sorted(self_refs))[:300])
    cs = (REPO / "devtools" / "check.sh").read_text()
    check("SQLGUARD_GATE is exactly check.sh's own label for the enforce gate",
          f'run "{sg}" "$PY" -m astryx.security.sqlguard.enforce' in cs)
    esrc = os.environ.get("ENFORCE_SRC")                              # mutation_probe points this at a mutant
    if esrc:
        import importlib.util
        esp = importlib.util.spec_from_file_location("enforce_under_test", esrc)
        enf = importlib.util.module_from_spec(esp)
        esp.loader.exec_module(enf)
    else:
        from astryx.security.sqlguard import enforce as enf
    def blind_ids(line, text="select 1"):
        rep_ = {"run_not_searched": [], "extractors": {}, "gates": {}, "covering": {},
                "sites": {enf.CANARY + "\x1fselect 1": {"rung": "RESPONSIVE"}},
                "blind": [{"frame": ["nucleus/x.py", "f", line], "t": text}]}
        return enf.enforce("/nonexistent", ledger={"rows": {}, "extractors": {}},
                           dsn="postgresql://nobody@127.0.0.1:1/x?connect_timeout=2", rep=rep_)["red_ids"]
    a_, b_, c_ = blind_ids(10), blind_ids(99), blind_ids(10, "select 2")
    check("C4: enforce keys an R-BLIND by path/function/text, never its LINE (same id at line 10 and 99)",
          len(a_) == 1 and a_ == b_, f"{a_} {b_}")
    check("…and different SQL at the same place is a different identity", a_ != c_, f"{a_} {c_}")
    td = Path(tempfile.mkdtemp())
    check("sqlguard_red: no red.json (enforce didn't run) → None, never an empty 'no findings'",
          bc.sqlguard_red(td) is None)
    (td / "red.json").write_text(json.dumps([{"id": "x", "line": "R-NEW …"}]))
    check("sqlguard_red: red.json → {id: line}", bc.sqlguard_red(td) == {"x": "R-NEW …"})

    t = Path(tempfile.mkdtemp())
    (t / "trace-1.jsonl").write_text("\n".join(json.dumps({"db": d}) for d in ("astryx", "astryx_fx_1", "astryx")) + "\n")
    check("the prod witness counts only statements whose db IS the prod database", bc.prod_statements(t, "astryx") == 2)

    # ── real estate: today's host is UNHARDENED (default PUBLIC CONNECT), so the run must refuse cleanly ─────
    from test_branch_check_prep import admin_dsn
    dsn = admin_dsn()
    if not dsn:
        print("NOT SEARCHED (real-estate arm): no ASTRYX_DSN.")
        return 1 if fails else 77
    import psycopg
    from devtools import branch_check_prep as prep
    adm = psycopg.connect(dsn, autocommit=True)
    unhardened = prep.unhardened(adm, "no_such_role")
    if unhardened:
        os.environ.setdefault("ASTRYX_DSN", dsn)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bc.run("HEAD", "HEAD")
        out = buf.getvalue()
        # only THIS run's role (bc_<our pid>x<epoch>): a concurrent oracle's scope is not our leak
        left = adm.execute("SELECT count(*) FROM pg_roles WHERE rolname LIKE %s",
                           (f"bc\\_{os.getpid()}x%",)).fetchone()[0]
        # REVOKE advice appears only for a NON-test database; a live oracle's open test DB is named instead (a2 F3)
        check("on an unhardened host the run REFUSES (rc 77) with P0-b's refusal, naming why",
              rc == 77 and "P0-b:" in out and ("REVOKE CONNECT" in out or "Oracle TEST databases" in out), out[-300:])
        check("…and the refusal leaves no role, database or scope behind", left == 0 and "LEAK" not in out, f"roles={left}")
    else:
        print("  NOTE  the host is hardened (P0-a applied): the refusal arm doesn't apply; the full run is the check.")
    adm.close()
    print(f"\n{'FAIL' if fails else 'PASS'}: branch_check orchestrator ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
