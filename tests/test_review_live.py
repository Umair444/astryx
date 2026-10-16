#!/usr/bin/env python3
"""Oracle: devtools/review_live.py runs a branch's code against the LIVE tree (a3 night-review 10-16, seed #56224).

    REVIEW_LIVE_SRC=<path> …   (the subject; default devtools/review_live.py)

Every arm MEASURES, through the subject's own CLI, a probe the child runs:
  L1 a module loaded from the EXTRACT has REPO = the live root (the subject's own repo), not the extract
  L2 a fixture tree's root is left alone (an oracle's fake repo still judges itself)
  L3 on a throwaway fixture DB (never prod), a CREATE under the child's default session is refused through EVERY path:
     L3a psycopg on a DSN the tool never saw (the PGOPTIONS guard), L3b asyncpg on ASTRYX_DSN (asyncpg ignores
     PGOPTIONS: the DSN rewrite, a4 #56228), L3c psycopg on ASTRYX_DSN; the same three WITHOUT the tool succeed
  L4 ASTRYX_AGENT set in the caller is absent in the child (nothing it runs posts as the reviewer's turn)
  L5 a DSN already carrying options= is refused (URI and key=value); one without gains the option, its query kept
Hermetic for L1/L2/L4 (no DB). L3 needs a fixture DB: SKIP (exit 77) if none is reachable.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("REVIEW_LIVE_SRC") or REPO / "devtools" / "review_live.py").resolve()
LIVE = SUBJECT.parents[1]                      # the subject answers the tree it lives in
sys.path.insert(0, str(REPO / "src"))

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


TD = Path(tempfile.mkdtemp(prefix="review-live-"))
EX = TD / "extract"                            # a branch extract: the package, nothing else
shutil.copytree(REPO / "src" / "astryx", EX / "src" / "astryx", ignore=shutil.ignore_patterns("__pycache__"))
FX = TD / "fixture"                            # an oracle's fake repo: must keep judging itself
(FX / "src" / "astryx").mkdir(parents=True)
(FX / "src" / "astryx" / "x.py").write_text("")
PROBE = TD / "probe.py"
PROBE.write_text(f"""
import json, os
import astryx.paths as P
import astryx.core.deps as D                   # imported AFTER the patch, as any measured module is
out = {{"deps_repo": str(D.REPO), "deps_file": D.__file__, "fixture_root": str(P.repo_root({str(FX / 'src/astryx/x.py')!r})),
       "agent": os.environ.get("ASTRYX_AGENT"), "write": None}}
if os.environ.get("PROBE_RAW_DSN"):
    import asyncio, asyncpg, psycopg
    def pg(dsn):
        with psycopg.connect(dsn) as c:
            try:
                c.execute("CREATE TABLE review_live_probe (x int)"); c.execute("DROP TABLE review_live_probe")
                return "allowed"
            except Exception as e:
                return type(e).__name__
    async def apg(dsn):
        c = await asyncpg.connect(dsn)
        try:
            await c.execute("CREATE TABLE review_live_probe (x int)"); await c.execute("DROP TABLE review_live_probe")
            return "allowed"
        except Exception as e:
            return type(e).__name__
        finally:
            await c.close()
    out["write"] = {{"raw_psycopg": pg(os.environ["PROBE_RAW_DSN"]), "asyncpg": asyncio.run(apg(os.environ["ASTRYX_DSN"])),
                    "psycopg": pg(os.environ["ASTRYX_DSN"])}}
