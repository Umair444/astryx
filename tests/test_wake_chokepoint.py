"""Oracle for plan-4227 S1c — the wake chokepoint (R1 + C1 never-rewind + P1-P4 + the Ctx.sql door + O7).

Design: #21239 (shed R1-R4), #21242 (coalesce P1-P4), #21251 (C1.3 atomic per trigger, C1.4 own writer,
C1.5 typed wire reads), build conditions B1/B2 (#21253). Every trigger wake now leaves through the pulse:
a check calls ctx.say(); the pulse delivers it after evaluation, or, when the 5h gauge reads >=85% and
the trigger has no survival flag (premium=0), HOLDS it in held_wakes and releases it on the first tick
below 85% (or with the gauge missing). The check's state commits as usual: a held wake is persisted,
never rewound, so nothing re-detects and nothing floods.

Runs against a THROWAWAY DATABASE (nucleus.sqlguard.fixture: schema.sql applied whole), never the org's.
It drives pulse.process() with fixture triggers whose checks live in a temp dir. It never calls tick(),
whose reconcile() would register and run the org's real triggers (backups, runners) inside a test.

Each arm can go red alone:
  A1  premium=0 check says a wake at 90%        -> no messages row, one held row
  A2  the same wake on 3 more ticks at 90%       -> still ONE held row (byte-identical dedup), n=4
  A3  first tick at 50%                          -> delivered once: held stamp, byte-compatible headers,
                                                    delivery.held_from set (B2); no held row survives
  A4  gauge MISSING                              -> held rows deliver (fail-open)
  A5  premium>0 at 90%                           -> delivered at once, never held
  A6  distinct wakes A then B during a hold      -> both delivered, oldest first (P1: append)
  A7  K+3 distinct wakes to one key              -> newest K delivered + ONE elided marker; the 3 elided
                                                    bodies stay readable in held_wakes (P3)
  A8  supersede=True report wakes                -> one held row (the latest); release delivers only it
  A9  a check that writes INSERT INTO messages   -> refused by the Ctx.sql door (evaluator error), no row
  A10 a check that says then crashes             -> none of its wakes delivered; state not advanced
  A11 the wake writer fails after the state write-> trigger state NOT committed (C1.3 atomic); the next
                                                    tick re-detects and delivers once
  A12 R1: a premium=0 python check at 90% IS evaluated (its state advances) — the omission arm
  A13 R3: a premium=0 heartbeat at 90% is neither delivered nor held; a premium>0 one is delivered
  A14 a RETURNED fire string at 90% is held like any wake, and released with the pulse's own header
  A15 a held wake is visible in wire_emitted (C1.5), and not in messages
  A16 O7: no `INSERT INTO messages` in triggers/**/*.py or in the in-repo modules they import
  A17 a wake to a QUOTA-FREE recipient (the owner, behind a bridge) at 90% is delivered, never held:
      the out-of-band owner alarm fires exactly when quota pressure latches the fleet
  A19 durable=True: a last-resort wake survives a LATER crash of its check; a non-durable wake queued
      by the same evaluation does not (the reviewed default: a crash delivers none)
  A20 D2: tool_ship_watch's own org-news read (the real _news, via the real Ctx) sees a HELD receipt,
      so a held tick can't read as "NOT CONVERGING" (NOT SEARCHED without triggers/)
  A21 released elided rows are pruned after 7 days; unreleased ones are not
  A22 an elided set with NO newer held rows still releases its one marker (and deletes nothing else)
  A23 a trigger deleted while it was being evaluated: its state writes touch 0 rows, the tick doesn't
      crash, and its wake is still delivered once
  A24 D2-b: every `durable=True` ctx.say site in triggers/** (+ their in-repo imports) is DECLARED below with
      its reason; a new use is RED until declared and reviewed (a durable wake whose dedup reads ctx.state
      would re-send on every failing tick)
      (a site counts unless its durable= is the literal False: a variable or a truthy literal counts)
  A25 D2-a: a durable wake survives its check HANGING past the pulse's timeout (delivered once)
  A18 residents() is derived from the agents/ tree: it holds seed, not owner (NOT SEARCHED without it)

Run: venv/bin/python tests/test_wake_chokepoint.py
"""
import ast
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db
except Exception as exc:                                        # noqa: BLE001
    print(f"SKIP: {type(exc).__name__}: {exc} — the chokepoint oracle needs the org runtime (venv + .env + postgres)")
    sys.exit(77)

