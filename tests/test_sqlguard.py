#!/usr/bin/env python3
"""sqlguard oracle (goal 4243, B1). Every control on nucleus/sqlguard/DESIGN.md's acceptance list lands here,
RED-first. This file is built up arm by arm, and check.sh starts enforcing only once it is complete, in one act.

    venv/bin/python tests/test_sqlguard.py [ledger.json]      # 0 pass · 1 fail · 77 could-not-run
    venv/bin/python tests/test_sqlguard.py --against <rev>    # RED-first: the harness vs an older package
    venv/bin/python tests/test_sqlguard.py --mutants          # every mutant must be killed by its NAMED arm

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


# ─── the TEMP-REPO harness (B1): every control, run for real, in a throwaway tree ─────────────────────────────
# The package under test is COPIED into a temp git tree beside small subject files, and ASTRYX_SQLGUARD_ROOT points
# there. So the shim, inventory, judge and enforce all run exactly as check.sh runs them, against subjects whose
# right answer is known. `--mutants` re-runs the harness against deliberately broken copies of the package: every
# mutant must turn at least one NAMED arm red (the RED-first evidence, mechanised).

SUBJ_ARMS = '''"""sqlguard harness subjects: one function per control (tests/test_sqlguard.py builds this file)."""


def v3_twin_a(c, k):
    return c.execute("SELECT id FROM goals WHERE id = %s", (k,)).fetchall()


def v3_twin_b(c, k):
    return c.execute("SELECT id FROM goals WHERE id = %s", (k,)).fetchall()


def v4_stored_bool(c, pat):
    return c.execute("SELECT name, enabled FROM triggers WHERE name LIKE %s", (pat,)).fetchall()


def p3_projected(ctx, floor):
    return ctx.sql("SELECT n, (n > 0) AS dq FROM generate_series(1, 2) AS n WHERE n > %s", (floor,))


def data_const(ctx, floor):
    return ctx.sql("SELECT n, ('x' || '') AS label, (n > 0)::text AS dq_text FROM generate_series(1, 2) AS n "
                   "WHERE n > %s", (floor,))


def cte_dml(c, floor):
    return c.execute("WITH d AS (DELETE FROM goals WHERE false RETURNING id) SELECT n FROM generate_series(1, 2) "
                     "AS n WHERE n > %s", (floor,)).fetchall()


def pct_literal(c, k):
    return c.execute("SELECT id FROM goals WHERE title LIKE 'x%' AND id = %s", (k,)).fetchall()


def bad_column(c, k):
    return c.execute("SELECT no_such_column FROM goals WHERE id = %s", (k,)).fetchall()


def fake_conn(c, k):
    return c.execute("SELECT id FROM goals WHERE state = %s", (k,))


def empty_w(c, k):
    return c.execute("SELECT id FROM goals WHERE id = %s AND id < 0", (k,)).fetchall()


def search_path_after(c, name):
    c.execute("SET search_path TO pg_catalog")
    return c.execute("SELECT relname FROM pg_class WHERE relname = %s", (name,)).fetchall()


def stamped_update(c, k):
    return c.execute("UPDATE goals SET title = title WHERE id = %s", (k,)).rowcount


def hand_fixture(c, k):
    return c.execute("SELECT id FROM hand_t WHERE id = %s", (k,)).fetchall()


def stamped_beside_hand(c, k):
    return c.execute("SELECT id, owner FROM goals WHERE id = %s", (k,)).fetchall()


def dml_after_hand(c, k):
    return c.execute("UPDATE goals SET owner = owner WHERE id = %s", (k,)).rowcount


def drop_recreate(c, k):
    return c.execute("SELECT kind FROM sqlguard_seen WHERE key = %s", (k,)).fetchall()


def da_probe(c, k):
    return c.execute("SELECT kind, runs FROM sqlguard_seen WHERE key = %s", (k,)).fetchall()


def stale_sha(c, k):
    return c.execute("SELECT id FROM goals WHERE id = %s AND title IS NOT NULL", (k,)).fetchall()


def dc_probe(c, k):
    return c.execute("SELECT id, title FROM goals WHERE id = %s", (k,)).fetchall()


def never_run(c, k):
    return c.execute("SELECT id FROM goals WHERE owner = %s", (k,)).fetchall()
'''

SUBJ_IGNORED = '''def ignored_never_run(c, k):
    return c.execute("SELECT id FROM goals WHERE scope_note = %s", (k,)).fetchall()
'''

SUBJ_CHILD = '''def child_site(c, k):
    return c.execute("SELECT id FROM goals WHERE parent_id = %s", (k,)).fetchall()


if __name__ == "__main__":
    pass
'''

DRIVE = r'''"""Drives every subject in subj/arms.py under the shim (tests/test_sqlguard.py builds this file)."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psycopg  # noqa: E402
from nucleus.sqlguard.fixture import fixture_db, live_dsn  # noqa: E402
from subj import arms  # noqa: E402

OUT = {}
TAG = f"sqlguard-harness-{os.getpid()}"


class FakeConn:
    def execute(self, *a, **k):
        return []


def rows(c):
    gid = c.execute("INSERT INTO goals (title, owner) VALUES ('g', 'o') RETURNING id").fetchone()[0]
    c.execute("INSERT INTO triggers (agent, name, schedule) VALUES ('a', 'fx_t1', '* * * * *')")
    return gid


def swallow(f, *a):
    try:
        f(*a)
    except psycopg.Error:
        pass


