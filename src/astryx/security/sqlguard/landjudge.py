#!/usr/bin/env python3
"""The sqlguard LAND JUDGE (plan-11908 D6 + D7, a4 #62645): a range that ADDS SQL sites is graded before it pushes.

    venv/bin/python src/astryx/security/sqlguard/landjudge.py <A> <B> [--tree DIR] [--oracle tests/test_x.py]...
    rc 0 pass (or not triggered) · 1 REFUSED · 77 could not judge (land.sh fails closed on it)

On 10-22 /chat (f46eb3e5) added 4 SQL sites and landed green: land.sh runs only the range's tests, with no shim and no
judge, and the pushed tree has no DSN. The 4 reds surfaced only at the next timer run.

TRIGGER: inv(A) ≠ inv(B) as key SETS. A range that touches no .py outside tests/ can't move the inventory, so it is
not triggered without one inventory being built (D8: only ranges that can add a site pay). Otherwise EACH side is
inventoried from its own `git archive` extract (ASTRYX_SQLGUARD_ROOT = that extract); ASTRYX_SQLGUARD_ESTATE_SRC is
the live tree for BOTH sides (a3 #62866), and gitignored sites (triggers/) are never in a range, so the difference is
pure code. rekey's move rule applies first: a new key whose text_key (same file, same SQL) matches a vanished key is a
MOVE, not a new site.
VERDICT: R-NEW-introduced = {k ∈ inv(B) \\ inv(A), not moved : rung(k) < RESPONSIVE ∧ ledger_key(k) ∉ ledger(B)}, rung
over the shim-traced union of the range's oracles, run in --tree (the live checkout at B, under land.sh). Plus R-BLIND
whose frame is in a file the range touched. And the inventory of the extract at B must EQUAL the tree's own at B on
tracked files, or nothing it says is about the tree that runs (refused, "inventory drift").
The judge only calls judge.judge, never enforce: sqlguard_seen is untouched by construction (D5). Its trace dir is its
own, removed on a pass; a refusal keeps it (report.json, stamped) and cites both sides' stamps and the judged seal, so
it can be reproduced from the receipt alone.
GRADE (D7): PREVENTION for lands through land.sh; a direct `git push` is the timer's to DETECT. Each verdict line names
the rung it certifies and the rung above it that it does not. Sites the range didn't add are the timer's.
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (as enforce does)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__)))))))
import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

PKG_SRC = Path(__file__).resolve().parents[3]          # the src/ this judge ships in (it judges; the tree is judged)
SHIM = Path(__file__).resolve().parent / "shim"
CERTIFIES = "RESPONSIVE (the WHERE and every computed bool responded)"
NOT_CERTIFIED = "CORRECT (the mutant battery's rung)"
UNTOUCHED = "untouched sites: the timer's"
ESTATE_ONLY = ("triggers/ absent", "nested checkouts")   # run-level items about the ESTATE: no range site is in it
# The inventory and judge children run with cwd = the tree they grade, so `-c` would put that tree FIRST on sys.path,
# and a tree that ships a root `astryx` (f46eb3e5 does: a symlink to src/astryx) graded itself with its OWN, older
# sqlguard: the live replay at 309d8c23 read KeyError 'seal'. -P drops that entry, so the judge's PYTHONPATH wins:
# the tree is the subject, never the grader. (The oracles run WITHOUT it: they are the tree's own code.)
PYC = [sys.executable, "-P"]


def _scrub(drop) -> dict:
    """A copy of this process's env without the names drop() selects (a whole-env copy: it reads no name)."""
    return {k: v for k, v in os.environ.items() if not drop(k)}


GIT_ENV = _scrub(lambda k: k.startswith("GIT_"))


def _git(tree, *a) -> str:
    return subprocess.run(["git", *a], cwd=tree, env=GIT_ENV, capture_output=True, text=True, check=True).stdout


def code_changed(tree, a, b) -> list:
    """The range's .py files outside tests/: the only files that can move the inventory."""
    return [p for p in _git(tree, "diff", "--name-only", f"{a}..{b}").split() if p.endswith(".py")
            and not p.startswith("tests/")]


def touched(tree, a, b) -> set:
    return set(_git(tree, "diff", "--name-only", f"{a}..{b}").split())


def extract(tree, sha, into: Path) -> Path:
    into.mkdir(parents=True)
    arc = subprocess.run(["git", "archive", sha], cwd=tree, env=GIT_ENV, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(into)], input=arc, check=True)
    return into


def _child_env(root, estate_src, **extra) -> dict:
    e = _scrub(lambda k: k.startswith("ASTRYX_SQLGUARD_") or k == "ASTRYX_AGENT")
    pp = [str(PKG_SRC)] + [x for x in [e.pop("PYTHONPATH", "")] if x]
    return {**e, "ASTRYX_SQLGUARD_ROOT": str(root), "ASTRYX_SQLGUARD_ESTATE_SRC": str(estate_src),
            "PYTHONPATH": os.pathsep.join(pp), **extra}


