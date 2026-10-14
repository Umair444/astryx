"""fixture_db's stamp signer and its checker read a relation's signature under ONE fixed search_path (a3 #50071).

format_type() and pg_get_expr() render names relative to the caller's search_path. A signer and a checker on
different paths disagree about a relation that never changed, and one such mismatch withholds DB-grain credit from
every write in the fixture (forge #50063).
  P1 (arm): an extra that LEAVES search_path at a private schema (and ag_catalog), with a column typed by that
     schema's enum and defaulted by nextval('<schema>.seq'::regclass). Every org relation stamps valid: 0 invalid.
  P2 (arm): a checker side connection opened while the DSN's own options set a hostile path still reads 0 invalid.
  P3 (CONTROL): ALTER the private table → exactly that relation reads invalid. The checker can still say no.
Mutants: tests/mutants_fixture_sigpath.py (mutation_probe, via SQLGUARD_FIXTURE_SRC).
Exit 0 pass · 1 fail · 77 no reachable server (nothing verified).
"""
import os
import sys
from pathlib import Path

for _k in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_k]
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_fixture_sigpath", REPO, deps=("psycopg",))
SRC = os.environ.get("SQLGUARD_FIXTURE_SRC") or str(REPO / "nucleus" / "sqlguard" / "fixture.py")  # mutation_probe swaps it
import importlib.util  # noqa: E402
os.environ.setdefault("ASTRYX_SQLGUARD_ROOT", str(REPO))
_sp = importlib.util.spec_from_file_location("fixture_under_test", SRC)
fxm = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(fxm)
fxm.PREFIX = f"astryx_fx_sptest{os.getpid()}_"      # private prefix: this oracle's reap() sees only its own DBs

import psycopg  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


EXTRA = (
    "CREATE SCHEMA sp_x; CREATE TYPE sp_x.mood AS ENUM ('a','b'); CREATE SEQUENCE sp_x.s; "
    "CREATE TABLE sp_x.t (id bigint DEFAULT nextval('sp_x.s'::regclass), m sp_x.mood)",
    "SET search_path = sp_x, ag_catalog",            # the extra leaves its path behind, as memgraph's AGE DDL did
)


def invalid(dbname):
    m = fxm.db_stamp_map(dbname)
    return m, sorted(o for o, ok in m.items() if not ok)


try:
    with fxm.fixture_db(extra=EXTRA) as fx:
        name = fx["dbname"]
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            t_oid = c.execute("SELECT 'sp_x.t'::regclass::oid").fetchone()[0]
            cmt = c.execute("SELECT obj_description(%s, 'pg_class')", (t_oid,)).fetchone()[0] or ""
        m, bad = invalid(name)
        check("P1: an extra that leaves search_path at its own schema → every org relation stamps valid",
              len(m) == fx["relations"] and m.get(t_oid) is True and not bad,
              f"map={len(m)} relations={fx['relations']} sp_x.t={m.get(t_oid)} invalid={bad[:5]}")
        check("P1: ...and the private table was stamped at all", cmt.startswith(fxm.STAMP), repr(cmt[:40]))

        fxm._side.pop(name).close()                  # reopen the checker under a DSN that sets a hostile path
        live = fxm.live_dsn
        fxm.live_dsn = lambda: fxm.make_conninfo(live(), options="-c search_path=sp_x,ag_catalog")
        try:
            m2, bad2 = invalid(name)
        finally:
            fxm.live_dsn = live
            s = fxm._side.pop(name, None)
            if s is not None:
                s.close()
        check("P2: a checker whose connection STARTS on a hostile path still reads 0 invalid",
              m2 and not bad2, f"map={len(m2)} invalid={bad2[:5]}")

        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            c.execute("ALTER TABLE sp_x.t ADD COLUMN z int")
        m3, bad3 = invalid(name)
        check("P3 CONTROL: ALTER the private table → exactly it reads invalid", bad3 == [t_oid],
              f"invalid={bad3[:5]} want=[{t_oid}]")
except fxm.FixtureUnavailable as e:
    print(f"  SKIP  no fixture server ({e})")
    sys.exit(77)

print(f"\n{'FAIL' if fails else 'PASS'}  test_fixture_sigpath ({len(fails)} failed)")
sys.exit(1 if fails else 0)