def main():
    spec = importlib.util.spec_from_file_location("pulse_run_h", ROOT / "nucleus" / "pulse_run.py")
    pr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pr)
    ctx = pr.Ctx({})
    for floor in (0, 9):                      # the REAL Ctx.sql, on live public, read-only
        arms.p3_projected(ctx, floor)
        arms.data_const(ctx, floor)
    live = psycopg.connect(live_dsn(), autocommit=True)
    for floor in (0, 9):
        arms.cte_dml(live, floor)             # DELETE ... WHERE false: a write that writes nothing
    sp = psycopg.connect(live_dsn(), autocommit=True)
    arms.search_path_after(sp, "pg_class")
    arms.search_path_after(sp, "no_such_rel")
    sp.close()

    with fixture_db() as fx:                  # A: a clean, stamped fixture
        c = psycopg.connect(fx["dsn"], autocommit=True)
        gid = rows(c)
        arms.v3_twin_a(c, gid)
        arms.v3_twin_a(c, -1)
        arms.v4_stored_bool(c, "fx_%")
        arms.v4_stored_bool(c, "none")
        swallow(arms.pct_literal, c, gid)
        swallow(arms.bad_column, c, gid)
        arms.fake_conn(FakeConn(), "active")
        arms.empty_w(c, gid)
        arms.stamped_update(c, gid)
        arms.stamped_update(c, -1)
        c.close()
    with fixture_db() as fx:                  # B: one hand-made relation (and M1: A's credit must not carry here)
        c = psycopg.connect(fx["dsn"], autocommit=True)
        gid = rows(c)
        c.execute("CREATE TABLE hand_t (id int)")
        c.execute("INSERT INTO hand_t VALUES (1)")
        arms.hand_fixture(c, 1)
        arms.hand_fixture(c, 2)
        arms.dml_after_hand(c, gid)
        arms.dml_after_hand(c, -1)
        arms.stamped_beside_hand(c, gid)
        arms.stamped_beside_hand(c, -1)
        c.close()
    with fixture_db() as fx:                  # C: DROP + re-CREATE, same shape, no stamp
        c = psycopg.connect(fx["dsn"], autocommit=True)
        c.execute("DROP TABLE sqlguard_seen")
        c.execute("CREATE TABLE sqlguard_seen (kind text NOT NULL, key text NOT NULL, first_seen timestamptz NOT "
                  "NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(), runs int NOT NULL DEFAULT 1, "
                  "PRIMARY KEY (kind, key))")
        c.execute("INSERT INTO sqlguard_seen (kind, key) VALUES ('k', 'k1')")
        arms.drop_recreate(c, "k1")
        arms.drop_recreate(c, "none")
        c.close()
    with fixture_db() as fx:                  # D (a3 D-A): SELECT, ALTER ... DROP DEFAULT, the same SELECT
        c = psycopg.connect(fx["dsn"], autocommit=True)
        c.execute("INSERT INTO sqlguard_seen (kind, key) VALUES ('k', 'k1')")
        arms.da_probe(c, "k1")
        c.execute("ALTER TABLE sqlguard_seen ALTER COLUMN runs DROP DEFAULT")
        arms.da_probe(c, "k1")
        c.close()
    with fixture_db() as fx:                  # E: schema.sql changed after the stamp
        c = psycopg.connect(fx["dsn"], autocommit=True)
        gid = rows(c)
        schema = ROOT / "nucleus" / "schema.sql"
        orig = schema.read_bytes()
        try:
            schema.write_bytes(orig + b"\n-- sqlguard harness: a stale sha\n")
            arms.stale_sha(c, gid)
            arms.stale_sha(c, -1)
        finally:
            schema.write_bytes(orig)
        c.close()
    with fixture_db() as fx:                  # F (a3 D-C): the caller holds uncommitted DDL
        c = psycopg.connect(fx["dsn"])
        gid = rows(c)
        c.commit()
        c.execute("ALTER TABLE goals ALTER COLUMN state DROP DEFAULT")
        t0 = time.monotonic()
        arms.dc_probe(c, gid)
        first = time.monotonic() - t0
        t0 = time.monotonic()
        for _ in range(50):
            arms.dc_probe(c, gid)
        fifty = time.monotonic() - t0
        c.rollback()
        c.close()
        dcdb = fx["dbname"]
    OUT["dc"] = {"first_s": first, "fifty_s": fifty,
                 "gone": not live.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dcdb,)).fetchone()}

    # zero NOTIFY in live (a1: the LISTEN connection is opened BEFORE the fixture DB exists)
    lis = psycopg.connect(live_dsn(), autocommit=True)
    probe = f"sqlguard_probe_{os.getpid()}"
    for ch in ("astryx_steps", "astryx_wire", probe):
        lis.execute(f"LISTEN {ch}")
    with fixture_db() as fx:
        c = psycopg.connect(fx["dsn"], autocommit=True)
        inner = psycopg.connect(fx["dsn"], autocommit=True)
        inner.execute("LISTEN astryx_steps")
        c.execute("INSERT INTO steps (agent, kind, content) VALUES (%s, 'milestone', 'fx')", (TAG,))
        mid = c.execute("INSERT INTO messages (from_agent, to_agent, body) VALUES (%s, %s, 'fx') RETURNING id",
                        (TAG, TAG)).fetchone()[0]
        inner_got = [n.payload for n in inner.notifies(timeout=2, stop_after=1)]
        inner.close()
        c.close()
    live.execute(f"NOTIFY {probe}, 'control'")
    got = list(lis.notifies(timeout=2))
    OUT["notify"] = {
        "leaked": [n.payload for n in got if (n.channel == "astryx_steps" and TAG in n.payload)
                   or (n.channel == "astryx_wire" and n.payload == str(mid))],
        "probe": sum(1 for n in got if n.channel == probe), "fixture_inner": inner_got}
    lis.close()

    # an untraced child: the oracle states its own env, so the shim records the launch instead of injecting
    subprocess.run([sys.executable, str(ROOT / "subj" / "child.py")], env={"PATH": os.environ.get("PATH", "")},
                   check=True)
    live.close()
    print(json.dumps(OUT))


