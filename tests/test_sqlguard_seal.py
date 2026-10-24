#!/usr/bin/env python3
"""Oracle for src/astryx/security/sqlguard/evidence.py: a grade is judged from a SEALED tuple, and every consumer
reads the evidence it was judged from (plan-11908 D1 + D2 + D3, a4 #62645).

    venv/bin/python tests/test_sqlguard_seal.py

On 10-23 enforce's own SQL was appended to the trace dir 80 ms after report.json (a3 H1 #62644). A later re-judge by
glob then graded enforce.py::enforce's to_regclass RESPONSIVE while the verdict had it as debt: two traces, one dir.
Hermetic: synthetic trace dirs and a synthetic inventory, no database (judge's live-db name is pinned), no network.
Exit 0 pass · 1 fail.
  E1 env census: every env name sqlguard reads == the stamp's set (a new read is RED until stamped); the census
     sees a planted read (control)
  E2 env values are stamped as sha256[:16] | null, never the value (a2 BC-1 #62651: the admin DSN is one)
  S1 a3's fixture: seal, then enforce's own process appends to a SEALED file and writes a NEW file, and a gate rc lands
     in gates.tsv. Re-judged from the seal, the grades are byte-identical and both files are named as ignored;
     MUTANT, the old glob reader, flips to_regclass to RESPONSIVE (CAUGHT)
  S2 a sealed byte changed is NOT SEARCHED "sealed evidence changed", never a grade
  S3 a partial final line is outside the seal and is not a shim error
  W1 the witness reader sees the WHOLE dir, post-seal included (a prod write by the guard is still a prod write)
  C1 census: every trace-dir read in src/ and devtools/ is evidence.py's (seal or witness), and every
     load_traces call passes a seal
  L1 ledger admit/shrink act only on a report stamped at their own tuple: unstamped and another commit are NOT
     SEARCHED; a VOLATILE env difference (the gate) is not a mismatch
"""
import glob
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard import evidence, judge, ledger  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


LIVE = "sgseal_live"
judge._live_db = lambda: LIVE                       # hermetic: no DSN is resolved, read or opened
ENF = "src/astryx/security/sqlguard/enforce.py"
SITE_T = "select to_regclass('sqlguard_seen')"
OTHER_T = "select id from goals where id = ?"
INV = {"functions": {f"{ENF}::enforce": {"sites": {SITE_T: {"write": False}}, "unresolved": False},
                     "subj/a.py::f": {"sites": {OTHER_T: {"write": False}}, "unresolved": False}},
       "oracle": {}, "triggers_absent": False, "unparseable": [], "extractors": [], "exempt": [], "excluded": []}


def rec(t, frame, rows, gate):
    return json.dumps({"t": t, "frames": [frame], "ok": True, "rows": rows, "db": LIVE, "schema": "public",
                       "gate": gate}) + "\n"


def grades(rep):
    return json.dumps({"sites": rep["sites"], "counts": rep["counts"], "gates": rep["gates"],
                       "records": rep["records"]}, sort_keys=True, default=sorted)


def glob_reader(d, sl, untraced=None):
    """The pre-11908 load_traces: every line of every trace file present NOW (the mutant)."""
    recs = []
    for f in sorted(glob.glob(os.path.join(d, "trace-*.jsonl"))):
        for line in open(f, errors="replace"):
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass
    return recs, 0, [], []