K = 5
fails = []
# D2-b: the only places a wake may survive its check's failure. Each must dedup on the WIRE.
DURABLE_DECLARED = {
    "triggers/seed/wedge_watch.py": (1, "owner escalation: the out-of-band last-resort alarm; its dedup "
                                        "(_esc_binds) reads the sent row, and owner wakes are never held (D-1)"),
}


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


CHECKS = '''
def emit_one(ctx):
    ctx.say("steward", "alpha", thread="t-x", from_agent="seed")

def emit_seq(ctx):
    n = ctx.state.get("n", 0) + 1
    ctx.state["n"] = n
    ctx.say("steward", f"news {n}", thread="org-news", intent="milestone", from_agent="seed")

def report(ctx):
    n = ctx.state.get("n", 0) + 1
    ctx.state["n"] = n
    ctx.say("seed", f"roster {n}", supersede=True, from_agent="pulse")

def old_style(ctx):
    ctx.sql("INSERT INTO messages (from_agent, to_agent, intent, body) VALUES ('seed','steward','chat','direct')")

def say_then_crash(ctx):
    ctx.state["n"] = ctx.state.get("n", 0) + 1
    ctx.say("steward", "never", from_agent="seed")
    raise RuntimeError("boom")

def counted(ctx):
    n = ctx.state.get("n", 0) + 1
    ctx.state["n"] = n
    ctx.say("steward", f"counted {n}", from_agent="seed")

def fire_str(ctx):
    return "condition X"

def durable_then_hang(ctx):
    ctx.say("owner", "hang alarm", thread="esc-z", intent="chat", from_agent="seed", durable=True)
    import time
    time.sleep(60)

def durable_then_crash(ctx):
    ctx.say("owner", "last resort", thread="esc-y", intent="chat", from_agent="seed", durable=True)
    ctx.say("steward", "not durable", from_agent="seed")
    raise RuntimeError("boom")

def to_owner(ctx):
    ctx.say("owner", "the org has gone quiet", thread="esc-x", intent="chat", from_agent="seed")
'''


def set_gauge(conn, pct):
    conn.execute("DELETE FROM usage_polls")
    conn.execute("DELETE FROM turns WHERE usage_snapshot IS NOT NULL")
    if pct is not None:
        snap = {"state": "fresh", "fetched_at": datetime.now().astimezone().isoformat(),
                "data": {"five_hour_utilization": pct}}
        conn.execute("INSERT INTO usage_polls (state, snapshot) VALUES ('fresh', %s::jsonb)",
                     (json.dumps(snap),))


def make_trigger(conn, name, func, checks, premium=0, kind="python", note=None):
    src = f"{checks}::{func}" if kind == "python" else None
    row = conn.execute(
        "INSERT INTO triggers (agent, name, schedule, kind, check_src, state, enabled, note, premium) "
        "VALUES ('seed', %s, '* * * * *', %s, %s, '{}'::jsonb, true, %s, %s) "
        "RETURNING id, agent, name, schedule, kind, check_src, state, note, premium",
        (name, kind, src, note, premium)).fetchone()
    cols = ["id", "agent", "name", "schedule", "kind", "check_src", "state", "note", "premium"]
    return dict(zip(cols, row))


def fresh(conn, t):
    """re-read the trigger row as the claim would hand it to process()"""
    row = conn.execute("SELECT id, agent, name, schedule, kind, check_src, state, note, premium "
                       "FROM triggers WHERE id=%s", (t["id"],)).fetchone()
    return dict(zip(["id", "agent", "name", "schedule", "kind", "check_src", "state", "note", "premium"], row))