KEYS = 'sorted(f"{k}\\x1f{t}" for k, f in fns.items() for t in list(f["sites"]) + (["*"] if f["unresolved"] else []))'
INV = ("import json, sys\nfrom astryx.security.sqlguard import inventory\nfns = inventory.build()['functions']\n"
       f"json.dump({KEYS}, sys.stdout)\n")


def inv_keys(root, estate_src) -> set:
    p = subprocess.run(PYC + ["-c", INV], cwd=root, env=_child_env(root, estate_src), capture_output=True,
                       text=True, timeout=600)
    if p.returncode:
        raise RuntimeError(f"inventory of {root} failed rc {p.returncode}: {p.stderr.strip()[-300:]}")
    return set(json.loads(p.stdout))


def moved(new: set, gone: set) -> set:
    from astryx.security.sqlguard.privacy import text_key
    gone_tk = {text_key(g) for g in gone}
    return {k for k in new if text_key(k) in gone_tk}


def decide(introduced, sites, lks, rows, blind, touched_files, label=lambda k: k.replace("\x1f", " :: ")) -> tuple:
    """(refusals, passes): the pure verdict over a judged report (sites: {key: {rung}}), each introduced key's ledger
    key (lks), the ledger's rows at B and the blind list. Every line names what it certifies and what it does not (D7)."""
    refusals, passes = [], []
    for k in sorted(introduced):
        rung = (sites.get(k) or {"rung": "UNEXECUTED"})["rung"]
        if lks.get(k, k) in rows:
            passes.append(f"· {label(k)}: listed in the ledger at B ({rung}; certified: listed debt; NOT certified: "
                          f"RESPONSIVE)")
        elif rung == "RESPONSIVE":
            passes.append(f"✓ {label(k)}: RESPONSIVE under the range's oracles (certified: {CERTIFIES}; NOT certified: "
                          f"{NOT_CERTIFIED})")
        else:
            refusals.append(f"R-NEW-introduced {label(k)}: {rung} under the range's oracles (certified: {rung}; NOT "
                            f"certified: RESPONSIVE). Add the arm that drives it to 0 and ≥1 rows, or `ledger admit`")
    for b in blind:
        if b["frame"][0] in touched_files:
            refusals.append(f"R-BLIND {b['frame'][0]}::{b['frame'][1]} (a file the range touched) ran SQL the "
                            f"inventory doesn't know (certified: nothing about it)")
    return refusals, passes


JUDGE = ("import json, os, sys\nfrom astryx.security.sqlguard import inventory, judge\n"
         "from astryx.security.sqlguard.privacy import ledger_key\n"
         "d, intro, led = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]\n"
         "inv = inventory.build()\nrep = judge.judge(d, inv=inv)\njudge.write_report(d, rep)\nfns = inv['functions']\n"
         "rows = sorted(json.load(open(led))['rows']) if os.path.exists(led) else []\n"
         "json.dump({'sites': {k: rep['sites'].get(k) for k in intro}, 'lk': {k: ledger_key(k) for k in intro},\n"
         f"           'rows': rows, 'blind': rep['blind'], 'keys': {KEYS}, 'seal': rep['seal'],\n"
         "           'run_not_searched': rep['run_not_searched']}, sys.stdout, default=sorted)\n")


