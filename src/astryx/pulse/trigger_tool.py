#!/usr/bin/env python3
"""The `trigger` tool's one implementation (plan-12214, a4 #65062): channel/server.mjs hands it the caller's arguments
and its stamped agent name on stdin, as JSON. rc 0 prints the reply, rc 1 the refusal, and every refusal states the fix.
Cron and python files are judged by what the pulse itself uses (croniter, discover), so there is no second parser.

A row's lifecycle. off_reason NULL = on. Until the contract land `enabled` is still its own column and alone decides
firing (a2 #65100 B4): every writer here sets both in one statement, and the pulse's normalize() brings the reason back
in line after a writer from before the land. Each reason names who sets it and what clears it:
  held          disable                  enable
  standdown     seed's act, as SQL       seed's lift; enable refuses. The tool only touches its caller's own rows, so:
                                           UPDATE triggers SET off_reason='standdown', off_why='<why>', enabled=false WHERE enabled AND <rows>
                                           UPDATE triggers SET off_reason=NULL, off_why=NULL, enabled=true WHERE off_reason='standdown' AND <rows>
                                         Never seed/tool_ship_watch: it is the census guard, and held off it goes dark.
  retired       retire (python: a tombstone too)   set, enable; reconcile, if the tombstone is gone
  fired         a `once` or `at` firing  a set changing the check, schedule or at
  vanished      reconcile: function absent or file won't load      reconcile, when it loads
  bad_schedule  tick                     a set with a good schedule; python: reconcile, on a changed decorator
  storm         the evaluator            enable
  unknown       normalize(): off, written by a writer from before the land       enable
Grade: validation holds on this path only. Same-uid agents can write rows and files directly, and sometimes should.
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves
    import os as _os
    import sys as _sys
    _root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
    _sys.path.insert(0, _os.path.join(_root, "src"))
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
from croniter import croniter
from psycopg.types.json import Jsonb

from astryx import config, paths
from astryx.pulse import pulse, watch

ESTATE = paths.estate(__file__)
NAME = re.compile(r"^[a-z0-9_]+$")
AGENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ACTIONS = ("set", "show", "enable", "disable", "retire", "test")
DEFAULT_SQL_SCHEDULE = "*/5 * * * *"
DEFAULT_WHILE_RENAG = timedelta(days=1)
TEMPLATE = '''from astryx import trigger

@trigger("*/5 * * * *", note="what this watches")
def my_watch(ctx):
    # ctx.sql(query, params) -> list of dicts. ctx.http(url) -> page text. ctx.say(to, body) wakes another agent.
    # ctx.state is a dict kept between runs. A crash keeps the old one, so a wake can repeat, and a crash wakes you.
    # Return a string to fire (it wakes you), None for silence. A check has 30 seconds. schedule is in this decorator.
    return None
'''


class Refuse(Exception):
    pass


def _dur(field: str, value: str) -> timedelta | None:
    if value == "":
        return None
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", str(value))
    if not m or int(m[1]) == 0:
        raise Refuse(f"{field}={value!r} isn't a duration: use a number and s, m, h or d, like 30m or 1d")
    return timedelta(**{{"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m[2]]: int(m[1])})


def _show_dur(d) -> str:
    return "-" if d is None else str(d)


def _now() -> datetime:
    return datetime.now().astimezone()


def _next_fires(schedule: str, n: int = 2) -> list[str]:
    it = croniter(schedule, _now())
    return [it.get_next(datetime).isoformat(timespec="minutes") for _ in range(n)]


def _schedule(value: str) -> str:
    if not croniter.is_valid(value):
        raise Refuse(f"schedule={value!r} isn't a cron expression. Use five fields in server-local time, like "
                     "'0 9 * * *' (daily at 09:00); for one moment, pass at= instead")
    return value


def _at(value: str) -> tuple[datetime, str]:
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        raise Refuse(f"at={value!r} isn't a timestamp. Use ISO form, like 2026-11-08T17:00 (server-local) or with an "
                     "offset, like 2026-11-08T17:00+05:00") from None
    at = at.astimezone()
    if at <= _now():
        raise Refuse(f"at={at.isoformat(timespec='minutes')} is in the past, and server time is "
                     f"{_now().isoformat(timespec='minutes')}. Pick a later moment")
    return at, f"{at.minute} {at.hour} {at.day} {at.month} *"        # only for readers of schedule; tick never reads it


def _probe(conn, sql: str) -> tuple[list, list, bool, list]:
    """Read a query the way the pulse will, twice: names, rows, over cap, and the columns that changed between reads."""
    try:
        names, rows, over = pulse.guarded_read(conn, sql)
        _, again, _ = pulse.guarded_read(conn, sql)
    except psycopg.Error as e:
        raise Refuse(f"the query doesn't run: {str(e).splitlines()[0]}. A watch takes one read-only SELECT, VALUES or "
                     "TABLE statement, with no EXPLAIN or SHOW and no second statement") from None
    churn = sorted({names[i] for a, b in zip(rows, again) for i in range(len(names)) if a[i] != b[i]})
    return names, rows, over, churn


def _churn_warning(churn: list) -> str:
    if not churn:
        return ""
    return (f"\nWARNING: {', '.join(churn)} changed between two reads, and a changing column makes every row new on "
            "every evaluation. Select only the columns that identify the event.")


def _tombstone(agent: str, name: str) -> Path:
    if not AGENT.match(agent) or not NAME.match(name):
        raise Refuse(f"not a valid agent and trigger name: {agent!r}, {name!r}")
    return ESTATE / "triggers" / agent / ".retired" / name


def _tomb_clear(agent: str, names) -> None:
    for n in names:
        _tombstone(agent, n).unlink(missing_ok=True)


def _row(conn, agent: str, name: str) -> dict | None:
    cur = conn.execute("SELECT * FROM triggers WHERE agent=%s AND name=%s", (agent, name))
    r = cur.fetchone()
    return _seen(dict(zip([d.name for d in cur.description], r))) if r else None


def _seen(t: dict) -> dict:
    """The reason as firing sees it: `enabled` decides, so a row a writer from before the land turned off or on reads
    as it will behave, never as a stale reason says (until the pulse's normalize() catches up)."""
    t["off_reason"] = None if t["enabled"] else (t["off_reason"] or "unknown")
    return t


def _kind_of(a: dict, row: dict | None) -> str:
    kind = "sql" if a.get("sql") else "python" if a.get("code") else row["kind"] if row else "heartbeat"
    if row and row["kind"] != kind:
        raise Refuse(f"{row['name']} is a {row['kind']} trigger and this call would make it {kind}. A trigger's kind "
                     "doesn't change: retire it and use a new name")
    return kind


def _set_code(conn, agent: str, a: dict) -> str:
    extra = [k for k in ("schedule", "at", "sql", "on", "after", "renag", "once") if a.get(k) not in (None, "")]
    if extra:
        raise Refuse(f"with code, {', '.join(extra)} can't be set here: a python trigger's schedule and note live in "
                     "its @trigger decorator, and its logic in its code")
    name = str(a.get("name") or "").strip().removesuffix(".py")
    if not NAME.match(name) or not AGENT.match(agent):
        raise Refuse(f"name={a.get('name')!r}: a python trigger's file name must match ^[a-z0-9_]+$")
    directory = ESTATE / "triggers" / agent
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.py"
    # Same directory, so a top-level Path(__file__).parents[2] validates as it will run (a1 #65068). Not *.py, so the
    # pulse's triggers/*/*.py glob can't register it.
    tmp = directory / f".{name}.{os.getpid()}.tmp"
    tmp.write_text(a["code"])
    try:
        pulse.PY = sys.executable
        found = pulse.discover(tmp)
        if isinstance(found, str):
            raise Refuse(f"this file doesn't load, so nothing was written: {found}\nA trigger file looks like:\n{TEMPLATE}")
        names = [t["name"] for t in found]
        if not names:
            raise Refuse(f"this file defines no @trigger function, so nothing was written. A trigger file looks like:\n{TEMPLATE}")
        for t in found:
            if not croniter.is_valid(t["schedule"]):
                raise Refuse(f"{t['name']}'s decorator has schedule={t['schedule']!r}, which isn't a cron expression")
        had = pulse.discover(target) if target.exists() else []
        lost = sorted({t["name"] for t in had} - set(names)) if isinstance(had, list) else []
        unnamed = [n for n in lost if n not in (a.get("drop") or [])]
        if unnamed:
            raise Refuse(f"this write would drop {', '.join(unnamed)}, which the file defines now. Keep them, or pass "
                         f"drop={json.dumps(unnamed)} to say you mean it")
        clash = [r[0] for r in conn.execute("SELECT name FROM triggers WHERE agent=%s AND name = ANY(%s) AND kind<>'python'",
                                            (agent, names)).fetchall()]
        if clash:
            raise Refuse(f"{', '.join(clash)} already exists as a non-python trigger. Retire it and use a new name")
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    _tomb_clear(agent, names)
    return (f"triggers/{agent}/{name}.py written, defining {', '.join(names)}. The pulse registers it within a minute. "
            f"Schedules come from the decorators: "
            + "; ".join(f"{t['name']} '{t['schedule']}'" for t in found))


def _set(conn, agent: str, a: dict) -> str:
    if a.get("code"):
        return _set_code(conn, agent, a)
    name = str(a.get("name") or "")
    if not name:
        raise Refuse("name is required: it names this trigger for later calls")
    row = _row(conn, agent, name)
    kind = _kind_of(a, row)
    if kind == "python":
        raise Refuse(f"{name} is a python trigger: its schedule and note live in its file. Pass code= to rewrite the "
                     "file, or use action=enable, disable or retire")
    if a.get("once") and a.get("renag") not in (None, ""):
        raise Refuse("once and renag can't go together: once retires on its first accepted wake, so renag could never "
                     "fire. Drop one of them")
    if a.get("at") and a.get("sql"):
        raise Refuse("at can't go with sql: at is one moment in time, with no query. For a query, pass sql with once=true")
    if a.get("at") and a.get("schedule"):
        raise Refuse("pass schedule (repeats) or at (one moment), not both")
    if kind == "heartbeat":
        extra = [k for k in ("on", "after", "renag") if a.get(k) not in (None, "")]
        if extra:
            raise Refuse(f"{', '.join(extra)} only apply to a sql watch, and this has no sql. Pass sql=<query>")
    if a.get("on") not in (None, "new", "while"):
        raise Refuse(f"on={a['on']!r}: use new (fires on rows it hasn't seen) or while (fires while the query returns rows)")
    on = a.get("on") or (row["watch"] if row else "new")
    if on == "new" and a.get("after") not in (None, ""):
        raise Refuse("after needs on=while: it means true continuously for that long before the first wake")

    sql = a.get("sql") if a.get("sql") else (row["check_src"] if row else None)
    at, schedule = None, a.get("schedule") or (row["schedule"] if row else None)
    if a.get("at"):
        at, schedule = _at(a["at"])
    elif a.get("schedule"):
        schedule = _schedule(a["schedule"])
    elif schedule is None:
        if kind == "sql":
            schedule = DEFAULT_SQL_SCHEDULE
        else:
            raise Refuse("a time wake needs schedule (cron, server-local, like '0 9 * * *') or at (one moment), and a "
                         "watch needs sql")
    keep = lambda k, col, parse: (parse(k, a[k]) if a.get(k) is not None else (row[col] if row else None))
    renag = keep("renag", "renag", _dur)
    after = keep("after", "after_for", _dur)
    if a.get("once") is not None:
        once = bool(a["once"])
    else:
        once = (row["once"] if row else False) or bool(at)
    if once and renag is not None and a.get("renag") in (None, ""):
        renag = None
    if on == "while" and renag is None and not once:
        renag = DEFAULT_WHILE_RENAG
    if on == "new" and kind == "sql" and row is not None and a.get("on") == "new":
        after = None
    note = a["note"] if a.get("note") is not None else (row["note"] if row else None)
    note = note or None

    warn, count = "", None
    if kind == "sql":
        _, rows, over, churn = _probe(conn, sql)
        count = f"cap reached, over {watch.CAP}" if over else str(len(rows))
        warn = _churn_warning(churn)

    check_changed = not row or (a.get("sql") and a["sql"] != row["check_src"])
    clock_changed = not row or at is not None or (a.get("schedule") and a["schedule"] != row["schedule"])
    state_reset = check_changed or (row and a.get("on") and a["on"] != row["watch"])
    reason = row["off_reason"] if row else None
    if reason == "retired" or (reason == "fired" and (check_changed or clock_changed)) \
            or (reason == "bad_schedule" and a.get("schedule")):
        reason = None
    state = {} if state_reset else (row["state"] if row else {})
    next_fire = at or (_now() if check_changed or clock_changed else row["next_fire"])
    conn.execute(
        """INSERT INTO triggers (agent, name, schedule, kind, check_src, note, next_fire, state, off_reason, enabled,
                                 watch, renag, after_for, once)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (agent, name) DO UPDATE
             SET schedule=EXCLUDED.schedule, check_src=EXCLUDED.check_src, note=EXCLUDED.note,
                 next_fire=EXCLUDED.next_fire, state=EXCLUDED.state, off_reason=EXCLUDED.off_reason, enabled=EXCLUDED.enabled,
                 off_why=CASE WHEN EXCLUDED.off_reason IS NULL THEN NULL ELSE triggers.off_why END,
                 watch=EXCLUDED.watch, renag=EXCLUDED.renag, after_for=EXCLUDED.after_for, once=EXCLUDED.once""",
        (agent, name, schedule, kind, sql, note, next_fire, Jsonb(state), reason, reason is None, on, renag, after, once))
    _tomb_clear(agent, [name]) if NAME.match(name) else None
    return _echo(_row(conn, agent, name), count) + warn


def _echo(t: dict, count=None) -> str:
    what = {"sql": "watch", "heartbeat": "time wake", "python": "python"}[t["kind"]]
    out = [f"{t['name']} set: {what}"]
    if t["once"] and t["kind"] == "heartbeat":
        out.append(f"fires once at {t['next_fire'].isoformat(timespec='minutes')}, server-local; under quota pressure it "
                   "can arrive late, and the wake says by how much")
    else:
        out.append(f"schedule '{t['schedule']}', server-local; next {', '.join(_next_fires(t['schedule']))}")
    if t["kind"] == "sql":
        if t["watch"] == "new":
            out.append(f"on=new: fires on rows it hasn't seen, and the first evaluation fires what is there now ({count} rows)")
            out.append(f"renag {t['renag']}: a row still present fires again, per row" if t["renag"] else
                       "no renag: a row still present fires once, and a stuck row then goes quiet. Pass renag to re-fire it")
        else:
            out.append(f"on=while: fires while rows return ({count} now)"
                       + (f", once true for {t['after_for']}" if t["after_for"] else "")
                       + (f", then every {t['renag']}" if t["renag"] else ""))
        if t["renag"]:
            secs = (croniter(t["schedule"], _now()).get_next(datetime) - _now()).total_seconds()
            if t["renag"].total_seconds() < secs:
                out.append(f"renag is shorter than the schedule, so in effect it means every evaluation")
    if t["once"] and t["kind"] == "sql":
        out.append("once: it turns itself off after its first wake")
    if t["note"]:
        out.append(f"note: {t['note']}")
    if t["off_reason"]:
        out.append(f"OFF, reason {t['off_reason']}" + (f" ({t['off_why']})" if t["off_why"] else ""))
    return "; ".join(out[:2]) + ("\n" + "\n".join(out[2:]) if out[2:] else "")


def _show(conn, agent: str, a: dict) -> str:
    if not a.get("name"):
        rows = conn.execute("SELECT name, kind, schedule, CASE WHEN enabled THEN NULL ELSE COALESCE(off_reason, "
                            "'unknown') END, last_fired, next_fire, note FROM triggers "
                            "WHERE agent=%s ORDER BY name", (agent,)).fetchall()
        if not rows:
            return "(no triggers; nothing wakes you by itself. action=set creates one)"
        return "\n".join(f"{'●' if r[3] is None else '○'} {r[0]} [{r[1]}] '{r[2]}'"
                         + (f" off:{r[3]}" if r[3] else "") + f" next {r[5].isoformat(timespec='minutes')}"
                         f" last {r[4].isoformat(timespec='minutes') if r[4] else 'never'}"
                         + (f" — {r[6]}" if r[6] else "") for r in rows)
    t = _row(conn, agent, a["name"])
    if not t:
        raise Refuse(f"you have no trigger named {a['name']!r}. action=show with no name lists yours")
    state = t["state"] or {}
    lines = [f"{t['name']} [{t['kind']}] schedule '{t['schedule']}', server-local",
             f"state: {'on' if t['off_reason'] is None else 'OFF, reason ' + t['off_reason']}"
             + (f" ({t['off_why']})" if t["off_why"] else ""),
             f"check: {t['check_src'] or '-'}",
             f"note: {t['note'] or '-'}",
             f"last evaluated {t['last_eval']}, last fired {t['last_fired']}, next {t['next_fire']}"]
    if t["off_reason"] is None and t["next_fire"] <= _now() and t["kind"] == "heartbeat" and pulse.pressure(conn):
        lines.append("due, waiting on quota pressure")
    if t["off_reason"] == "standdown":
        lines.append("held by the org's stand-down: seed lifts it, as SQL on off_reason='standdown'")
    if t["kind"] == "sql":
        lines.append(f"watch: on={t['watch']}, renag {_show_dur(t['renag'])}, after {_show_dur(t['after_for'])}, once {t['once']}")
        lines.append(f"memory: {len(state.get('seen', {}))} rows seen, last eval {state.get('eval_ms', '-')} ms"
                     + (f", OVER CAP since {state['over_cap']}: not watching" if state.get("over_cap") else "")
                     + (f", true since {state['since']}" if state.get("since") else ""))
    return "\n".join(lines)


def _enable(conn, agent: str, a: dict) -> str:
    t = _need(conn, agent, a)
    r = t["off_reason"]
    fixes = {"standdown": "the org's stand-down holds it, and seed lifts that",
             "fired": "it already fired. To fire again, set a new at, schedule or check",
             "vanished": "its function or file isn't there. Restore the file, and the pulse turns it on",
             "bad_schedule": "its schedule is bad. Set a good one (python: fix the decorator)"}
    if r in fixes:
        raise Refuse(f"{t['name']} stays off: {fixes[r]}")
    if r is None:
        return f"{t['name']} is already on"
    if t["kind"] == "python":
        _tomb_clear(agent, [t["name"]])
    state = {k: v for k, v in (t["state"] or {}).items() if k != "churn"}
    conn.execute("UPDATE triggers SET off_reason=NULL, off_why=NULL, enabled=true, state=%s WHERE id=%s", (Jsonb(state), t["id"]))
    return f"{t['name']} is on (was {r})"


def _need(conn, agent: str, a: dict) -> dict:
    if not a.get("name"):
        raise Refuse("name is required. action=show with no name lists yours")
    t = _row(conn, agent, a["name"])
    if not t:
        raise Refuse(f"you have no trigger named {a['name']!r}. action=show with no name lists yours")
    return t


def _disable(conn, agent: str, a: dict) -> str:
    t = _need(conn, agent, a)
    if t["off_reason"]:
        return f"{t['name']} is already off, reason {t['off_reason']}. Nothing changed"
    conn.execute("UPDATE triggers SET off_reason='held', off_why=%s, enabled=false WHERE id=%s", (a.get("why") or None, t["id"]))
    return f"{t['name']} is off (held). action=enable turns it back on, and the pulse won't"


def _retire(conn, agent: str, a: dict) -> str:
    t = _need(conn, agent, a)
    if t["off_reason"] == "standdown":
        raise Refuse(f"{t['name']} is held by the org's stand-down: seed lifts that first")
    if t["kind"] == "python":
        tomb = _tombstone(agent, t["name"])
        tomb.parent.mkdir(parents=True, exist_ok=True)
        tomb.write_text(f"{_now().isoformat()} retired by the trigger tool\n")
    conn.execute("UPDATE triggers SET off_reason='retired', off_why=%s, enabled=false WHERE id=%s", (a.get("why") or None, t["id"]))
    return f"{t['name']} retired. It stays off, and the row is kept. action=enable or set brings it back"


def _test(conn, agent: str, a: dict) -> str:
    row = _row(conn, agent, a["name"]) if a.get("name") else None
    sql = a.get("sql") or (row["check_src"] if row and row["kind"] == "sql" else None)
    if sql:
        started = pulse.time.monotonic()
        _, rows, over, churn = _probe(conn, sql)
        ms = int((pulse.time.monotonic() - started) * 500)
        s = watch.step(rows, over, a.get("on") or (row["watch"] if row else "new"), (row or {}).get("state") or {},
                       after=_dur("after", a["after"]) if a.get("after") else (row or {}).get("after_for"),
                       renag=_dur("renag", a["renag"]) if a.get("renag") else (row or {}).get("renag"), now=_now())
        return (f"read {len(rows)} rows in {ms} ms; nothing written and no wake sent.\n"
                + (f"Would fire now:\n{s.body}" if s.body else "Would stay quiet now.") + _churn_warning(churn))
    if a.get("code"):
        raise Refuse("to check a file, use action=set: it validates first and writes nothing if the file doesn't load")
    if row and row["kind"] == "python":
        if a.get("run"):
            out = pulse.run_python(row["check_src"], dict(row["state"] or {}))
            return ("Ran your code with its side effects; its state and wakes were discarded.\n"
                    + (f"Check crashed: {out['error']}" if "error" in out else f"Returned: {out.get('fire')!r}"))
        file = row["check_src"].split("::")[0]
        pulse.PY = sys.executable
        found = pulse.discover(ESTATE / file)
        if isinstance(found, str):
            return f"{file} doesn't load: {found}"
        return (f"{file} loads and defines {', '.join(t['name'] for t in found)}. Its code was NOT run: run=true runs it, "
                "with its side effects, and discards its state and wakes")
    if row:
        return f"{row['name']} is a time wake: next {', '.join(_next_fires(row['schedule']))}, server-local"
    if a.get("schedule"):
        return f"'{_schedule(a['schedule'])}' next fires {', '.join(_next_fires(a['schedule']))}, server-local"
    raise Refuse("nothing to test: pass name, sql or schedule")


def run(agent: str, a: dict, conn) -> str:
    action = a.get("action") or "set"
    if action not in ACTIONS:
        raise Refuse(f"action={action!r}: use one of {', '.join(ACTIONS)}")
    return {"set": _set, "show": _show, "enable": _enable, "disable": _disable, "retire": _retire, "test": _test}[action](conn, agent, a)


def main() -> int:
    req = json.load(sys.stdin)
    try:
        with psycopg.connect(config.dsn(ESTATE / ".env"), autocommit=True) as conn:
            print(run(req["agent"], req.get("args") or {}, conn))
        return 0
    except Refuse as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
