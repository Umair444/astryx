#!/usr/bin/env python3
"""The isolation pins of tests/test_plan_lifecycle.py must match THIS TREE's schema.sql (goal 4227 S3).

test_plan_lifecycle refuses to run its live-DB scenarios unless every DB trigger on the tables it
writes is pinned (AUDITED_TRIGGERS) at the sha256 of its pg_get_functiondef — the audit that the
trigger cannot escape a rolled-back transaction. Those pins are compared against the LIVE database,
so a branch that changes a pinned trigger (S3 changed goals_done_stamp and added
goals_budget_frozen) reads GREEN in every review and goes RED only after the live apply — the
isolation premise then breaks mid-deploy, with nobody holding the change. (seed #23672.)

This oracle moves that failure to REVIEW time: it builds a sqlguard fixture from the branch's own
schema.sql and requires every trigger on those tables to be pinned at the hash this schema
produces. A trigger change without a re-audit is RED on the branch that makes it. It reads the pins
by AST (never executes the lifecycle oracle), so it runs in a worktree with no triggers/.
It does NOT audit a body — a human re-reads pg_get_functiondef and pins it; this only proves the
pins describe the schema being shipped. Exit 0 pass · 1 fail · 77 no DB / no CREATEDB.
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_audited_trigger_pins", REPO, deps=("psycopg",))
import psycopg  # noqa: E402
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

LIFECYCLE = REPO / "tests" / "test_plan_lifecycle.py"
tree = ast.parse(LIFECYCLE.read_text())
consts = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
          for t in n.targets if isinstance(t, ast.Name) and t.id in ("AUDITED_TRIGGERS", "WRITE_TABLES")}
if set(consts) != {"AUDITED_TRIGGERS", "WRITE_TABLES"}:
    print("FAIL: test_plan_lifecycle.py no longer declares AUDITED_TRIGGERS/WRITE_TABLES at top level")
    sys.exit(1)
PINS = ast.literal_eval(consts["AUDITED_TRIGGERS"])
TABLES = ast.literal_eval(consts["WRITE_TABLES"])

_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(77)
try:
    with psycopg.connect(fx["dsn"]) as c:
        rows = c.execute(
            "SELECT c.relname, t.tgname, encode(sha256(pg_get_functiondef(t.tgfoid)::bytea), 'hex') "
            "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname = ANY(%s)", (list(TABLES),)).fetchall()
finally:
    _fx.__exit__(None, None, None)

built = {(t, g): h for t, g, h in rows}
fails = []
for key, h in sorted(built.items()):
    pin = PINS.get(key)
    if pin is None:
        fails.append(f"{key[0]}.{key[1]} is in schema.sql but NOT pinned — audit its body, pin {h}")
    elif pin != h:
        fails.append(f"{key[0]}.{key[1]} pinned {pin[:12]}… but schema.sql builds {h[:12]}… — re-audit")
for key in sorted(set(PINS) - set(built)):
    fails.append(f"{key[0]}.{key[1]} is pinned but schema.sql no longer creates it — drop the pin")
for f in fails:
    print(f"  FAIL  {f}")
if fails:
    sys.exit(1)
print(f"audited trigger pins: {len(built)} trigger(s) on {'/'.join(TABLES)} pinned at the hashes this "
      f"schema.sql builds")
sys.exit(0)