print("PROBE " + json.dumps(out))
""")


def run_tool(env_extra=None):
    env = dict(os.environ, ASTRYX_AGENT="reviewer-x", **(env_extra or {}))
    r = subprocess.run([sys.executable, str(SUBJECT), str(EX), "--", str(PROBE)], env=env, capture_output=True,
                       text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if l.startswith("PROBE ")]
    return json.loads(line[-1][6:]) if line else {"rc": r.returncode, "err": r.stderr[-400:]}


def run_direct(env_extra=None):
    env = dict(os.environ, PYTHONPATH=str(EX / "src"), **(env_extra or {}))
    r = subprocess.run([sys.executable, str(PROBE)], env=env, capture_output=True, text=True, timeout=120, cwd=TD)
    line = [l for l in r.stdout.splitlines() if l.startswith("PROBE ")]
    return json.loads(line[-1][6:]) if line else {"rc": r.returncode, "err": r.stderr[-400:]}


try:
    print("hermetic:")
    t = run_tool()
    check("L1 a module loaded from the extract has REPO = the live root",
          t.get("deps_repo") == str(LIVE) and str(EX) in (t.get("deps_file") or ""), t)
    d = run_direct()
    check("L1 …while the same probe run directly reads the EXTRACT (the trap the tool exists for)",
          d.get("deps_repo") == str(EX.resolve()), d)
    check("L2 a fixture tree's root is left alone", t.get("fixture_root") == str(FX.resolve()), t)
    check("L4 ASTRYX_AGENT set in the caller is absent in the child", "agent" in t and t["agent"] is None, t)
    import importlib.util
    spec = importlib.util.spec_from_file_location("review_live_subject", SUBJECT)
    RL = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RL)

    def refuses(d):
        try:
            RL.read_only_dsn(d)
        except RL.Refused:
            return True
        return False
    check("L5 a DSN that already carries options= is refused, URI and key=value (never merged or overwritten)",
          refuses("postgresql://u@h/db?options=-c%20statement_timeout%3D5") and refuses("host=h options='-c x=1'"))
    check("L5 …and one without gets the read-only option, its other parameters kept",
          RL.read_only_dsn("postgresql://u@h/db?sslmode=disable").endswith(
              "sslmode=disable&options=-c%20default_transaction_read_only%3Don")
          and RL.read_only_dsn("host=h").endswith("options='-c default_transaction_read_only=on'"))

    print("fixture DB:")
    try:
        from astryx.security.sqlguard.fixture import fixture_db
        cm = fixture_db()
        fx = cm.__enter__()
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP  L3: no fixture DB ({type(e).__name__})")
        print(f"\n{'FAIL' if fails else 'SKIP (partial)'}: review_live ({len(fails)} failing)")
        sys.exit(1 if fails else 77)
    try:
        dsn = fx["dsn"]
        # the fixture hands a key=value DSN; asyncpg takes only URIs, as the estate's asyncpg callers use
        from urllib.parse import quote
        from psycopg.conninfo import conninfo_to_dict
        k = conninfo_to_dict(dsn)
        auth = quote(k.get("user", ""), safe="") + (":" + quote(k["password"], safe="") if k.get("password") else "")
        uri = f"postgresql://{auth}@{k.get('host', '127.0.0.1')}:{k.get('port', 5432)}/{quote(k['dbname'], safe='')}"
        env = {"PROBE_RAW_DSN": dsn, "ASTRYX_DSN": uri}
        tr = run_tool(env)
        w = tr.get("write") or tr
        check("L3a psycopg on a DSN the tool never saw: ReadOnlySqlTransaction (PGOPTIONS)",
              w.get("raw_psycopg") == "ReadOnlySqlTransaction", w)
        check("L3b asyncpg on ASTRYX_DSN: ReadOnlySQLTransactionError (the DSN rewrite)",
              w.get("asyncpg") == "ReadOnlySQLTransactionError", w)
        check("L3c psycopg on ASTRYX_DSN: ReadOnlySqlTransaction", w.get("psycopg") == "ReadOnlySqlTransaction", w)
        dr = run_direct(env)
        d = dr.get("write") or dr
        check("L3 …and all three succeed without the tool (the arms can fail)",
              d and all(v == "allowed" for v in d.values()), d)
    finally:
        cm.__exit__(None, None, None)
finally:
    shutil.rmtree(TD, ignore_errors=True)

print(f"\n{'FAIL' if fails else 'PASS'}: review_live ({len(fails)} failing)")
sys.exit(1 if fails else 0)
