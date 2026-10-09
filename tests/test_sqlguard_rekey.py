#!/usr/bin/env python3
"""Oracle for nucleus/sqlguard/rekey.py: a range that re-texts a LISTED SQL literal without moving its ledger row is
RED before merge, statically (a3 night-review 10-09; the shape that backed plan-4918 out twice, seed #33150 #34264).

    venv/bin/python tests/test_sqlguard_rekey.py

Hermetic: a throwaway git repo carrying THIS tree's inventory + normalize and one SQL-bearing subject. No database,
no live state, no network. Exit 0 pass · 1 fail.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus.sqlguard import rekey  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(repo, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, env=ENV,
                          capture_output=True, text=True, check=True).stdout.strip()


SUBJECT = 'def q(c, x):\n    return c.execute("SELECT a FROM t WHERE a {op} %s", (x,))\n'


def main():
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / "nucleus" / "sqlguard").mkdir(parents=True)
        (r / "nucleus" / "__init__.py").write_text("")
        (r / "nucleus" / "sqlguard" / "__init__.py").write_text("")
        for f in ("inventory.py", "normalize.py"):
            shutil.copy2(REPO / "nucleus" / "sqlguard" / f, r / "nucleus" / "sqlguard" / f)
        (r / "nucleus" / "demo.py").write_text(SUBJECT.format(op="LIKE"))
        led = r / "nucleus" / "sqlguard" / "ledger.json"
        led.write_text(json.dumps({"header": {}, "rows": {}}))
        git(r, "init", "-q", "-b", "main")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "A0")
        with tempfile.TemporaryDirectory() as t2:      # the subject's key, from the inventory itself (never typed)
            old_key, = rekey._sites(rekey._tree(r, "HEAD", Path(t2) / "x"))
        hashed = "sha256:" + "0" * 64
        led.write_text(json.dumps({"header": {}, "rows": {old_key: {"debt": "UNEXECUTED"}, hashed: {}}}))
        git(r, "commit", "-qam", "A: the LIKE site, listed")
        A = git(r, "rev-parse", "HEAD")

        # B: the literal re-texted, the ledger NOT moved (9689203's shape)
        (r / "nucleus" / "demo.py").write_text(SUBJECT.format(op="~"))
        git(r, "commit", "-qam", "B: LIKE -> ~, ledger untouched")
        B = git(r, "rev-parse", "HEAD")
        res = rekey.check(r, A, B)
        new_key = old_key.replace(" like ", " ~ ")
        arm("a re-texted LISTED literal with no ledger move → STALE names the old row",
            res["stale"] == [old_key], res)
        arm("…and its new spelling is reported NEW (unlisted)", res["new"] == [new_key], res)
        arm("…and the CLI exits 1", rekey.main([A, B, "--repo", str(r)]) == 1)
        arm("hashed estate rows are SKIPPED and COUNTED, never silently", res["hashed_skipped"] == 1, res)

        # C: the ledger moved with it (abdbe4b's shape)
        led.write_text(json.dumps({"header": {}, "rows": {new_key: {"debt": "UNEXECUTED"}, hashed: {}}}))
        git(r, "commit", "-qam", "C: the row re-keyed")
        C = git(r, "rev-parse", "HEAD")
        res = rekey.check(r, A, C)
        arm("the same range WITH the ledger move → no STALE, no NEW", res["stale"] == [] and res["new"] == [], res)
        arm("…and the CLI exits 0", rekey.main([A, C, "--repo", str(r)]) == 0)

        # D: a brand-new unlisted site is ADVISORY only (a run may grade it RESPONSIVE)
        with open(r / "nucleus" / "demo.py", "a") as f:
            f.write('\n\ndef q2(c):\n    return c.execute("SELECT b FROM t")\n')
        git(r, "commit", "-qam", "D: a new site")
        D = git(r, "rev-parse", "HEAD")
        res = rekey.check(r, C, D)
        arm("a NEW unlisted site is reported but is not STALE", res["stale"] == [] and len(res["new"]) == 1, res)
        arm("…and the CLI still exits 0 (only a run can say RESPONSIVE)", rekey.main([C, D, "--repo", str(r)]) == 0)

        # a listed row stale at BOTH sides is not this range's
        led.write_text(json.dumps({"header": {}, "rows": {new_key: {}, "nucleus/gone.py::f\x1fselect 1": {}}}))
        git(r, "commit", "-qam", "E: a row for a site that never existed")
        E = git(r, "rev-parse", "HEAD")
        res = rekey.check(r, D, E)
        arm("a row absent at both sides is PRE-EXISTING, never blamed on the range",
            res["stale"] == [] and res["preexisting"] == ["nucleus/gone.py::f\x1fselect 1"], res)

        arm("an unresolvable rev → rc 2 (couldn't run), never a clean 0",
            rekey.main(["no-such-rev", E, "--repo", str(r)]) == 2)

    print(("PASS: sqlguard rekey" if not fails else f"FAIL: {len(fails)} arm(s)") + " (0 failing)" * (not fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