if __name__ == "__main__":
    main()
'''

JUDGE_Q = r'''
import json, sys
from nucleus.sqlguard import judge
d, cov, stored = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
kw = {"stored_covering": stored} if stored else {}
try:
    rep = judge.judge(d, covering=cov or None, **kw)
except TypeError as e:                      # an older package: THOSE arms fail by name, the rest still run
    print(json.dumps({"error": f"TypeError: {e}"}))
    sys.exit(0)
print(json.dumps({"sites": rep["sites"], "run_not_searched": rep["run_not_searched"], "blind": rep["blind"],
                  "untraced": rep["untraced_children"], "extractors": rep["extractors"]}))
'''

ENF = r'''"""Drives enforce.py and ledger.admit against SYNTHETIC reports (tests/test_sqlguard.py builds this file)."""
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psycopg  # noqa: E402
from nucleus.sqlguard import enforce, fixture, ledger  # noqa: E402

CAN = "nucleus/sqlguard/canary.py::canary\x1fselect 1"
S1 = "subj/arms.py::v3_twin_b\x1fselect id from goals where id = ?"
S2 = "subj/arms.py::gone\x1fselect 2"
OUT = {}


def rep(sites, gates=None, covering=None, extractors=None):
    return {"sites": {CAN: {"rung": "RESPONSIVE"}, **{k: {"rung": v} for k, v in sites.items()}},
            "run_not_searched": [], "gates": gates or {}, "covering": covering or {},
            "extractors": extractors or {}, "blind": []}


def lg(rows=None, extractors=None):
    return {"rows": {k: {"debt": v, "reason": "seed"} for k, v in (rows or {}).items()},
            "extractors": extractors or {}, "covering": {}}


def run(name, r, led, dsn):
    out = enforce.enforce("", ledger=led, dsn=dsn, rep=r)
    OUT[name] = {"rc": out["rc"], "red": out["red"], "report": out["report"], "ns": out["not_searched"]}


def main():
    run_id = os.environ["ASTRYX_SQLGUARD_RUN"]
    os.environ["ASTRYX_SQLGUARD_RUN"] = f"st{os.getpid()}"          # the state DB must not be "this run's"
    with fixture.fixture_db() as fx:
        os.environ["ASTRYX_SQLGUARD_RUN"] = run_id
        dsn = fx["dsn"]
        st = psycopg.connect(dsn, autocommit=True)
        today = datetime.date.today()
        run("new", rep({S1: "UNEXECUTED"}), lg(), dsn)
        run("listed", rep({S1: "UNEXECUTED"}), lg({S1: "UNEXECUTED"}), dsn)
        run("climbed", rep({S1: "RESPONSIVE"}), lg({S1: "UNEXECUTED"}), dsn)
        run("vanished", rep({}), lg({S2: "UNEXECUTED"}), dsn)
        run("canary_absent", {**rep({}), "sites": {}}, lg(), dsn)
        ex = {"tests/x.py": {"gates": ["gx"], "listed_since": str(today), "trip": {"goal": 999999, "state": "done"}}}
        cov = {S1: ["gx"]}
        run("ex3_listed", rep({S1: "EXECUTED/FIXTURE-DDL"}, covering=cov, extractors={"tests/x.py": ["gx"]}),
            lg(extractors=ex), dsn)
        run("ex3_unlisted", rep({S1: "EXECUTED/FIXTURE-DDL"}, covering=cov, extractors={"tests/x.py": ["gx"]}),
            lg(), dsn)
        for rc in (0, 77, 1):                                        # F-b: only a COMPLETED gate proves absence
            run(f"fb_rc{rc}", rep({}, gates={"gx": rc}), lg(extractors=ex), dsn)
        old = {"tests/x.py": {**ex["tests/x.py"], "listed_since": str(today - datetime.timedelta(days=40))}}
        run("ex2_clock", rep({}, gates={"gx": 77}), lg(extractors=old), dsn)
        gid = st.execute("INSERT INTO goals (title, owner, state) VALUES ('trip', 'o', 'active') RETURNING id"
                         ).fetchone()[0]
        tripped = {"tests/x.py": {**ex["tests/x.py"], "trip": {"goal": gid, "state": "done"}}}
        run("trip_armed", rep({}, gates={"gx": 77}), lg(extractors=tripped), dsn)
        st.execute("UPDATE goals SET state = 'done' WHERE id = %s", (gid,))
        run("trip_fired", rep({}, gates={"gx": 77}), lg(extractors=tripped), dsn)
        # R-CLOCK: first-seen state, per site
        run("clock_1", rep({S1: "NOT SEARCHED"}), lg(), dsn)
        st.execute("UPDATE sqlguard_seen SET runs = 99, first_seen = now() - interval '10 days' WHERE kind = 'ns_site'")
        run("clock_2", rep({S1: "NOT SEARCHED"}), lg(), dsn)
        # R-LEAK: this run's prefix, and a foreign one by first-seen
        mine, foreign = f"astryx_fx_{run_id}_leak".lower(), f"astryx_fx_zzh{os.getpid()}".lower()
        adm = psycopg.connect(fixture.live_dsn(), autocommit=True)
        try:
            adm.execute(f'CREATE DATABASE "{mine}"')
            adm.execute(f'CREATE DATABASE "{foreign}"')
            run("leak_1", rep({}), lg(), dsn)
            st.execute("UPDATE sqlguard_seen SET runs = 5, first_seen = now() - interval '2 hours' "
                       "WHERE kind = 'fx_db' AND key = %s", (foreign,))
            run("leak_2", rep({}), lg(), dsn)
        finally:
            adm.execute(f'DROP DATABASE IF EXISTS "{mine}" WITH (FORCE)')
            adm.execute(f'DROP DATABASE IF EXISTS "{foreign}" WITH (FORCE)')
            adm.close()
        # --admit: the only growth path
        if not hasattr(ledger, "admit"):         # an older package: the admit arms fail by NAME, never a crash
            OUT["admit_refusals"], OUT["admitted"] = {}, {"rc": None, "red": [], "report": [], "ns": ["no admit"]}
            st.close()
            print(json.dumps(OUT))
            return
        td = Path(sys.argv[1])
        (td / "report.json").write_text(json.dumps(rep({S1: "UNEXECUTED", S2: "RESPONSIVE"})))
        lp = td / "ledger.json"
        lp.write_text(json.dumps(lg()))
        refusals = {}
        for name, site, reason in (("no_reason", S1, " "), ("seed_reason", S1, "seed"), ("healthy", S2, "why"),
                                   ("unknown", "subj/nope.py::f\x1fselect 9", "why")):
            try:
                ledger.admit(str(td), site, reason, lp)
                refusals[name] = False
            except SystemExit:
                refusals[name] = True
        OUT["admit_refusals"] = refusals
        label = S1.replace("\x1f", " :: ")
        OUT["admit_key"] = ledger.admit(str(td), label, "harness: the reason", lp)
        led = json.loads(lp.read_text())
        run("admitted", rep({S1: "UNEXECUTED"}), led, dsn)
        try:
            ledger.admit(str(td), label, "again", lp)
            refusals["twice"] = False
        except SystemExit:
            refusals["twice"] = True
        st.close()
    print(json.dumps(OUT))