def msgs(conn, like):
    return conn.execute("SELECT from_agent, from_org, to_agent, to_org, thread, intent, body, delivery "
                        "FROM messages WHERE body LIKE %s ORDER BY id", (like,)).fetchall()


def held(conn, like, elided=False):
    return conn.execute("SELECT body, n, elided, released_at FROM held_wakes WHERE body LIKE %s "
                        "AND elided=%s ORDER BY id", (like, elided)).fetchall()


def tick(pulse, conn, *ts):
    pulse.process(conn, [fresh(conn, t) for t in ts], datetime.now().astimezone())


def o7_scan():
    """every `INSERT INTO messages` in trigger code, and in the in-repo modules trigger code imports"""
    pat = re.compile(r"INSERT\s+INTO\s+(?:\"?public\"?\.)?\"?messages\"?\b", re.I)
    seen, todo, hits, durable = set(), [], [], {}
    for p in (REPO / "triggers").rglob("*.py"):
        todo.append(p)
    while todo:
        p = todo.pop()
        if p in seen or not p.exists():
            continue
        seen.add(p)
        src = p.read_text()
        for m in pat.finditer(src):
            hits.append(f"{p.relative_to(REPO)}:{src.count(chr(10), 0, m.start()) + 1}")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            hits.append(f"{p.relative_to(REPO)}: unparseable (closure unknown)")
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "say"
                    and any(k.arg == "durable" and not (isinstance(k.value, ast.Constant) and k.value.value is False)
                            for k in node.keywords)):   # ANY durable= but a literal False counts (a3):
                                                        # durable=flag / durable=1 can't slip past
                rel = str(p.relative_to(REPO))
                durable[rel] = durable.get(rel, 0) + 1
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module]
            for m in mods:
                cand = REPO / (m.replace(".", "/") + ".py")
                if cand.exists():
                    todo.append(cand)
    return hits, len(seen), durable


