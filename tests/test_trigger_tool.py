#!/usr/bin/env python3
"""plan-12214 slice 1, against a fixture database: the migration from the real table's shape, the pulse's one-shot and
wake-acceptance rules, the guarded read, and the `trigger` tool's naive-path table. The design and its conditions:
a4 #65062, #65072, #65074; a3 #65066, #65081; a1 #65068, #65079; a2 #65070, #65078. Pure watch logic is
tests/test_trigger_watch.py. Needs a fixture database, else 77."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
fails = []


def check(label, ok, why=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{str(why)[:300]}]" if why != "" and not ok else ""))
    if not ok:
        fails.append(label)


try:
    import psycopg
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
    from astryx.security.sqlguard import estate
    from astryx.pulse import pulse, trigger_tool as tool, watch
except ImportError as e:
    print(f"SKIP: deps ({e}). Nothing was verified here.")
    sys.exit(77)

# the mutation probe's seams
for _env, _name in (("PULSE_SRC", "pulse_under_test"), ("TOOL_SRC", "tool_under_test")):
    if os.environ.get(_env):
        import importlib.util
        _spec = importlib.util.spec_from_file_location(_name, os.environ[_env])
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        if _env == "PULSE_SRC":
            _mod.REPO = REPO                # the copy lives outside the tree: its children still run from here
            pulse = _mod
            tool.pulse = _mod
        else:
            _mod.pulse = pulse
            tool = _mod

# The table as it stands on origin/main at this plan's base (32f27dbe), read from its schema.sql.
OLD_TABLE = """
DROP TABLE triggers;
CREATE TABLE triggers (
  id bigserial PRIMARY KEY, agent text NOT NULL, name text NOT NULL, schedule text NOT NULL,
  kind text NOT NULL DEFAULT 'heartbeat', check_src text, state jsonb NOT NULL DEFAULT '{}',
  enabled boolean NOT NULL DEFAULT true, last_eval timestamptz, last_fired timestamptz,
  next_fire timestamptz NOT NULL DEFAULT now(), note text, premium bigint NOT NULL DEFAULT 0, UNIQUE (agent, name));
