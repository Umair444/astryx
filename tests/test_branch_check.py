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