if __name__ == "__main__":
    main()
'''


CLEAN = '''"""Uses ONLY the applier: must never be derived as an extractor (tests/test_sqlguard.py builds this file)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg  # noqa: E402
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

with fixture_db() as fx:
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        c.execute("SELECT count(*) FROM goals").fetchone()
'''


def _build_tree(tmp: Path, rev=None):
    """rev: take the PACKAGE from that commit (RED-first: `--against <rev>`); subjects and drivers stay current."""
    import shutil
    if rev:
        (tmp / "nucleus").mkdir(parents=True)
        arc = subprocess.run(["git", "archive", rev, "nucleus/sqlguard"], cwd=REPO, capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(tmp)], input=arc.stdout, check=True)
        (tmp / "nucleus" / "sqlguard" / "ledger.json").unlink(missing_ok=True)
    else:
        shutil.copytree(REPO / "nucleus" / "sqlguard", tmp / "nucleus" / "sqlguard",
                        ignore=shutil.ignore_patterns("__pycache__", "ledger.json"))
    (tmp / "nucleus" / "__init__.py").write_text("")
    for f in ("pulse_run.py", "schema.sql"):
        shutil.copy2(REPO / "nucleus" / f, tmp / "nucleus" / f)
    (tmp / ".env").symlink_to((REPO / ".env").resolve())
    (tmp / "triggers").mkdir()
    (tmp / "subj").mkdir()
    (tmp / "subj" / "__init__.py").write_text("")
    (tmp / "subj" / "arms.py").write_text(SUBJ_ARMS)
    (tmp / "subj" / "ignored_arm.py").write_text(SUBJ_IGNORED)
    (tmp / "subj" / "child.py").write_text(SUBJ_CHILD)
    (tmp / "tests").mkdir()
    (tmp / "tests" / "drive.py").write_text(DRIVE)
    (tmp / "tests" / "enf.py").write_text(ENF)
    (tmp / "tests" / "clean.py").write_text(CLEAN)
    (tmp / ".gitignore").write_text("subj/ignored_*.py\n.env\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)


def _env(tmp: Path, run: str, trace=None, gate=""):
    import os
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"),
         "ASTRYX_SQLGUARD_ROOT": str(tmp), "ASTRYX_SQLGUARD_RUN": run}
    if trace is not None:
        e.update(ASTRYX_SQLGUARD_DIR=str(trace), ASTRYX_SQLGUARD_GATE=gate,
                 PYTHONPATH=str(tmp / "nucleus" / "sqlguard" / "shim"))
    return e


def _py(tmp, env, *args, timeout=300):
    r = subprocess.run([sys.executable, *args], cwd=tmp, env=env, capture_output=True, text=True, timeout=timeout)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    try:
        return r.returncode, json.loads(last), r.stderr
    except ValueError:
        return r.returncode, None, (r.stderr or r.stdout)[-1500:]


def _rung(sites, fn, path="subj/arms.py"):
    got = [v["rung"] for k, v in sites.items() if k.startswith(f"{path}::{fn}\x1f")]
    return got[0] if len(got) == 1 else f"<{len(got)} sites>"


def harness_arms(tmp: Path, quiet=False, rev=None, mutate=None):
    """Every acceptance control from DESIGN.md, run for real. Returns the list of failing arm names."""
    import os
    say = (lambda *a: None) if quiet else check
    failed = []

    def arm(name, ok, detail=""):
        if not ok:
            failed.append(name)
        say(name, ok, detail)

    _build_tree(tmp, rev)
    if mutate:
        mutate(tmp)
    run = (os.environ.get("ASTRYX_SQLGUARD_RUN") or f"th{os.getpid()}").lower()
    trace = tmp / "trace"
    trace.mkdir()
    rc_c = subprocess.run([sys.executable, "-m", "nucleus.sqlguard.canary"], cwd=tmp, capture_output=True,
                          env=_env(tmp, run, trace, "g-canary")).returncode
    rc_d, drive, err = _py(tmp, _env(tmp, run, trace, "g-main"), "tests/drive.py")
    rc_k = subprocess.run([sys.executable, "tests/clean.py"], cwd=tmp, capture_output=True,
                          env=_env(tmp, run, trace, "g-clean")).returncode
    gates = f"g-canary\t{rc_c}\ng-main\t{rc_d}\ng-clean\t{rc_k}\n"
    (trace / "gates.tsv").write_text(gates)
    if drive is None:
        arm("harness: the subject driver ran", False, err)
        return failed
    rc_j, rep, err = _py(tmp, _env(tmp, run), "-c", JUDGE_Q, str(trace), "{}", "{}")
    if rep is None:
        arm("harness: the judge ran", False, err)
        return failed
    S = rep["sites"]
    arm("run: no shim errors, no blind SQL, triggers/ present", not rep["run_not_searched"] and not rep["blind"],
        f"{rep['run_not_searched']} {rep['blind'][:3]}")
    arm("V2 the canary through the REAL Ctx.sql is RESPONSIVE",
        _rung(S, "canary", "nucleus/sqlguard/canary.py") == "RESPONSIVE", _rung(S, "canary", "nucleus/sqlguard/canary.py"))
    arm("V3 twin texts: the executed twin climbs", _rung(S, "v3_twin_a") == "RESPONSIVE", _rung(S, "v3_twin_a"))
    arm("V3 twin texts: the identical, unexecuted twin gets NO credit", _rung(S, "v3_twin_b") == "UNEXECUTED",
        _rung(S, "v3_twin_b"))
    arm("V4 a STORED bool constant is not graded (RESPONSIVE)", _rung(S, "v4_stored_bool") == "RESPONSIVE",
        _rung(S, "v4_stored_bool"))
    arm("computed-DATA constant via Ctx.sql is GREEN (RESPONSIVE)", _rung(S, "data_const") == "RESPONSIVE",
        _rung(S, "data_const"))
    arm("#3 a projected computed-bool constant via Ctx.sql stays RED (EXECUTED)",
        _rung(S, "p3_projected") == "EXECUTED", _rung(S, "p3_projected"))
    for fn, why in (("pct_literal", "a %-literal"), ("bad_column", "a bad column"), ("fake_conn", "a FakeConn"),
                    ("never_run", "never run")):
        arm(f"{why} → UNEXECUTED", _rung(S, fn) == "UNEXECUTED", _rung(S, fn))
    arm("an empty (W) (only ever 0 rows) is not RESPONSIVE", _rung(S, "empty_w") == "EXECUTED", _rung(S, "empty_w"))
    arm("SET search_path after connect → no public credit", _rung(S, "search_path_after") == "EXECUTED/FIXTURE-DDL",
        _rung(S, "search_path_after"))
    cte = [v for k, v in S.items() if k.startswith("subj/arms.py::cte_dml\x1f")]
    arm("CTE-DML is classified WRITE", bool(cte) and cte[0]["write"] is True)
    arm("public DML (a CTE write on live) counts to EXECUTED only", _rung(S, "cte_dml") == "EXECUTED",
        _rung(S, "cte_dml"))
    arm("stamped DML both ways (1 row, 0 rows) → RESPONSIVE (D-B green)", _rung(S, "stamped_update") == "RESPONSIVE",
        _rung(S, "stamped_update"))
    arm("a hand fixture relation → FIXTURE-DDL (M1: no credit carried from another DB)",
        _rung(S, "hand_fixture") == "EXECUTED/FIXTURE-DDL", _rung(S, "hand_fixture"))
    arm("DML beside a hand relation is not credited (D-B red)", _rung(S, "dml_after_hand") == "EXECUTED/FIXTURE-DDL",
        _rung(S, "dml_after_hand"))
    arm("a stamped read BESIDE a hand relation is still credited (per-relation grain)",
        _rung(S, "stamped_beside_hand") == "RESPONSIVE", _rung(S, "stamped_beside_hand"))
    arm("DROP + re-CREATE → capped", _rung(S, "drop_recreate") == "EXECUTED/FIXTURE-DDL", _rung(S, "drop_recreate"))
    arm("a stale schema.sql sha → capped", _rung(S, "stale_sha") == "EXECUTED/FIXTURE-DDL", _rung(S, "stale_sha"))
    recs = []
    for f in sorted(trace.glob("trace-*.jsonl")):
        recs += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    da = [r.get("stamped") for r in recs if r.get("t", "").startswith("select kind, runs from sqlguard_seen")]
    arm("D-A SELECT, ALTER … DROP DEFAULT, SELECT → stamped [True, False]", da == [True, False], str(da))
    dc = drive["dc"]
    dcs = {r.get("stamped") for r in recs if r.get("t", "").startswith("select id, title from goals")}
    arm("D-C uncommitted DDL: the first statement completes < 5s", dc["first_s"] < 5, f"{dc['first_s']:.2f}s")
    arm("D-C ...50 more in that txn < 2s", dc["fifty_s"] < 2, f"{dc['fifty_s']:.2f}s")
    arm("D-C ...never credited, and the fixture DB is gone", dcs == {False} and dc["gone"], f"{dcs} gone={dc['gone']}")
    n = drive["notify"]
    arm("zero NOTIFY reaches live from a fixture (steps + messages)", n["leaked"] == [], str(n["leaked"]))
    arm("zero-NOTIFY positive control: the live listener hears a live NOTIFY", n["probe"] == 1, str(n["probe"]))
    arm("zero-NOTIFY positive control: the fixture's own trigger DID fire inside it", len(n["fixture_inner"]) == 1,
        str(n["fixture_inner"]))
    arm("an untraced child is recorded, and its sites grade NOT SEARCHED",
        "subj/child.py" in rep["untraced"] and _rung(S, "child_site", "subj/child.py") == "NOT SEARCHED",
        f"{rep['untraced']} {_rung(S, 'child_site', 'subj/child.py')}")
    arm("F-b the extractor list is derived at runtime (a tests/ CREATE TABLE; the applier never counts)",
        rc_k == 0 and set(rep["extractors"]) == {"tests/drive.py"}, f"clean rc={rc_k} {rep['extractors']}")

    # asymmetry (C1): a NEGATIVE needs every covering gate at rc=0; the ledger's stored map is digest-keyed
    never = next(k for k in S if k.startswith("subj/arms.py::never_run\x1f"))
    ign = next(k for k in S if k.startswith("subj/ignored_arm.py::"))
    import hashlib
    for rc, want in ((1, "NOT SEARCHED"), (0, "UNEXECUTED")):
        (trace / "gates.tsv").write_text(gates + f"g-crash\t{rc}\n")
        _, r2, err = _py(tmp, _env(tmp, run), "-c", JUDGE_Q, str(trace), json.dumps({never: ["g-crash"]}), "{}")
        arm(f"asymmetry: covering gate rc={rc} → {want}",
            bool(r2) and "sites" in r2 and r2["sites"][never]["rung"] == want,
            (r2 or {}).get("sites", {}).get(never, err))
        stored = {"sha256:" + hashlib.sha256(ign.encode()).hexdigest(): ["g-crash"]}
        _, r3, err = _py(tmp, _env(tmp, run), "-c", JUDGE_Q, str(trace), "{}", json.dumps(stored))
        arm(f"asymmetry via the ledger's DIGEST-keyed stored covering: rc={rc} → {want}",
            bool(r3) and "sites" in r3 and r3["sites"][ign]["rung"] == want,
            (r3 or {}).get("error") or (r3 or {}).get("sites", {}).get(ign, err))
    (trace / "gates.tsv").write_text(gates)

    # env -i: the canary + shim with NOTHING but the three variables check.sh sets
    t2 = tmp / "trace-envi"
    t2.mkdir()
    envi = {"PYTHONPATH": str(tmp / "nucleus" / "sqlguard" / "shim"), "ASTRYX_SQLGUARD_DIR": str(t2),
            "ASTRYX_SQLGUARD_GATE": "g-envi"}
    rc_e = subprocess.run([sys.executable, "-m", "nucleus.sqlguard.canary"], cwd=tmp, env=envi,
                          capture_output=True).returncode
    (t2 / "gates.tsv").write_text(f"g-envi\t{rc_e}\n")
    _, r4, err = _py(tmp, _env(tmp, run), "-c", JUDGE_Q, str(t2), "{}", "{}")
    arm("env -i: the canary is RESPONSIVE under a bare env",
        rc_e == 0 and r4 is not None and _rung(r4["sites"], "canary", "nucleus/sqlguard/canary.py") == "RESPONSIVE",
        f"rc={rc_e} {err if r4 is None else _rung(r4['sites'], 'canary', 'nucleus/sqlguard/canary.py')}")

    # estate-absent: a committed-only tree (no .env, no triggers/), the shape pushed_tree_check and CI run.
    # Built from THIS package, so --against and --mutants reach it. Both gates must say 77 and name why.
    import shutil
    bare = tmp / "bare"
    shutil.copytree(tmp / "nucleus", bare / "nucleus", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(REPO / "nucleus" / "sqlguard" / "ledger.json", bare / "nucleus" / "sqlguard" / "ledger.json")
    (bare / "t").mkdir()
    benv = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp")}
    for mod, extra in (("canary", []), ("enforce", [str(bare / "t")])):
        p = subprocess.run([sys.executable, "-m", f"nucleus.sqlguard.{mod}", *extra], cwd=bare, env=benv,
                           capture_output=True, text=True)
        arm(f"estate-absent: {mod} exits 77 and names .env, never a crash",
            p.returncode == 77 and ".env" in p.stdout and "Traceback" not in p.stderr,
            f"rc={p.returncode} {(p.stdout + p.stderr).strip().splitlines()[-1:]}")
    # deps-absent: .env present, but `-S` drops site-packages, so psycopg is gone (pushed_tree_check's bare python3)
    (bare / ".env").symlink_to((REPO / ".env").resolve())
    for mod, extra in (("canary", []), ("enforce", [str(bare / "t")])):
        p = subprocess.run([sys.executable, "-S", "-m", f"nucleus.sqlguard.{mod}", *extra], cwd=bare, env=benv,
                           capture_output=True, text=True)
        arm(f"deps-absent: {mod} exits 77 and names psycopg, never a crash",
            p.returncode == 77 and "psycopg" in p.stdout and "Traceback" not in p.stderr,
            f"rc={p.returncode} {(p.stdout + p.stderr).strip().splitlines()[-1:]}")
    # positive control: the same bare tree WITH .env and deps runs the canary for real (gate keys on absence only)
    p = subprocess.run([sys.executable, "-m", "nucleus.sqlguard.canary"], cwd=bare, env=benv,
                       capture_output=True, text=True)
    arm("estate-absent control: the same tree with .env runs the canary (rc 0)", p.returncode == 0,
        f"rc={p.returncode} {p.stderr.strip().splitlines()[-1:]}")

    # enforce + ledger, on synthetic reports (state in a fixture DB, never the live table)
    t3 = tmp / "enf"
    t3.mkdir()
    _, E, err = _py(tmp, _env(tmp, run), "tests/enf.py", str(t3))
    if E is None:
        arm("harness: the enforce driver ran", False, err)
        return failed
    has = lambda name, tag: any(r.startswith(tag) for r in E[name]["red"])
    arm("R-NEW a new site below RESPONSIVE → RED", E["new"]["rc"] == 1 and has("new", "R-NEW"), str(E["new"]))
    arm("R-NEW names the admit handle", any("ledger admit" in r for r in E["new"]["red"]), str(E["new"]["red"]))
    arm("a listed debt row passes (rc 0)", E["listed"]["rc"] == 0, str(E["listed"]))
    arm("R-STALE a listed row that climbed", has("climbed", "R-STALE"), str(E["climbed"]))
    arm("R-STALE a listed row whose site vanished", has("vanished", "R-STALE"), str(E["vanished"]))
    arm("canary absent → run-level NOT SEARCHED (77)", E["canary_absent"]["rc"] == 77, str(E["canary_absent"]))
    arm("EX3 a listed extractor's FIXTURE-DDL site is REPORTED, not RED",
        E["ex3_listed"]["rc"] == 0 and any(r.startswith("EX3") for r in E["ex3_listed"]["report"]),
        str(E["ex3_listed"]))
    arm("EX3 control: an UNLISTED extractor → R-EXTRACT + R-NEW",
        has("ex3_unlisted", "R-EXTRACT") and has("ex3_unlisted", "R-NEW"), str(E["ex3_unlisted"]))
    arm("F-b a listed extractor whose gate COMPLETED rc=0 without building → R-EXTRACT (shrink)",
        has("fb_rc0", "R-EXTRACT"), str(E["fb_rc0"]))
    arm("F-b ...but a gate that skipped (77) or failed (1) proves no absence",
        not has("fb_rc77", "R-EXTRACT") and not has("fb_rc1", "R-EXTRACT"), f"{E['fb_rc77']} {E['fb_rc1']}")
    arm("EX2 a listed extractor past its window → R-EXTRACT", has("ex2_clock", "R-EXTRACT"), str(E["ex2_clock"]))
    arm("trip armed (goal not done) → no R-EXTRACT", not has("trip_armed", "R-EXTRACT"), str(E["trip_armed"]))
    arm("trip fired (goal done) → R-EXTRACT", has("trip_fired", "R-EXTRACT"), str(E["trip_fired"]))
    arm("R-CLOCK not before the clock runs out", not has("clock_1", "R-CLOCK"), str(E["clock_1"]))
    arm("R-CLOCK a site NOT SEARCHED past N runs AND T days", has("clock_2", "R-CLOCK"), str(E["clock_2"]))
    arm("R-LEAK this run's fixture DB still present", any("this run's" in r for r in E["leak_1"]["red"]),
        str(E["leak_1"]))
    arm("R-LEAK a foreign fixture DB: not on first sight",
        not any("foreign" in r for r in E["leak_1"]["red"]), str(E["leak_1"]))
    arm("R-LEAK a foreign fixture DB past K runs AND T age", any("foreign" in r for r in E["leak_2"]["red"]),
        str(E["leak_2"]))
    arm("admit refuses: no reason / 'seed' / a RESPONSIVE site / an unknown site / twice",
        all(E["admit_refusals"].values()) and len(E["admit_refusals"]) == 5, str(E["admit_refusals"]))
    arm("admit grows the ledger; the admitted row passes and its REASON prints",
        E["admitted"]["rc"] == 0 and any("harness: the reason" in r for r in E["admitted"]["report"]),
        str(E["admitted"]))
    return failed


# Each mutant breaks ONE property in the copied package; the NAMED arm must go red. (file, old, new, arm substring)
MUTANTS = [
    ("fixture.py", "ok = sha == cur_sha and sig ==", "ok = True or sig ==", "D-A"),
    ("fixture.py", "ok = sha == cur_sha and sig ==", "ok = sig ==", "stale schema.sql sha"),
    ("fixture.py", "ok = bool(text) and text.startswith(STAMP)", "ok = True", "per-relation grain"),
    ("shim/sitecustomize.py", "elif col.type_code == 16:", "elif False:", "#3"),
    ("shim/sitecustomize.py", "elif col.type_code == 16:", "elif True:", "computed-DATA"),
    ("shim/sitecustomize.py", "ft = res.ftable(i)", "ft = 0", "V4"),
    ("shim/sitecustomize.py", "m = _SET_PATH.match(t) or _SET_CFG.search(t)", "m = None", "search_path"),
    ("shim/sitecustomize.py", "if conn is not None and _withheld.get(conn):", "if False:", "50 more"),
    ("shim/sitecustomize.py", 'if env is not None and "ASTRYX_SQLGUARD_DIR" not in env:', "if False:",
     "untraced child"),
    ("shim/sitecustomize.py", "return all(m.values())", "return False", "D-B green"),
    ("normalize.py", '_WRITE = re.compile(r"\\b(', '_WRITE = re.compile(r"^\\s*(', "CTE-DML"),
    ("judge.py", 'if e["write"] and not stamped_fx:', "if False:", "public DML"),
    ("judge.py", "complete = all(gates.get(g, 0) == 0 for g in cov)", "complete = True", "asymmetry"),
    ("judge.py", "old = stored_covering.get(ledger_key(k))", "old = stored_covering.get(k)", "DIGEST"),
    ("judge.py", "if not any(f[0] == APPLIER for f in fr):", "if True:", "F-b the extractor list"),
    ("enforce.py", 'red.append(f"R-NEW {label(key)}', 'report.append(f"R-NEW {label(key)}', "R-NEW a new site"),
    ("enforce.py", "if gs and all(gates.get(g) == 0 for g in gs):", "if True:", "proves no absence"),
    ("enforce.py", "if runs >= LEAK_RUNS and now - first >= LEAK_AGE:", "if True:", "not on first sight"),
    ("enforce.py", "if not canary or any(", "if False and any(", "canary absent"),
    ("enforce.py", "if runs > NS_RUNS and age.days >= NS_DAYS:", "if True:", "R-CLOCK not before"),
    ("ledger.py", 'if lk in doc["rows"]:', "if False:", "admit refuses"),
    ("estate.py", "if not env.is_file():", "if False:", "estate-absent: canary"),
    ("estate.py", "if not env.is_file():", "if False:", "estate-absent: enforce"),
    ("estate.py", "if missing:", "if False:", "deps-absent: enforce"),
    ("estate.py", "if missing:", "if False:", "deps-absent: canary"),
    ("enforce.py", 'gate("enforce"', 'print("enforce"', "estate-absent: enforce"),
]


def mutant_battery(only=None):
    """RED-first, mechanised: every mutant must be KILLED by the arm it names (not merely by some arm)."""
    import tempfile
    survived = []
    todo = [m for m in MUTANTS if not only or only in m[3]]
    for f, old, new, want in todo:
        def mutate(tmp, f=f, old=old, new=new):
            p = tmp / "nucleus" / "sqlguard" / f
            s = p.read_text()
            if s.count(old) != 1:
                raise SystemExit(f"mutant anchor absent or ambiguous in {f}: {old!r}")
            p.write_text(s.replace(old, new))
        with tempfile.TemporaryDirectory(prefix="sqlguard-mut-") as d:
            failed = harness_arms(Path(d), quiet=True, mutate=mutate)
        hit = [a for a in failed if want in a]
        print(f"  {'KILLED  ' if hit else 'SURVIVED'} {f}: {old[:50]!r} → {new[:22]!r}  ({(hit or failed)[:2]})")
        if not hit:
            survived.append(f"{f}: {old}")
    print(f"\nmutants: {len(todo) - len(survived)}/{len(todo)} killed by their named arm")
    return 1 if survived else 0


def propagate_arms():
    """F-a: the ONE opt-in helper. Outside a trace it returns the oracle's env UNCHANGED (it never widens a stated
    env); inside one it adds exactly the sqlguard variables and the shim path, keeping what the oracle set."""
    import os
    sys.path.insert(0, str(REPO))
    from nucleus.sqlguard import propagate
    saved = {k: v for k, v in os.environ.items() if k.startswith("ASTRYX_SQLGUARD_")}
    try:
        for k in saved:
            del os.environ[k]
        base = {"PATH": "/usr/bin", "PYTHONPATH": "/oracle/own"}
        check("F-a outside a trace: the stated env comes back unchanged", propagate.env_for_child(base) == base)
        os.environ.update(ASTRYX_SQLGUARD_DIR="/tmp/sg-probe", ASTRYX_SQLGUARD_GATE="g", ASTRYX_SQLGUARD_RUN="r")
        out = propagate.env_for_child(base)
        extra = set(out) - set(base)
        check("F-a inside a trace: adds ONLY the sqlguard variables",
              extra == {"ASTRYX_SQLGUARD_DIR", "ASTRYX_SQLGUARD_GATE", "ASTRYX_SQLGUARD_RUN"}, str(extra))
        pp = out["PYTHONPATH"].split(os.pathsep)
        check("F-a ...puts the shim FIRST and keeps the oracle's own PYTHONPATH",
              pp[0].endswith(os.path.join("sqlguard", "shim")) and pp[1:] == ["/oracle/own"], out["PYTHONPATH"])
        check("F-a ...and never mutates the dict it was given", base == {"PATH": "/usr/bin", "PYTHONPATH": "/oracle/own"})
    finally:
        for k in ("ASTRYX_SQLGUARD_DIR", "ASTRYX_SQLGUARD_GATE", "ASTRYX_SQLGUARD_RUN"):
            os.environ.pop(k, None)
        os.environ.update(saved)


def main():
    import tempfile
    args = sys.argv[1:]
    if "--mutants" in args:
        i = args.index("--mutants")
        return mutant_battery(args[i + 1] if i + 1 < len(args) else None)
    if not (REPO / ".env").exists():
        print("NOT SEARCHED: no .env (ASTRYX_DSN), so the harness can't reach postgres. Nothing was verified.")
        return 77
    if "--against" in args:                    # RED-first: this harness against an OLDER package
        rev = args[args.index("--against") + 1]
        with tempfile.TemporaryDirectory(prefix="sqlguard-h-") as d:
            harness_arms(Path(d), rev=rev)
        print(f"\n{'FAIL' if fails else 'PASS'}: sqlguard harness against {rev} ({len(fails)} failing)")
        return 1 if fails else 0
    args = [a for a in args if not a.startswith("--")]
    path = Path(args[0]) if args else REPO / "nucleus" / "sqlguard" / "ledger.json"
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
    propagate_arms()
    with tempfile.TemporaryDirectory(prefix="sqlguard-h-") as d:
        harness_arms(Path(d))
    print(f"\n{'FAIL' if fails else 'PASS'}: sqlguard oracle ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