CREATE INDEX triggers_due ON triggers (next_fire) WHERE enabled;
"""
OLD_RM = "UPDATE triggers SET enabled=false WHERE agent='a' AND name='h0'"
OLD_SET = ("INSERT INTO triggers (agent, name, schedule, kind, check_src, note, next_fire) "
           "VALUES ('a','brand_new','* * * * *','heartbeat',null,null, now()) ON CONFLICT (agent, name) DO UPDATE "
           "SET schedule='* * * * *', enabled=true, next_fire=now()")


def schema_block() -> str:
    """The migration block, exactly as schema.sql carries it."""
    s = (REPO / "src/astryx/sql/schema.sql").read_text()
    a = s.index("DO $$ BEGIN\n  IF (SELECT is_generated")
    return s[a:s.index("END $$;", a) + len("END $$;")] + "\nCREATE INDEX IF NOT EXISTS triggers_due ON triggers (next_fire) WHERE enabled;"


def columns(c):
    return dict(c.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='triggers' "
                          "AND table_schema=current_schema()").fetchall())


def constraints(c):
    return {r[0]: r[1] for r in c.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE "
                                          "conrelid='triggers'::regclass AND contype='c'").fetchall()}


def migration(fx):
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        fresh_cols, fresh_cons = columns(c), constraints(c)
        order = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='triggers' "
                                         "AND table_schema=current_schema() ORDER BY ordinal_position").fetchall()]
        c.execute(OLD_TABLE)
        # the live proportions, 11-07: heartbeat 40 off/9 on, python 14/61, sql 5/2, 9 of the off heartbeats stood down
        for kind, off, on in (("heartbeat", 40, 9), ("python", 14, 61), ("sql", 5, 2)):
            for i in range(off + on):
                note = "STAND-DOWN (owner 10-30)" if kind == "heartbeat" and i < 9 else None
                c.execute("INSERT INTO triggers (agent,name,schedule,kind,enabled,note,check_src) VALUES "
                          "('a',%s,'* * * * *',%s,%s,%s,%s)",
                          (f"{kind[0]}{i}", kind, i >= off, note, "select 1" if kind == "sql" else None))
        c.execute("INSERT INTO triggers (agent,name,schedule,note) VALUES ('a','on_with_note','* * * * *','mentions the stand-down')")
        # This code on a database that lags (a sibling org, or the land's own window; a4 #65062's blocker)
        c.execute("UPDATE triggers SET next_fire = now() - interval '1 minute' WHERE kind='heartbeat'")
        clocks = c.execute("SELECT sum(extract(epoch from next_fire)) FROM triggers").fetchone()
        pulse.tick()
        said = c.execute("SELECT to_agent, body FROM messages WHERE body LIKE '[trigger schema pending]%'").fetchall()
        check("B1 the new pulse on an old table: no trigger evaluated, every clock unmoved",
              c.execute("SELECT sum(extract(epoch from next_fire)) FROM triggers").fetchone() == clocks
              and c.execute("SELECT count(*) FROM triggers WHERE last_eval IS NOT NULL").fetchone()[0] == 0)
        check("B2 ...and it says so to its seed, with the command, never journal-only",
              len(said) == 1 and said[0][0] == "seed" and "apply_schema.py --all" in said[0][1], said)
        pulse.tick()
        check("B3 ...once while that wake is unread",
              c.execute("SELECT count(*) FROM messages WHERE body LIKE '[trigger schema pending]%'").fetchone()[0] == 1)
        c.execute("DELETE FROM messages")
        c.execute(schema_block())
        check("B4 once applied, the same predicate reads ready", pulse.schema_ready(c))
        r = dict(c.execute("SELECT enabled, count(*) FROM triggers GROUP BY 1").fetchall())
        check("M1 72+1 on and 59 off survive exactly (backfill before the drop, a2 #65070 BC-3)", r == {True: 73, False: 59}, r)
        rs = dict(c.execute("SELECT off_reason, count(*) FROM triggers WHERE NOT enabled GROUP BY 1").fetchall())
        check("M2 stood-down rows are standdown, python off rows are derived, the rest unknown (a3 BC-2)",
              rs == {"standdown": 9, "vanished": 14, "unknown": 36}, rs)
        check("M3 a row that is on stays on, whatever its note says",
              c.execute("SELECT enabled FROM triggers WHERE name='on_with_note'").fetchone()[0] is True)
        due = c.execute("SELECT indexdef FROM pg_indexes WHERE tablename='triggers' AND indexname='triggers_due'").fetchone()
        check("M4 triggers_due is back, on the new column", due and "WHERE enabled" in due[0], due)
        check("M5 the migrated table has the columns and constraints a fresh one has",
              columns(c) == fresh_cols and constraints(c) == fresh_cons, (columns(c), constraints(c)))
        check("M6 ...and in the same order (a2's open question: schema_parity reads a map, but a fresh and a migrated "
              "table should still read alike)",
              [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='triggers' "
                                       "AND table_schema=current_schema() ORDER BY ordinal_position").fetchall()] == order)
        before = c.execute("SELECT count(*) FILTER (WHERE enabled), count(*) FROM triggers").fetchone()
        c.execute(schema_block())
        check("M7 a re-apply is a no-op", c.execute("SELECT count(*) FILTER (WHERE enabled), count(*) FROM triggers").fetchone() == before)
        for label, q in (("trigger_rm", OLD_RM), ("trigger_set, on a brand-new name", OLD_SET)):
            try:
                c.execute(q)
                check(f"M8 an old body's {label} is refused", False)
            except psycopg.Error as e:
                check(f"M8 an old body's {label} is refused, with the error org-news quotes",
                      "can only be updated to DEFAULT" in str(e), e)
        try:
            c.execute("INSERT INTO triggers (agent,name,schedule,kind) VALUES ('a','typo','* * * * *','cron')")
            check("M9 a kind typo is refused at the table", False)
        except psycopg.Error:
            check("M9 a kind typo is refused at the table, from any writer", True)
        c.execute("INSERT INTO triggers (agent,name,schedule,kind) VALUES ('a','spawned','0 9 * * *','heartbeat') "
                  "ON CONFLICT (agent,name) DO NOTHING")
        check("M10 spawn.sh's insert still works", c.execute("SELECT enabled FROM triggers WHERE name='spawned'").fetchone()[0] is True)
        c.execute("DELETE FROM triggers")


def guarded(c):
    for label, sql in (("multi-statement", "SELECT 1; CREATE TEMP TABLE g1(a int)"), ("DDL", "CREATE TEMP TABLE g2(a int)"),
                       ("a write", "WITH d AS (DELETE FROM triggers RETURNING 1) SELECT * FROM d")):
        try:
            pulse.guarded_rows(c, sql)
            check(f"G1 {label} is refused", False)
        except psycopg.Error:
            check(f"G1 {label} is refused, and the connection stays usable", c.execute("SELECT 1").fetchone() == (1,))
    try:
        pulse.guarded_rows(c, "SELECT pg_sleep(3)", timeout_ms=200)
        check("G2 a slow query is cancelled", False)
    except psycopg.errors.QueryCanceled:
        check("G2 a slow query is cancelled", True)
    check("G3 LIKE, a CTE and a trailing ; all read",
          pulse.guarded_rows(c, "WITH a AS (SELECT 'tom' x) SELECT x FROM a WHERE x LIKE 'to%';")[0] == [("tom",)])
    rows, over = pulse.guarded_rows(c, "SELECT generate_series(1, 500)", cap=10)
    check("G4 the cap holds, and says it was passed", len(rows) == 10 and over)
    check("G5 known pass, named so nobody rounds the grade up: pg_notify runs in the read-only cursor (a1 #65068)",
          pulse.guarded_rows(c, "SELECT pg_notify('astryx_test_nobody', 'x')")[1] is False)


def set_ok(c, **a):
    return tool.run("a", a, c)


def refused(c, needle, **a):
    try:
        return f"not refused: {tool.run('a', a, c)}"
    except tool.Refuse as e:
        return "" if needle in str(e) else f"refused, but without {needle!r}: {e}"


def naive(c, tree):
    """The naive path: each is correct behaviour or a refusal that teaches. kind is gone, so a kind typo has no way in."""
    arms = (("a bad cron", "cron expression", dict(name="x", schedule="every day", note="n")),
            ("no schedule, no at, no sql", "needs schedule", dict(name="x", note="n")),
            ("a past at", "in the past", dict(name="x", at="2020-01-01T00:00")),
            ("a bad at", "isn't a timestamp", dict(name="x", at="tomorrow 5pm")),
            ("schedule and at", "not both", dict(name="x", at="2099-01-01T00:00", schedule="0 9 * * *")),
            ("at with sql", "at can't go with sql", dict(name="x", at="2099-01-01T00:00", sql="SELECT 1")),
            ("once with renag (a2 #65078)", "can't go together", dict(name="x", sql="SELECT 1", once=True, renag="1h")),
            ("after on new", "needs on=while", dict(name="x", sql="SELECT 1", after="1h")),
            ("renag on a time wake", "only apply to a sql watch", dict(name="x", schedule="0 9 * * *", renag="1h")),
            ("a bad duration", "isn't a duration", dict(name="x", sql="SELECT 1", renag="soon")),
            ("multi-statement sql", "one read-only SELECT", dict(name="x", sql="SELECT 1; SELECT 2")),
            ("EXPLAIN (a2 #65070)", "SELECT, VALUES or", dict(name="x", sql="EXPLAIN SELECT 1")),
            ("a guessed column", "doesn't run", dict(name="x", sql="SELECT nope FROM triggers")),
            ("an unknown action", "use one of", dict(action="delete", name="x")),
            ("a bad on", "use new", dict(name="x", sql="SELECT 1", on="change")),
            ("show on a name you don't have", "no trigger named", dict(action="show", name="nope")),
            ("enable a name you don't have", "no trigger named", dict(action="enable", name="nope")),
            ("a path as a python name", "must match", dict(name="../../hooks/step", code="x=1")),
            ("code that doesn't load", "doesn't load", dict(name="broken", code="def (")),
            ("schedule beside code", "can't be set here", dict(name="y", code="x=1", schedule="0 9 * * *")))
    for label, needle, a in arms:
        r = refused(c, needle, **a)
        check(f"N {label} is refused with its fix", r == "", r)
    check("N no refused call left a row", c.execute("SELECT count(*) FROM triggers WHERE agent='a'").fetchone()[0] == 0)
    check("N no path traversal wrote anything, and no temp file is left",
          not list((tree / "triggers").glob("a/.*.tmp")) and not (tree / "hooks").exists())



def teach(c, tree):
    r = refused(c, "def my_watch(ctx)", name="empty", code="x = 1\n")
    check("T1 code with no @trigger returns the template (a1 #65079 BC-5)", r == "", r)
    for word in ("ctx.sql", "ctx.http", "ctx.say", "ctx.state", "None for silence", "30 seconds", "from astryx import trigger"):
        check(f"T2 the template names {word}", word in tool.TEMPLATE)
    check("T3 the template's 30 seconds is the pulse's", pulse.CHECK_TIMEOUT == 30)
    path = tree / "tpl.py"
    path.write_text(tool.TEMPLATE)
    pulse.PY = sys.executable
    check("T4 the template itself loads", [t["name"] for t in pulse.discover(path)] == ["my_watch"])


def patch(c):
    r = set_ok(c, name="w", sql="SELECT 1 AS one", note="first", schedule="*/5 * * * *")
    check("P1 the reply echoes the row, next fires in server-local time", "next " in r and "server-local" in r, r)
    check("P2 a watch with no renag says a stuck row goes quiet (a3 BC-9)", "goes quiet" in r and "renag" in r, r)
    check("P3 first-evaluation behaviour is stated", "first evaluation" in r, r)
    set_ok(c, name="w", note="second")
    t = tool._row(c, "a", "w")
    check("P4 F1a: a one-field set keeps the check, the kind and the schedule",
          t["check_src"] == "SELECT 1 AS one" and t["kind"] == "sql" and t["schedule"] == "*/5 * * * *" and t["note"] == "second", t)
    c.execute("UPDATE triggers SET state='{\"seen\":{\"k\":\"2026-01-01T00:00:00+00:00\"}}', next_fire=now()+interval '9 hours' WHERE name='w'")
    before = tool._row(c, "a", "w")
    set_ok(c, name="w", note="third")
    t = tool._row(c, "a", "w")
    check("P5 a note edit keeps watch state and doesn't move the clock (a2 #65055)",
          t["state"] == before["state"] and t["next_fire"] == before["next_fire"], t)
    set_ok(c, name="w", sql="SELECT 2 AS two")
    t = tool._row(c, "a", "w")
    check("P6 a changed check resets state and is due", t["state"] == {} and t["next_fire"] <= tool._now(), t)
    c.execute("UPDATE triggers SET state='{\"seen\":{\"k\":\"x\"}}' WHERE name='w'")
    set_ok(c, name="w", on="while")
    t = tool._row(c, "a", "w")
    check("P7 a changed `on` resets state (a3 #65081); while's default renag applies, and is echoed",
          t["state"] == {} and t["renag"] == timedelta(days=1), t)
    set_ok(c, name="w", note="")
    check("P8 an explicit \"\" clears a field", tool._row(c, "a", "w")["note"] is None)
    set_ok(c, name="w", on="new", renag="")
    check("P9 renag \"\" clears it", tool._row(c, "a", "w")["renag"] is None)
    check("P10 a sql watch defaults to a 5-minute schedule, echoed",
          "*/5" in set_ok(c, name="w2", sql="SELECT 1"))
    r = refused(c, "kind doesn't change", name="w", schedule="0 9 * * *", code="from astryx import trigger\n")
    r2 = refused(c, "can't be set here", name="w", schedule="0 9 * * *", code="from astryx import trigger\n")
    check("P11 code beside a schedule on a sql name is refused", r == "" or r2 == "", (r, r2))
    set_ok(c, name="hb", schedule="0 9 * * *", note="n")
    r = refused(c, "kind doesn't change", name="hb", sql="SELECT 1")
    check("P12 kind doesn't change", r == "", r)
    c.execute("UPDATE triggers SET next_fire=now()+interval '9 hours' WHERE name='hb'")
    r = set_ok(c, name="hb", note="edited")
    check("P13 a heartbeat's note edit doesn't fire it next tick", tool._row(c, "a", "hb")["next_fire"] > tool._now(), r)


def churn(c):
    r = set_ok(c, name="age", sql="SELECT 1 AS id, clock_timestamp() - timestamptz '2020-01-01' AS age", renag="1h")
    check("C1 set warns of a changing column, naming it (a1 #65079 BC-6)", "WARNING" in r and "age" in r, r)
    check("C2 ...and the row is still made", tool._row(c, "a", "age") is not None)
    check("C3 test reports it too, writing nothing (a2 #65078)",
          "WARNING" in tool.run("a", {"action": "test", "name": "age"}, c))
    check("C4 a stable query doesn't warn", "WARNING" not in set_ok(c, name="stable", sql="SELECT 1 AS id"))


def lifecycle(c, tree):
    set_ok(c, name="w", sql="SELECT 1 AS id", note="n")
    tool.run("a", {"action": "disable", "name": "w", "why": "busy"}, c)
    t = tool._row(c, "a", "w")
    check("L1 disable holds, with its why", t["off_reason"] == "held" and t["off_why"] == "busy" and not t["enabled"], t)
    set_ok(c, name="w", note="edited")
    check("L2 a note edit doesn't revive a disabled row (a2 #65055)", tool._row(c, "a", "w")["off_reason"] == "held")
    tool.run("a", {"action": "enable", "name": "w"}, c)
    check("L3 enable clears held", tool._row(c, "a", "w")["enabled"] is True)
    tool.run("a", {"action": "retire", "name": "w", "why": "done"}, c)
    t = tool._row(c, "a", "w")
    check("L4 retire keeps the row (spawn.sh would recreate a deleted one)", t and t["off_reason"] == "retired", t)
    set_ok(c, name="w", note="back")
    check("L5 set revives retired", tool._row(c, "a", "w")["enabled"] is True)
    for reason in ("standdown", "fired", "vanished", "bad_schedule"):
        c.execute("UPDATE triggers SET off_reason=%s WHERE name='w'", (reason,))
        r = refused(c, "stays off", action="enable", name="w")
        check(f"L6 enable refuses {reason}, with the fix", r == "", r)
    c.execute("UPDATE triggers SET off_reason='standdown' WHERE name='w'")
    check("L7 show says who lifts a stand-down", "seed lifts" in tool.run("a", {"action": "show", "name": "w"}, c))
    r = refused(c, "stand-down", action="retire", name="w")
    check("L8 retire can't quietly end a stand-down hold", r == "", r)
    c.execute("UPDATE triggers SET off_reason='fired' WHERE name='w'")
    set_ok(c, name="w", note="note only")
    check("L9 a note edit leaves a fired row off", tool._row(c, "a", "w")["off_reason"] == "fired")
    set_ok(c, name="w", sql="SELECT 2 AS id")
    check("L10 a set changing the check re-arms a fired row", tool._row(c, "a", "w")["enabled"] is True)
    c.execute("UPDATE triggers SET off_reason='storm', state='{\"churn\":9}' WHERE name='w'")
    tool.run("a", {"action": "enable", "name": "w"}, c)
    t = tool._row(c, "a", "w")
    check("L11 enable clears storm, and its count", t["enabled"] and "churn" not in t["state"], t)
    c.execute("UPDATE triggers SET off_reason='bad_schedule', schedule='nonsense' WHERE name='w'")
    set_ok(c, name="w", schedule="0 9 * * *")
    check("L12 a good schedule clears bad_schedule", tool._row(c, "a", "w")["enabled"] is True)
    listing = tool.run("a", {"action": "show"}, c)
    check("L13 show lists yours, on and off", "w [sql]" in listing, listing)
    c.execute("INSERT INTO triggers (agent,name,schedule) VALUES ('other','theirs','0 9 * * *')")
    check("L14 another agent's row isn't yours", "theirs" not in listing and "no trigger named" in refused(c, "zzz", action="show", name="theirs"))
    c.execute("UPDATE triggers SET off_reason='unknown' WHERE name='w'")
    tool.run("a", {"action": "enable", "name": "w"}, c)
    check("L15 enable clears unknown", tool._row(c, "a", "w")["enabled"] is True)


PY_FILE = '''from astryx import trigger

@trigger("*/5 * * * *", note="one")
def zt_one(ctx):
    return None

@trigger("*/5 * * * *", note="two")
def zt_two(ctx):
    return None
'''
TOP_LEVEL = '''from pathlib import Path
from astryx import trigger
ROOT = Path(__file__).absolute().parents[2]
if not (ROOT / "marker").exists():
    raise SystemExit("wrong root")

@trigger("*/5 * * * *", note="uses its root")
def zt_root(ctx):
    return None
'''


def python_path(c, tree):
    r = set_ok(c, name="zt.py", code=PY_FILE)
    check("Y1 a '.py' name lands on one file, defining its functions",
          (tree / "triggers/a/zt.py").exists() and "zt_one, zt_two" in r, r)
    check("Y2 no temp file is left, and nothing the pulse's glob would register",
          [p.name for p in (tree / "triggers/a").iterdir() if p.is_file()] == ["zt.py"])
    pulse.reconcile(c)
    check("Y3 the pulse registers them", tool._row(c, "a", "zt_one")["enabled"] is True)
    kept = PY_FILE[:PY_FILE.index('@trigger("*/5 * * * *", note="two")')]
    r = refused(c, "would drop zt_two", name="zt", code=kept)
    check("Y4 a write that drops a defined function is refused, and names it", r == "", r)
    check("Y5 ...and the file is unchanged", (tree / "triggers/a/zt.py").read_text() == PY_FILE)
    r = set_ok(c, name="zt", code=kept, drop=["zt_two"])
    check("Y6 drop= says you mean it", "zt_one" in r and "zt_two" not in r, r)
    pulse.reconcile(c)
    check("Y7 the dropped function's row goes off as vanished", tool._row(c, "a", "zt_two")["off_reason"] == "vanished")
    set_ok(c, name="zt", code=PY_FILE)
    pulse.reconcile(c)
    check("Y8 a restored file turns it back on (a3 BC-2)", tool._row(c, "a", "zt_two")["enabled"] is True)
    tool.run("a", {"action": "disable", "name": "zt_two"}, c)
    pulse.reconcile(c)
    check("Y9 a held python row stays held through reconcile: the stand-down gap", tool._row(c, "a", "zt_two")["off_reason"] == "held")
    tool.run("a", {"action": "enable", "name": "zt_two"}, c)
    tool.run("a", {"action": "retire", "name": "zt_one"}, c)
    pulse.reconcile(c)
    check("Y10 a tombstone holds through reconcile", tool._row(c, "a", "zt_one")["off_reason"] == "retired")
    tool.run("a", {"action": "enable", "name": "zt_one"}, c)
    pulse.reconcile(c)
    check("Y11 enable clears the tombstone, so reconcile leaves it on", tool._row(c, "a", "zt_one")["enabled"] is True)
    (tree / "triggers/a/.retired").mkdir(exist_ok=True)
    c.execute("UPDATE triggers SET off_reason='retired' WHERE name='zt_two'")
    pulse.reconcile(c)
    check("Y12 a retired row whose tombstone is gone comes back: the tombstone is the authority", tool._row(c, "a", "zt_two")["enabled"] is True)
    c.execute("UPDATE triggers SET off_reason='bad_schedule' WHERE name='zt_two'")
    pulse.reconcile(c)
    check("Y13 reconcile leaves bad_schedule off while the decorator is unchanged", tool._row(c, "a", "zt_two")["off_reason"] == "bad_schedule")
    c.execute("UPDATE triggers SET schedule='nonsense' WHERE name='zt_two'")
    pulse.reconcile(c)
    check("Y14 ...and clears it when the decorator changes", tool._row(c, "a", "zt_two")["enabled"] is True)
    (tree / "triggers/a/broken.py").write_text("from astryx import trigger\n@trigger('* * * * *')\ndef zt_b(ctx):\n    return None\n")
    pulse.reconcile(c)
    (tree / "triggers/a/broken.py").write_text("def (\n")
    pulse.reconcile(c)
    check("Y15 a file that won't load: its row is vanished, not forgotten", tool._row(c, "a", "zt_b")["off_reason"] == "vanished")
    (tree / "triggers/a/broken.py").unlink()
    (tree / "marker").write_text("")
    r = set_ok(c, name="rooted", code=TOP_LEVEL)
    check("Y16 a top-level parents[2] validates as it will run (a1 #65068 BC-1)", "zt_root" in r, r)
    r = set_ok(c, name="named", code='import pathlib\nfrom astryx import trigger\n'
               'pathlib.Path(__file__).with_name("validated_as").write_text(pathlib.Path(__file__).name)\n'
               '@trigger("* * * * *")\ndef zt_named(ctx):\n    return None\n')
    validated = (tree / "triggers/a/validated_as").read_text()
    (tree / "triggers/a/validated_as").unlink()
    check("Y16b validation's temp file sits outside the pulse's triggers/*/*.py glob, in the same directory",
          not validated.endswith(".py"), validated)
    tool.run("a", {"action": "retire", "name": "zt_one"}, c)
    set_ok(c, name="zt", code=PY_FILE)
    check("Y16c a set clears the tombstones of the names it writes (a3 BC-2)", not (tree / "triggers/a/.retired/zt_one").exists())
    r = set_ok(c, name="lone", code='from astryx import trigger\n@trigger("* * * * *")\ndef zt_lone(ctx):\n    return None\n')
    pulse.reconcile(c)
    c.execute("INSERT INTO triggers (agent,name,schedule) VALUES ('a','clash','0 9 * * *')")
    r = refused(c, "non-python", name="clash_file", code='from astryx import trigger\n@trigger("* * * * *")\ndef clash(ctx):\n    return None\n')
    check("Y17 a function can't take a non-python row's name", r == "", r)
    r = tool.run("a", {"action": "test", "name": "zt_one"}, c)
    check("Y18 test on python loads it and says the code did NOT run", "NOT run" in r and "run=true" in r, r)
    ran, saved = [], pulse.run_python
    pulse.run_python = lambda src, state: (ran.append(src), {"state": state, "fire": None})[1]
    r = tool.run("a", {"action": "test", "name": "zt_one", "run": True}, c)
    pulse.run_python = saved
    check("Y19 run=true runs it, and says so", ran and "side effects" in r and "None" in r, r)
    r = refused(c, "python trigger", name="zt_one", note="x")
    check("Y20 a python row's fields are its file's", r == "", r)


def tick_rules(c):
    def row(n):
        return tool._row(c, "a", n)

    def wakes(name=None):
        return c.execute("SELECT count(*) FROM messages WHERE to_agent='a' AND from_agent='pulse' AND body LIKE %s",
                         (f"[trigger {name}]%",)).fetchone()[0]
    # at
    r = set_ok(c, name="dl", at="2099-01-01T17:00", note="pay the rent")
    t = row("dl")
    check("A1 at is a one-shot time wake, stating it can be late (a1 BC-2)", t["once"] and "late" in r, r)
    check("A2 at's pin is only for readers: next_fire holds the instant", t["next_fire"].year == 2099, t)
    c.execute("UPDATE triggers SET next_fire=now()-interval '3 hours' WHERE name='dl'")
    pulse.reconcile = lambda conn: False                 # python plumbing out of this arm's way; it's the claim under test
    held = _tick_claim_only(c)
    check("A3 a crash between claim and process leaves it DUE (a3 #65060 §2): the clock didn't move",
          "dl" in held and row("dl")["next_fire"] < tool._now(), row("dl"))
    _tick(c)
    t = row("dl")
    check("A4 the next tick fires it and retires it as fired", t["off_reason"] == "fired" and wakes("dl") == 1, (t["off_reason"], wakes("dl")))
    body = c.execute("SELECT body FROM messages WHERE body LIKE '[trigger dl]%'").fetchone()[0]
    check("A5 the wake says the note, the due time and how late (a1 BC-2)", "pay the rent" in body and "min late" in body and "due " in body, body)
    _tick(c)
    check("A6 it fires once", wakes("dl") == 1)
    set_ok(c, name="dl2", at="2099-01-01T17:00", note="again")
    c.execute("UPDATE triggers SET next_fire=now() WHERE name='dl2'")
    c.execute("INSERT INTO messages (from_agent,to_agent,intent,body) VALUES ('pulse','a','trigger','[trigger dl2] earlier, unread')")
    _tick(c)
    check("A7 an unread earlier wake never swallows a deadline", wakes("dl2") == 2)
    c.execute("UPDATE triggers SET off_reason=NULL WHERE name='dl'")
    c.execute("UPDATE triggers SET off_reason='held' WHERE name='dl2'")
    t = dict(_due_row(c, "dl"))
    c.execute("UPDATE triggers SET off_reason='fired' WHERE name='dl'")
    n = wakes("dl")
    pulse.process(c, [t], tool._now(), hot=False)
    check("A8 a row another claim already fired doesn't fire twice", wakes("dl") == n, wakes("dl"))

    # F1h, through process()
    set_ok(c, name="fh", sql="SELECT 'a' AS id")
    _tick(c)
    check("B1 first evaluation fires", wakes("fh") == 1)
    c.execute("UPDATE triggers SET check_src='SELECT ''a'' AS id UNION ALL SELECT ''b''', next_fire=now() WHERE name='fh'")
    _tick(c)
    check("B2 the earlier wake is unread, so this one is swallowed", wakes("fh") == 1)
    k = watch.row_key(("b",))
    check("B3 F1h: the swallowed row isn't recorded as told (recorder on the old code: state advanced, no wake)",
          k not in row("fh")["state"]["seen"], row("fh")["state"])
    c.execute("UPDATE messages SET status='delivered' WHERE to_agent='a'")
    c.execute("UPDATE triggers SET next_fire=now() WHERE name='fh'")
    _tick(c)
    check("B4 once read, the next evaluation tells it", wakes("fh") == 2 and k in row("fh")["state"]["seen"], wakes("fh"))

    # once on a watch
    set_ok(c, name="os", sql="SELECT 1 AS id", once=True)
    _tick(c)
    t = row("os")
    check("C1 once on a watch fires and retires as fired, and its clock had advanced", t["off_reason"] == "fired" and wakes("os") == 1, t["off_reason"])
    set_ok(c, name="oq", sql="SELECT 1 AS id WHERE false", once=True)
    _tick(c)
    t = row("oq")
    check("C2 once on a watch with no rows waits, its clock moving (it polls)", t["enabled"] and t["next_fire"] > tool._now(), t)

    # an evaluator error: never burns a one-shot, and a kind this can't run is said
    set_ok(c, name="oe", sql="SELECT 1 AS id", once=True)
    c.execute("UPDATE triggers SET check_src='SELECT nope' WHERE name='oe'")
    _tick(c)
    check("D1 a failing check wakes its author and doesn't burn the one-shot",
          wakes("oe") == 1 and row("oe")["enabled"] is True, row("oe")["off_reason"])
    try:
        pulse.evaluate({"kind": "cron", "check_src": None, "state": {}}, c)
        check("D2 evaluate raises on a kind it can't run (F1b)", False)
    except ValueError:
        check("D2 evaluate raises on a kind it can't run (F1b): a loud evaluator-error wake, never a silent guard", True)

    # storm reaches the row
    set_ok(c, name="st", sql="SELECT clock_timestamp()")
    for _ in range(watch.STORM_K + 1):
        c.execute("UPDATE messages SET status='delivered' WHERE to_agent='a'")
        c.execute("UPDATE triggers SET next_fire=now() WHERE name='st'")
        _tick(c)
    check("E1 storm turns the row off, and tells the author", row("st")["off_reason"] == "storm"
          and c.execute("SELECT count(*) FROM messages WHERE body LIKE '[trigger st] storm%'").fetchone()[0] == 1)

    # shed: a late reminder stays visible
    set_ok(c, name="sh", at="2099-01-01T17:00", note="n")
    c.execute("UPDATE triggers SET next_fire=now()-interval '1 hour' WHERE name='sh'")
    saved = pulse.pressure
    pulse.pressure = lambda conn: True
    n = wakes("sh")
    _tick(c)
    check("F1 hot gauge: the deadline waits, unfired, unretired", wakes("sh") == n and row("sh")["enabled"] is True)
    check("F2 show says it's waiting on quota pressure", "waiting on quota pressure" in tool.run("a", {"action": "show", "name": "sh"}, c))
    pulse.pressure = saved
    _tick(c)
    body = c.execute("SELECT body FROM messages WHERE body LIKE '[trigger sh]%'").fetchone()
    check("F3 gauge cools: it fires, naming both times", body and "due " in body[0] and "min late" in body[0], body)

    # the stand-down lift
    set_ok(c, name="sd", schedule="0 9 * * *")
    c.execute("UPDATE triggers SET off_reason='held' WHERE name='sd'")
    set_ok(c, name="sd2", schedule="0 9 * * *")
    c.execute("UPDATE triggers SET off_reason='standdown', off_why='owner' WHERE name='sd2'")
    c.execute("UPDATE triggers SET off_reason=NULL, off_why=NULL WHERE off_reason='standdown'")
    check("G1 seed's lift revives stood-down rows and never an author's hold",
          row("sd2")["enabled"] is True and row("sd")["off_reason"] == "held")


def _due_row(c, name):
    cur = c.execute("SELECT id, agent, name, schedule, kind, check_src, state, note, premium, watch, renag, after_for, once, "
                    "next_fire FROM triggers WHERE name=%s", (name,))
    return zip([d.name for d in cur.description], cur.fetchone())


def _due(c):
    return [r[0] for r in c.execute("SELECT name FROM triggers WHERE enabled AND next_fire <= now()").fetchall()]


def _tick_claim_only(c):
    """tick(), stopped dead between its claim and process(): a crash in that gap."""
    saved = pulse.process

    def crash(*a, **k):
        raise KeyboardInterrupt
    pulse.process = crash
    names = _due(c)
    try:
        _tick(c)
    except KeyboardInterrupt:
        pass
    finally:
        pulse.process = saved
    return names


def _tick(c):
    pulse.tick()


def apply_schema():
    """devtools/apply_schema.py over several orgs, each lagging: a4 #65062's land blocker. Fixture database names can't
    enter a real registry, so the launch is the arm's; what runs in each org is the real --one modes."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("apply_schema", REPO / "devtools" / "apply_schema.py")
    tool_ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool_)
    script = str(REPO / "devtools" / "apply_schema.py")
    with fixture_db() as one, fixture_db() as two:
        dsns = {"first": one["dsn"], "broken": "postgresql://nobody@127.0.0.1:1/none", "second": two["dsn"]}
        for fx in (one, two):
            with psycopg.connect(fx["dsn"], autocommit=True) as c:
                c.execute(OLD_TABLE)
                c.execute("DROP TABLE IF EXISTS schema_applied")

        def launch(key, o, mode):
            env = {**os.environ, "ASTRYX_DSN": dsns[key], "ASTRYX_COG_REGISTRY": "/nonexistent/cog.json"}
            return subprocess.run([sys.executable, script, mode], capture_output=True, text=True, timeout=300, env=env, cwd=REPO)

        def fan(mode):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = tool_._fan_out(dict.fromkeys(dsns, {}), mode, launch=launch)
            return rc, buf.getvalue()
        rc, out = fan("--one-check")
        check("S1 a check names each org and says it lags", rc == 1 and "first: LAGGING" in out and "second: LAGGING" in out, out)
        with psycopg.connect(two["dsn"], autocommit=True) as c:
            check("S2 ...and changes nothing", not pulse.schema_ready(c))
        rc, out = fan("--one-apply")
        check("S3 an org that fails is said, rc 1, and the org after it still gets its turn",
              rc == 1 and "first: applied" in out and "second: applied" in out and "broken: " in out and "(rc " in out, out)
        for fx in (one, two):
            with psycopg.connect(fx["dsn"], autocommit=True) as c:
                check("S4 each org's own database is migrated and stamped",
                      pulse.schema_ready(c) and c.execute("SELECT count(*) FROM schema_applied").fetchone()[0] == 1)
        del dsns["broken"]
        rc, out = fan("--one-check")
        check("S5 a check then reads current", rc == 0 and "first: current" in out and "second: current" in out, out)