def main():
    # E1
    census = evidence.env_census()
    arm("E1 the env census of sqlguard equals the stamp's env set", census == set(evidence.STAMP_ENV),
        f"census-only {sorted(census - set(evidence.STAMP_ENV))} stamp-only {sorted(set(evidence.STAMP_ENV) - census)}")
    with tempfile.TemporaryDirectory() as td:
        Path(td, "m.py").write_text('import os\nK = "ASTRYX_SQLGUARD_PLANTED"\nos.environ.get(K)\n'
                                    'x = os.environ["ASTRYX_B"]\ny = "ASTRYX_C" in os.environ\nos.getenv("ASTRYX_D")\n'
                                    'os.environ["ASTRYX_WRITE_ONLY"] = "1"\n')
        got = evidence.env_census(Path(td))
        arm("E1 control: the census sees a planted read (a constant, a subscript, `in`, getenv), never a write",
            got == {"ASTRYX_SQLGUARD_PLANTED", "ASTRYX_B", "ASTRYX_C", "ASTRYX_D"}, str(sorted(got)))

    # E2
    secret = "postgresql://sentinel-user:sentinel-pw@127.0.0.1/sentinel_db"
    st = evidence.env_stamp({"ASTRYX_FIXTURE_ADMIN_DSN": secret})
    blob = json.dumps(st)
    arm("E2 an env value is stamped as sha256[:16], absent as null, never the value",
        "sentinel" not in blob and len(st["ASTRYX_FIXTURE_ADMIN_DSN"]) == 16 and st["ASTRYX_SQLGUARD_ROOT"] is None,
        blob)

    # S1 / S2 / S3 / W1
    with tempfile.TemporaryDirectory() as d:
        a = Path(d, "trace-100-0-1.jsonl")
        a.write_text(rec(OTHER_T, ["subj/a.py", "f", 3], 0, "g1") + rec(OTHER_T, ["subj/a.py", "f", 3], 1, "g1")
                     + '{"t": "select half')                          # a gate still writing: a partial line
        Path(d, "gates.tsv").write_text("g1\t0\n")
        rep1 = judge.judge(d, inv=INV, covering={})
        sl = rep1["seal"]
        arm("S3 a partial final line is outside the seal and is not a shim error",
            sl["lines"] == 3 and not rep1["run_not_searched"] and rep1["records"] == 2,
            f"{sl} {rep1['run_not_searched']}")
        before = grades(rep1)
        site = f"{ENF}::enforce\x1f{SITE_T}"
        # after the verdict: enforce's OWN process writes its to_regclass (a new file), the running gate finishes
        # its line and adds one more (a sealed file grows), and check.sh appends enforce's rc to gates.tsv
        Path(d, "trace-200-0-2.jsonl").write_text(rec(SITE_T, [ENF, "enforce", 197], 1, "enforce"))
        with open(a, "a") as f:
            f.write('"}\n' + rec(SITE_T, [ENF, "enforce", 197], 1, "g1"))
        with open(Path(d, "gates.tsv"), "a") as f:
            f.write("enforce\t1\n")
        rep2 = judge.judge(d, inv=INV, covering={}, seal=sl)
        arm("S1 re-judged from the seal, the grades are byte-identical", grades(rep2) == before,
            f"{grades(rep2)}\n        vs {before}")
        ps = " ".join(rep2["post_seal"])
        arm("S1 the grown sealed file AND the new file are both named as ignored",
            "trace-100-0-1.jsonl" in ps and "trace-200-0-2.jsonl" in ps and "gates.tsv" in ps, ps)
        arm("S1 the site is debt in the verdict (the fixture's premise)", rep1["sites"][site]["rung"] != "RESPONSIVE",
            rep1["sites"][site])
        real = judge.load_traces
        judge.load_traces = glob_reader
        try:
            mut = judge.judge(d, inv=INV, covering={}, seal=sl)
        finally:
            judge.load_traces = real
        arm("S1 MUTANT CAUGHT: the glob reader flips enforce.py's to_regclass to RESPONSIVE",
            mut["sites"][site]["rung"] == "RESPONSIVE" and grades(mut) != before, mut["sites"][site])

        w = sum(1 for r in evidence.witness_traces(d) if r.get("db") == LIVE)
        arm("W1 the witness reader sees the whole dir, post-seal included (4 live statements, 1 of them enforce's own)",
            w == 4, str(w))

        raw = a.read_bytes()
        a.write_bytes(raw.replace(b'"rows": 0', b'"rows": 7', 1))
        rep3 = judge.judge(d, inv=INV, covering={}, seal=sl)
        arm("S2 a changed sealed byte is NOT SEARCHED 'sealed evidence changed'",
            any("sealed evidence changed" in n and "trace-100-0-1.jsonl" in n for n in rep3["run_not_searched"]),
            rep3["run_not_searched"])

    # C1
    accused = []
    for f in sorted(list((REPO / "src").rglob("*.py")) + list((REPO / "devtools").rglob("*.py"))
                    + list((REPO / "devtools").glob("*.sh"))):
        rel = str(f.relative_to(REPO))
        if rel in ("src/astryx/security/sqlguard/evidence.py", "src/astryx/security/sqlguard/shim/sitecustomize.py"):
            continue                                   # the readers themselves, and the one writer
        for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"glob\w*\(.*trace-", code) or re.search(r"open\(.*(trace-|gates\.tsv)", code):
                accused.append(f"{rel}:{i}")
            for m in re.finditer(r"\bload_traces\(([^()]*)\)", code):
                if "," not in m.group(1) and not code.lstrip().startswith("def "):
                    accused.append(f"{rel}:{i} load_traces without a seal")
    arm("C1 every trace-dir read in src/ and devtools/ is classed: a seal (grader) or witness_traces (witness)",
        not accused, str(accused))

    # L1
    with tempfile.TemporaryDirectory() as d:
        mine = evidence.stamp(ledger.REPO)
        cases = {"unstamped": None, "other commit": {**mine, "commit": "0" * 40},
                 "volatile gate": {**mine, "env": {**mine["env"], "ASTRYX_SQLGUARD_GATE": "deadbeefdeadbeef"}},
                 "same": mine}
        res = {}
        for name, s in cases.items():
            Path(d, "report.json").write_text(json.dumps({"sites": {}, "run_not_searched": [], "stamp": s}))
            try:
                ledger._report(d)
                res[name] = "ok"
            except SystemExit as e:
                res[name] = str(e)
        arm("L1 an unstamped report is refused NOT SEARCHED", "NOT SEARCHED" in res["unstamped"], res["unstamped"])
        arm("L1 a report from another commit is refused 'evidence from commit X, judged at commit Y'",
            "evidence from commit 000000000000" in res["other commit"], res["other commit"])
        arm("L1 the same tuple, and a VOLATILE env difference, are accepted",
            res["same"] == "ok" and res["volatile gate"] == "ok", str(res))

    print(("PASS: sqlguard seal" if not fails else f"FAIL: {len(fails)} arm(s)") + " (0 failing)" * (not fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
