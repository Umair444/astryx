#!/usr/bin/env python3
"""sqlguard oracle (goal 4243, B1). Every control on nucleus/sqlguard/DESIGN.md's acceptance list lands here,
RED-first. This file is built up arm by arm, and check.sh starts enforcing only once it is complete, in one act.

    venv/bin/python tests/test_sqlguard.py [ledger.json]      # 0 pass · 1 fail · 77 could-not-run

P1 (a3 #22368, privacy): the TRACKED ledger may carry NO plaintext key whose path git ignores. A site key is
`relpath::qualname␟<normalised SQL>`, so for a gitignored file the key IS derived content, and CLAUDE.md forbids
committing it. Such keys must be sha256 digests. "Ignored" is asked of git, never listed by hand.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def plaintext_ignored_keys(doc: dict) -> set:
    """Files whose plaintext site keys appear in a ledger document although git ignores them."""
    keys = list(doc.get("rows", {})) + list(doc.get("covering", {}))
    paths = sorted({k.split("::", 1)[0] for k in keys if "::" in k and not k.startswith("sha256:")})
    if not paths:
        return set()
    r = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"], cwd=REPO, input="\n".join(paths),
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):
        return None                     # a3 D-P: the authority couldn't answer. That's NOT SEARCHED, never PASS.
    return set(r.stdout.split())


def dp_arms():
    """a3 D-P: privacy.py must FAIL CLOSED when git can't answer. RED against ee495dd (rc 128 read as 'not
    ignored')."""
    import os
    import tempfile
    sys.path.insert(0, str(REPO))
    from nucleus.sqlguard import privacy, ledger
    real_repo, real_path = privacy.REPO, os.environ.get("PATH", "")
    # Test BEHAVIOUR, not the new API: against code without an error list (ee495dd) the arms must FAIL with a
    # name, not crash. A crash is red, but it can't say WHICH property the code violates.
    errs = lambda: list(getattr(privacy, "ERRORS", []))
    clear = lambda: (privacy.ignored.cache_clear(), getattr(privacy, "ERRORS", []).clear())

    def probe(p):                        # an exception is a named FAIL (the authority didn't fail CLOSED)
        try:
            return privacy.ignored(p)
        except Exception as e:
            return f"raised {type(e).__name__}"
    with tempfile.TemporaryDirectory() as nonrepo:
        try:
            privacy.REPO = Path(nonrepo)                                  # (i) outside any git repo → rc 128
            clear()
            check("D-P (i) not-a-repo reads as IGNORED (fails closed)", probe("triggers/zz/a.py") is True)
            check("D-P (i) ...and records a classification error", bool(errs()))
            privacy.REPO = real_repo; os.environ["PATH"] = "/nonexistent"  # (ii) git absent from PATH
            clear()
            check("D-P (ii) git absent reads as IGNORED (fails closed)", probe("triggers/zz/b.py") is True)
            check("D-P (ii) ...and records a classification error", bool(errs()))
            os.environ["PATH"] = real_path
            privacy.REPO = Path(nonrepo)                                  # (iii) a seed write while it's failing
            clear()
            out = Path(nonrepo) / "ledger.json"
            real_ledger, real_judge = ledger.LEDGER, ledger.judge.judge
            ledger.LEDGER = out
            ledger.judge.judge = lambda d: {"sites": {"triggers/zz/c.py::f\x1fselect 1": {"rung": "UNEXECUTED"}},
                                            "run_not_searched": [], "extractors": {}, "covering": {},
                                            "counts": {}, "untraced_children": {}}
            refused = False
            try:
                ledger.seed(nonrepo)
            except SystemExit:
                refused = True
            except Exception:
                refused = False          # a crash isn't a refusal; the file check below decides the rest
            check("D-P (iii) the ledger writer REFUSES while classification failed", refused)
            check("D-P (iii) ...and no ledger file was written", not out.exists())
        finally:
            os.environ["PATH"] = real_path
            privacy.REPO = real_repo; clear()
            try:
                ledger.LEDGER, ledger.judge.judge = real_ledger, real_judge
            except NameError:
                pass


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "nucleus" / "sqlguard" / "ledger.json"
    if not path.exists():
        print("SKIP: no ledger.json to check. Nothing was verified.")
        return 77
    leaked = plaintext_ignored_keys(json.loads(path.read_text()))
    if leaked is None:
        print("NOT SEARCHED: git check-ignore couldn't answer (no usable git repo here). P1 verified nothing.")
        return 77
    check("P1 the tracked ledger carries no plaintext key from a gitignored file", not leaked,
          f"{len(leaked)} gitignored file(s) in plaintext: {sorted(leaked)[:6]}")
    # Positive control: the probe must be able to SEE a leak, or its silence proves nothing.
    probe = {"rows": {"triggers/zz/x.py::f\x1fselect 1": {}}}
    check("P1 control: a planted plaintext gitignored key IS detected", bool(plaintext_ignored_keys(probe)))
    dp_arms()
    print(f"\n{'FAIL' if fails else 'PASS'}: sqlguard oracle ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