def surviving_names():
    pattern = "trigger_(set|list|rm)" + r"\b"
    p = subprocess.run(["git", "-C", str(REPO), "grep", "-lE", pattern, "--", ".", ":!tests/test_trigger_tool.py"],
                       capture_output=True, text=True)
    if p.returncode not in (0, 1):                    # no .git (the probe's copy, an extract): this arm can't see
        print("  ○  S6 not run: this tree has no git")
        return
    check("S6 no tracked file still names the retired tools (a4 #65062 C3)", p.stdout.strip() == "", p.stdout)
    server = (REPO / "channel" / "server.mjs").read_text()
    check("S7 the server's tool list has `trigger` and the instruction naming it (a2 #65055, a3 #65060)",
          "name: 'trigger'," in server and "CronCreate and ScheduleWakeup die with the session" in server)


def main() -> int:
    tree = Path(tempfile.mkdtemp(prefix="trigger-tool-")).resolve()
    (tree / "triggers").mkdir()
    (tree / "triggers" / "a").mkdir()
    try:
        with fixture_db() as fx:
            os.environ["ASTRYX_DSN"] = fx["dsn"]
            pulse.ESTATE, tool.ESTATE = tree, tree
            pulse.PY = sys.executable
            migration(fx)
            with psycopg.connect(fx["dsn"], autocommit=True) as c:
                def clean():
                    c.execute("DELETE FROM triggers")
                    c.execute("DELETE FROM messages")
                    shutil.rmtree(tree / "triggers" / "a", ignore_errors=True)
                    (tree / "triggers" / "a").mkdir()
                guarded(c)
                for arm in (naive, teach):
                    clean()
                    arm(c, tree)
                for arm in (patch, churn):
                    clean()
                    arm(c)
                clean()
                lifecycle(c, tree)
                clean()
                python_path(c, tree)
                clean()
                tick_rules(c)
            apply_schema()
            surviving_names()
    except FixtureUnavailable as e:
        shutil.rmtree(tree, ignore_errors=True)
        estate.unavailable("test_trigger_tool", REPO, e, fails)
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    print(f"\n{'FAIL' if fails else 'PASS'}: trigger tool ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
