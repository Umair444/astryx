#!/usr/bin/env python3
"""branch_check orchestrator oracle (plan-4918 P2): the verdict is check.sh's own sets compared (never a verdict of
the tool's own), FLAKY is not REGRESSED, a prod-reaching statement fails the run, and on an UNHARDENED host the run
REFUSES (rc 77, naming seed's P0-a) and leaves nothing behind. Exits 77 without a DSN.
"""
import contextlib
import io
import json
import os
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
        from nucleus import branch_check as bc
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
    def rep(main, branch, witness=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bc.report(sha, {"main": main, "branch": branch}, witness or {"main": 0, "branch": 0}, est)
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
    cs = (REPO / "nucleus" / "check.sh").read_text()
    check("SQLGUARD_GATE is exactly check.sh's own label for the enforce gate",
          f'run "{sg}" "$PY" -m nucleus.sqlguard.enforce' in cs)
    esrc = os.environ.get("ENFORCE_SRC")                              # mutation_probe points this at a mutant
    if esrc:
        import importlib.util
        esp = importlib.util.spec_from_file_location("enforce_under_test", esrc)
        enf = importlib.util.module_from_spec(esp)
        esp.loader.exec_module(enf)
    else:
        from nucleus.sqlguard import enforce as enf
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
    from nucleus import branch_check_prep as prep
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
        check("on an unhardened host the run REFUSES (rc 77) naming seed's P0-a REVOKE", rc == 77 and "REVOKE CONNECT" in out,
              out[-300:])
        check("…and the refusal leaves no role, database or scope behind", left == 0 and "LEAK" not in out, f"roles={left}")
    else:
        print("  NOTE  the host is hardened (P0-a applied): the refusal arm doesn't apply; the full run is the check.")
    adm.close()
    print(f"\n{'FAIL' if fails else 'PASS'}: branch_check orchestrator ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