def run_oracles(tree, oracles, tdir, timeout) -> dict:
    run = f"lj{os.getpid()}x{int(time.time())}"
    Path(tdir, "run_id").write_text(run + "\n")
    rcs = {}
    for o in oracles:
        ce = _child_env(tree, tree, ASTRYX_SQLGUARD_DIR=str(tdir), ASTRYX_SQLGUARD_RUN=run,
                        ASTRYX_SQLGUARD_GATE=o, ASTRYX_RUNSCOPE_TEST="1")
        # the oracle imports the TREE's code, never this judge's src: only the shim rides it (as sitecustomize, which
        # loads its own sqlguard helpers by file path)
        ce["PYTHONPATH"] = os.pathsep.join([str(SHIM)] + ce["PYTHONPATH"].split(os.pathsep)[1:])
        try:
            rc = subprocess.run([sys.executable, o], cwd=tree, env=ce, capture_output=True, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            rc = 124
        rcs[o] = rc
        with Path(tdir, "gates.tsv").open("a") as f:      # the WRITER (check.sh's run() shape); judge reads it sealed
            f.write(f"{o}\t{rc}\n")
    return rcs


def _short(st) -> str:
    return (f"commit {st['commit'][:12]}, estate_code {str(st.get('estate_code_hash'))[:12]}, env "
            f"{hashlib.sha256(json.dumps(st.get('env'), sort_keys=True).encode()).hexdigest()[:12]}")


def land_judge(a, b, tree, oracles, timeout=900, log=print) -> int:
    """The verdict. A trace dir is KEPT only on a refusal or a 77 (to reproduce or admit from); on every rc 0 it is
    removed, whichever path passed (the design's "removed on green")."""
    made = []
    rc = _land_judge(a, b, tree, oracles, timeout, log, made)
    if rc == 0:
        for d in made:
            shutil.rmtree(d, ignore_errors=True)
    return rc


def _land_judge(a, b, tree, oracles, timeout, log, made) -> int:
    tree = Path(tree).resolve()
    t0 = time.monotonic()
    cost = {}
    if not code_changed(tree, a, b):
        log(f"land judge: not triggered (no .py outside tests/ in the range: the inventory can't move). Certifies "
            f"nothing about SQL; {UNTOUCHED}")
        return 0
    from astryx.security.sqlguard import evidence
    work = Path(tempfile.mkdtemp(prefix="landjudge-"))
    try:
        t = time.monotonic()
        inv_a = inv_keys(extract(tree, a, work / "a"), tree)
        inv_b = inv_keys(extract(tree, b, work / "b"), tree)
        cost["inventories (2 extracts)"] = time.monotonic() - t
        new, gone = inv_b - inv_a, inv_a - inv_b
        mv = moved(new, gone)
        intro = new - mv
        if not new and not gone:
            log(f"land judge: not triggered (inv(A) = inv(B), {len(inv_b)} sites). Certifies nothing about SQL; {UNTOUCHED}")
            return 0
        if not intro:
            log(f"land judge: PASS, the range only MOVED {len(mv)} site(s) (rekey: same file, same SQL) and dropped "
                f"{len(gone) - len(mv)}; nothing new to grade (certified: no new site; NOT certified: the moved sites' "
                f"rungs). {UNTOUCHED}")
            return 0
        oracles = [o for o in oracles if Path(o).name.startswith("test_")]
        if not oracles:
            log(f"land judge: REFUSED, the range adds {len(intro)} SQL site(s) and no test_*.py oracle to grade them")
            return 1
        tdir = Path(tempfile.mkdtemp(prefix="landjudge-trace-"))
        made.append(tdir)
        t = time.monotonic()
        rcs = run_oracles(tree, oracles, tdir, timeout)
        cost[f"oracles under the shim ({len(oracles)})"] = time.monotonic() - t
        Path(work, "intro.json").write_text(json.dumps(sorted(intro)))
        led = tree / "src" / "astryx" / "security" / "sqlguard" / "ledger.json"
        t = time.monotonic()
        p = subprocess.run(PYC + ["-c", JUDGE, str(tdir), str(work / "intro.json"), str(led)], cwd=tree,
                           env=_child_env(tree, tree), capture_output=True, text=True, timeout=1200)
        cost["judge (seal + tree inventory)"] = time.monotonic() - t
        cost["total"] = time.monotonic() - t0
        log("  cost (D8): " + ", ".join(f"{k} {v:.1f}s" for k, v in cost.items()))   # every judged path, red ones too
        if p.returncode:
            log(f"land judge: COULD NOT JUDGE (rc {p.returncode}): {p.stderr.strip()[-300:]}; trace kept at {tdir}")
            return 77
        j = json.loads(p.stdout)
        tracked = set(_git(tree, "ls-files").split())
        live_b = {k for k in j["keys"] if k.split("::", 1)[0] in tracked}
        st_a = {**evidence.stamp(tree), "commit": _git(tree, "rev-parse", a).strip()}
        st_b = {**evidence.stamp(tree), "commit": _git(tree, "rev-parse", b).strip()}
        seal_sha = hashlib.sha256(json.dumps(j["seal"], sort_keys=True).encode()).hexdigest()
        cite = (f"stamps: A {_short(st_a)} | B {_short(st_b)}; judged seal {seal_sha[:12]} "
                f"({len(j['seal']['files'])} files, {j['seal']['lines']} lines); trace {tdir}")
        log(f"  seal (D8): {j['seal']['lines']} records hashed")
        if live_b != inv_b:
            log(f"land judge: REFUSED, inventory drift: the extract at B and the tree at B disagree on "
                f"{len(live_b ^ inv_b)} tracked site(s), so the trigger is not about the tree that runs. {cite}")
            return 1
        ns = [n for n in j["run_not_searched"] if not n.startswith(ESTATE_ONLY)]
        bad_rc = {o: rc for o, rc in rcs.items() if rc != 0}
        if ns or bad_rc:
            log(f"land judge: COULD NOT JUDGE: run NOT SEARCHED {ns}, oracle rcs {bad_rc}. {cite}")
            return 77
        refusals, passes = decide(intro, j["sites"], j["lk"], set(j["rows"]), j["blind"], touched(tree, a, b))
        for line in passes:
            log(f"  {line}")
        if refusals:
            for line in refusals:
                log(f"  ✗ {line}")
            log(f"land judge: REFUSED: {len(refusals)} finding(s) on the {len(intro)} site(s) the range introduced. {cite}")
            return 1
        log(f"land judge: PASS: {len(intro)} introduced site(s) graded (certified: {CERTIFIES}; NOT certified: "
            f"{NOT_CERTIFIED}); {len(mv)} moved. {UNTOUCHED}")
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log(f"land judge: COULD NOT JUDGE: {type(e).__name__}: {str(e)[-300:]}")
        return 77
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="landjudge")
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--tree", default=".")
    ap.add_argument("--oracle", action="append", default=[])
    ap.add_argument("--timeout", type=int, default=900)
    o = ap.parse_args(argv)
    return land_judge(o.a, o.b, o.tree, o.oracle, o.timeout)


if __name__ == "__main__":
    sys.exit(main())