def main():
    if not (REPO / "triggers").is_dir():                # 4243 r1/r2: ABSENT is NOT SEARCHED, never a FAIL
        print("  NOT SEARCHED  A16/A24 — no triggers/ tree here (gitignored); runs on the org host")
    else:
        hits, nfiles, durable = o7_scan()
        check(f"A16 O7: no INSERT INTO messages in triggers/** + their in-repo imports ({nfiles} files)",
              not hits and nfiles > 0, "; ".join(hits[:12]))       # PRESENT but 0 files scanned → RED
        declared = {f: n for f, (n, _) in DURABLE_DECLARED.items()}
        check("A24 D2-b: the durable=True sites are exactly the declared ones", durable == declared,
              f"found {durable}, declared {declared}")

    with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
        os.environ["ASTRYX_DSN"] = fx["dsn"]        # pulse + pulse_run subprocesses bind to the fixture
        from nucleus import pulse
        if pulse.DSN != fx["dsn"] or not hasattr(pulse, "process"):
            check("pulse binds ASTRYX_DSN from env and exposes process() (the chokepoint seam)", False,
                  f"DSN is fixture: {pulse.DSN == fx['dsn']}, process: {hasattr(pulse, 'process')}")
            return finish()
        real_tree = (REPO / "agents").is_dir()
        if real_tree:
            pulse._residents = None
            r = pulse.residents()
            check("A18 residents() derived from agents/: seed in, owner out", "seed" in r and "owner" not in r,
                  f"{len(r)} residents")
        else:
            print("  NOT SEARCHED  A18 residents() — no agents/ tree here (gitignored); runs on the org host")
        pulse._residents = {"seed", "steward"}      # hermetic: the fixture recipients are the residents
        checks = str(Path(td) / "checks.py")
        Path(checks).write_text(CHECKS)
        conn = psycopg.connect(fx["dsn"], autocommit=True)
        import runpy
        from nucleus.pulse_run import Ctx
        tsw = REPO / "triggers" / "seed" / "tool_ship_watch.py"
        news_fn = runpy.run_path(str(tsw))["_news"] if tsw.exists() else None
        empty_news = news_fn(Ctx({})) if news_fn else None     # before any org-news exists

        # A1/A2/A3 — hold, dedup, release
        set_gauge(conn, 90)
        t = make_trigger(conn, "one", "emit_one", checks)
        tick(pulse, conn, t)
        check("A1 at 90%: no messages row", not msgs(conn, "%alpha%"))
        check("A1 at 90%: one held row", len(held(conn, "alpha")) == 1)
        for _ in range(3):
            tick(pulse, conn, t)
        h = held(conn, "alpha")
        check("A2 3 more ticks: still ONE held row, n=4", len(h) == 1 and h[0][1] == 4, repr(h))
        set_gauge(conn, 50)
        tick(pulse, conn)
        m = msgs(conn, "%alpha%")
        check("A3 below 85%: delivered exactly once", len(m) == 1, repr(m))
        if m:
            fa, fo, ta, to, th, it, body, dv = m[0]
            check("A3 byte-compatible headers (seed→steward, local, thread t-x, intent trigger)",
                  (fa, fo, ta, to, th, it) == ("seed", "local", "steward", "local", "t-x", "trigger"),
                  repr(m[0][:6]))
            check("A3 held stamp prefixes the body (P4)",
                  body.startswith("[held wake · raised ") and "under 5h ≥85% quota pressure]\nalpha" in body, body)
            check("A3 delivery.held_from records the raised time (B2)", bool(dv and dv.get("held_from")), repr(dv))
        check("A3 release liveness: no held row survives a tick below 85%", not held(conn, "alpha"))

        # A4 — gauge missing delivers
        set_gauge(conn, 90)
        t4 = make_trigger(conn, "four", "counted", checks)
        tick(pulse, conn, t4)
        set_gauge(conn, None)
        tick(pulse, conn)
        check("A4 gauge missing: held wake delivered (fail-open)", len(msgs(conn, "%counted 1%")) == 1)

        # A5 — survival flag delivers at once
        set_gauge(conn, 90)
        t5 = make_trigger(conn, "five", "counted", checks, premium=1)
        tick(pulse, conn, t5)
        check("A5 premium>0 at 90%: delivered at once, not held",
              len(msgs(conn, "%counted 1%")) == 2 and not held(conn, "counted 1"))

        # A6/A7 — append, then the visible cap
        t6 = make_trigger(conn, "six", "emit_seq", checks)
        for _ in range(K + 3):
            tick(pulse, conn, t6)
        check(f"A7 {K + 3} distinct wakes held as {K + 3} rows before release",
              len(held(conn, "news %")) + len(held(conn, "news %", elided=True)) == K + 3)
        set_gauge(conn, 50)
        tick(pulse, conn)
        m = [r[6] for r in msgs(conn, "%news %")]
        marker = [b for b in msgs(conn, "%earlier held wakes elided%")]
        check(f"A6/A7 newest {K} delivered, oldest first",
              [b.rsplit("\n", 1)[-1] for b in m] == [f"news {i}" for i in range(4, K + 4)], repr(m))
        check("A7 exactly ONE elided marker, naming 3 and how to read them",
              len(marker) == 1 and "[3 earlier held wakes elided" in marker[0][6]
              and "SELECT body FROM held_wakes" in marker[0][6], repr(marker))
        el = held(conn, "news %", elided=True)
        check("A7 the 3 elided bodies stay readable, marked released",
              [r[0] for r in el] == ["news 1", "news 2", "news 3"] and all(r[3] for r in el), repr(el))

        # A8 — opt-in supersede
        set_gauge(conn, 90)
        t8 = make_trigger(conn, "eight", "report", checks)
        for _ in range(3):
            tick(pulse, conn, t8)
        check("A8 supersede: one held row, the latest", [r[0] for r in held(conn, "roster %")] == ["roster 3"])
        set_gauge(conn, 50)
        tick(pulse, conn)
        check("A8 release delivers only the latest report",
              [r[6].rsplit("\n", 1)[-1] for r in msgs(conn, "%roster %")] == ["roster 3"])

        # A9 — the door
        t9 = make_trigger(conn, "nine", "old_style", checks)
        tick(pulse, conn, t9)
        check("A9 a direct INSERT INTO messages is refused: no row", not msgs(conn, "direct"))
        check("A9 the refusal is loud (evaluator error to the owner)",
              any("nine" in r[6] and "ctx.say" in r[6] for r in msgs(conn, "%check crashed%")))

        # A10 — say then crash
        t10 = make_trigger(conn, "ten", "say_then_crash", checks)
        tick(pulse, conn, t10)
        check("A10 a crashed evaluation delivers none of its wakes", not msgs(conn, "%never%")
              and not held(conn, "never"))
        check("A10 its state is not advanced", fresh(conn, t10)["state"] in ({}, None))

        # A11 — writer fails after the state write: atomic per trigger
        t11 = make_trigger(conn, "eleven", "counted", checks)
        real, calls = pulse.emit, {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("injected writer failure")
            return real(*a, **k)
        pulse.emit = flaky
        try:
            try:
                tick(pulse, conn, t11)
            except Exception:                                   # noqa: BLE001 — a failed trigger may surface
                pass
            check("A11 writer failure: trigger state NOT committed", fresh(conn, t11)["state"] in ({}, None),
                  repr(fresh(conn, t11)["state"]))
            before = len(msgs(conn, "%counted 1%"))
            tick(pulse, conn, t11)
            check("A11 next tick re-detects and delivers once",
                  len(msgs(conn, "%counted 1%")) == before + 1 and fresh(conn, t11)["state"].get("n") == 1)
        finally:
            pulse.emit = real

        # A12/A13 — R1 evaluates python under pressure, R3 heartbeats wait
        set_gauge(conn, 90)
        t12 = make_trigger(conn, "twelve", "counted", checks)
        tick(pulse, conn, t12)
        check("A12 R1: premium=0 python check at 90% IS evaluated (state advanced)",
              fresh(conn, t12)["state"].get("n") == 1)
        hb0 = make_trigger(conn, "hb0", None, checks, kind="heartbeat", note="hb-free")
        hb1 = make_trigger(conn, "hb1", None, checks, kind="heartbeat", note="hb-paid", premium=1)
        tick(pulse, conn, hb0, hb1)
        check("A13 R3: premium=0 heartbeat at 90% neither delivered nor held",
              not msgs(conn, "%hb-free%") and not held(conn, "%hb-free%"))
        check("A13 R3: premium>0 heartbeat at 90% delivered", len(msgs(conn, "%hb-paid%")) == 1)

        # A17 — quota-free recipients are never held
        t17 = make_trigger(conn, "seventeen", "to_owner", checks)
        tick(pulse, conn, t17)
        m = msgs(conn, "%gone quiet%")
        check("A17 wake to owner at 90%: delivered at once, not held",
              len(m) == 1 and m[0][:6] == ("seed", "local", "owner", "local", "esc-x", "chat")
              and not held(conn, "%gone quiet%"), repr(m))

        # A19 — durable survives a later crash, nothing else does
        t19 = make_trigger(conn, "nineteen", "durable_then_crash", checks)
        tick(pulse, conn, t19)
        check("A19 durable owner wake delivered despite the crash", len(msgs(conn, "%last resort%")) == 1)
        check("A19 the non-durable wake of the same crashed evaluation is not delivered or held",
              not msgs(conn, "%not durable%") and not held(conn, "%not durable%"))

        # A25 — a durable wake survives a HANG past the pulse's timeout
        t25 = make_trigger(conn, "twentyfive", "durable_then_hang", checks)
        saved, pulse.CHECK_TIMEOUT = pulse.CHECK_TIMEOUT, 4
        try:
            tick(pulse, conn, t25)
        finally:
            pulse.CHECK_TIMEOUT = saved
        check("A25 durable owner wake delivered once although its check hung and was killed",
              len(msgs(conn, "%hang alarm%")) == 1)
        check("A25 the hang is reported loudly (timed out; emitted, held here at 90%)",
              conn.execute("SELECT count(*) FROM wire_emitted WHERE body LIKE '%twentyfive%' "
                           "AND body LIKE '%timed out%'").fetchone()[0] == 1)

        # A14/A15 — returned fire strings take the same path; wire_emitted sees held rows
        t14 = make_trigger(conn, "fourteen", "fire_str", checks)
        tick(pulse, conn, t14)
        check("A14 returned fire at 90%: held, not delivered",
              not msgs(conn, "%condition X%") and len(held(conn, "%condition X%")) == 1)
        we = conn.execute("SELECT src FROM wire_emitted WHERE body LIKE '%condition X%'").fetchall()
        check("A15 wire_emitted shows the held wake (src=held)", we == [("held",)], repr(we))
        set_gauge(conn, 50)
        tick(pulse, conn)
        m = msgs(conn, "%condition X%")
        check("A14 released with the pulse's own header",
              len(m) == 1 and m[0][0] == "pulse" and m[0][2] == "seed" and "[trigger fourteen] condition X" in m[0][6],
              repr(m))
        # A20 — the emitted-read sees held wakes
        if news_fn:
            check("A20 D2: the org-news read is empty on an empty wire", empty_news == "", repr(empty_news))
            conn.execute("INSERT INTO held_wakes (agent, trigger, from_agent, to_agent, thread, intent, body) "
                         "VALUES ('seed','tool_ship_watch','seed','steward','org-news','milestone',"
                         "'held receipt zq-4227')")
            news = news_fn(Ctx({}))
            check("A20 D2: tool_ship_watch._news sees a held org-news receipt", "held receipt zq-4227" in news)
        else:
            print("  NOT SEARCHED  A20 — no triggers/ tree here (gitignored); runs on the org host")

        # A21 — the 7-day prune
        conn.execute("DELETE FROM held_wakes")
        conn.execute("INSERT INTO held_wakes (agent, trigger, from_agent, to_agent, body, elided, released_at) "
                     "VALUES ('seed','p','seed','steward','old', true, now() - interval '8 days'), "
                     "('seed','p','seed','steward','recent', true, now() - interval '1 day')")
        set_gauge(conn, 50)
        pulse.release(conn)
        left = [r[0] for r in conn.execute("SELECT body FROM held_wakes ORDER BY id").fetchall()]
        check("A21 prune: the 8-day-old released elided row is gone, the 1-day-old one stays",
              left == ["recent"], repr(left))
        # A22 — an orphaned elided set still announces itself
        conn.execute("DELETE FROM held_wakes")
        conn.execute("INSERT INTO held_wakes (agent, trigger, from_agent, to_agent, body, elided) "
                     "VALUES ('seed','orphan','seed','steward','lost-ish', true)")
        pulse.release(conn)
        mk = msgs(conn, "[1 earlier held wakes elided%")
        check("A22 an elided set with no newer rows releases exactly one marker",
              len(mk) == 1 and mk[0][2] == "steward", repr(mk))
        check("A22 the elided row stays readable, marked released",
              conn.execute("SELECT count(*) FROM held_wakes WHERE body='lost-ish' AND elided "
                           "AND released_at IS NOT NULL").fetchone()[0] == 1)

        # A23 — a trigger that vanishes mid-evaluation
        t23 = make_trigger(conn, "twentythree", "counted", checks)
        stale = fresh(conn, t23)
        conn.execute("DELETE FROM triggers WHERE id=%s", (t23["id"],))
        before = len(msgs(conn, "%counted 1%"))
        pulse.process(conn, [stale], datetime.now().astimezone())
        check("A23 vanished trigger: no crash, its wake delivered once",
              len(msgs(conn, "%counted 1%")) == before + 1)
        conn.close()
    return finish()


def finish():
    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    print("\nPASS: every trigger wake leaves through the pulse; held, never rewound, never lost (4227 S1c)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
