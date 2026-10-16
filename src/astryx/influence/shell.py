#!/usr/bin/env python3
"""astryx · influence shell — the IO around src/astryx/influence/graph.py (plan-11324 S2). No rule lives here.

    venv/bin/python src/astryx/influence/shell.py report   [--days 14]      # read-only: kinds, coverage, GLOBAL view
    venv/bin/python src/astryx/influence/shell.py compute  [--days 14]      # the nightly job: edge cache + GLOBAL values
    venv/bin/python src/astryx/influence/shell.py ask <asker> [--topic T] [--k 5]   # who should I ask (advisory)
    venv/bin/python src/astryx/influence/shell.py backtest [--days 14]      # read-only: routing vs GLOBAL vs uniform

IO, all of it: ONE `git log` pass over main (the parent map, the merges and their subjects); ONE messages read of
exactly the read tools' columns (graph.MSG_COLS, BC-R); econ's tool-ledger reader (econ._v2_tool_rows, per day so
an edge carries its day); the steps liveness proxy; the cache write; the tool's query log. `report` and `backtest`
open a READ-ONLY session. `compute` is the nightly job's verb (its trigger is the scheduler's, not tracked here).
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402

import argparse  # noqa: E402
import os  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from astryx.core import address, charter  # noqa: E402
from astryx.influence import graph  # noqa: E402

REPO = repo_root(__file__)
DAYS = 14
LIVE_W_H = 36          # the liveness proxy's W (>= 24h: a daily-heartbeat agent must read live)
LOOP_W_H = 72          # a task within this long after the tool returned its recipient is ROUTED (loop discount)
SCOPE = "local"
MSG_SQL = ("SELECT id, ts, from_agent, from_org, to_agent, to_org, thread, intent, body FROM messages "
           "WHERE id = ANY(%s) OR (ts >= %s AND ts < %s)")
LIVE_SQL = "SELECT agent, max(ts) FROM steps WHERE ts >= %s GROUP BY agent"
QLOG_THERE = "SELECT to_regclass('influence_query')"
QLOG_SQL = "SELECT asker, returned, ts FROM influence_query WHERE ts >= %s"
QLOG_ADD = "INSERT INTO influence_query (asker, returned, view, liveness) VALUES (%s, %s, %s, %s)"
CACHE_ANY = "SELECT 1 FROM influence_edge WHERE scope = %s LIMIT 1"
CACHE_SQL = "SELECT kind, src, dst, ts, ask_ts, ref, topic, coverage FROM influence_edge WHERE scope = %s"
CACHE_DROP = "DELETE FROM influence_edge WHERE scope = %s"
CACHE_ADD = ("INSERT INTO influence_edge (scope, kind, src, dst, ts, ask_ts, ref, topic, coverage, computed_at) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
VALUE_ADD = ("INSERT INTO influence_value (scope, view, agent, value, unmapped, computed_at) "
             "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (scope, view, agent, computed_at) "
             "DO UPDATE SET value = EXCLUDED.value, unmapped = EXCLUDED.unmapped")


def _dsn() -> str:
    return os.environ.get("ASTRYX_DSN") or next(
        line.split("=", 1)[1].strip() for line in (REPO / ".env").read_text().splitlines()
        if line.startswith("ASTRYX_DSN="))


def connect(dsn=None, readonly=True):
    """autocommit; READ-ONLY by construction unless a verb writes (compute, ask)."""
    import psycopg
    extra = {"options": "-c default_transaction_read_only=on"} if readonly else {}
    return psycopg.connect(dsn or _dsn(), autocommit=True, **extra)


# ── git: ONE pass ─────────────────────────────────────────────────────────────────────────────────────────────────
def git_history(repo=REPO, ref="main"):
    """(commits {sha: {parents, ts, subject}}, tip sha) from one `git log` over `ref`. GIT_* is scrubbed so a hook's
    GIT_DIR can never point this at another repository."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run(["git", "-C", str(repo), "log", "--format=%H%x1f%P%x1f%cI%x1f%s", ref],
                         capture_output=True, text=True, check=True, env=env).stdout
    commits, tip = {}, None
    for line in out.splitlines():
        sha, ps, ts, subject = line.split("\x1f", 3)
        commits[sha] = {"parents": ps.split(), "ts": datetime.fromisoformat(ts), "subject": subject}
        tip = tip or sha
    return commits, tip


# ── the database reads ────────────────────────────────────────────────────────────────────────────────────────────
def read_messages(conn, since, until, ids=()):
    cur = conn.execute(MSG_SQL, (sorted(ids), since, until))
    cols = [d.name for d in cur.description]
    return graph.check_rows([dict(zip(cols, r)) for r in cur.fetchall()])


def read_tool_calls(conn, since, until):
    """econ's ledger reader, one call per day, so a call's edge carries its DAY's end as ts (the reader returns no
    ts; a day-end stamp keeps "strictly before" honest in the backtest). Returns (calls, econ's coverage)."""
    from astryx.econ import econ
    calls, rows, ok = [], [], True
    t = since
    while t < until:
        u = min(t + timedelta(days=1), until)
        day, day_ok = econ._v2_tool_rows(conn, t, u)
        ok = ok and day_ok
        rows += day
        calls += [{"rid": r[0], "caller": r[1], "author": r[2], "dq": r[3], "ts": u} for r in day]
        t = u
    gdp = econ._v2_tool_gdp(rows, econ.V2_VERSION, ok)
    return calls, float(gdp.get("coverage") or 0.0)


def last_steps(conn, since):
    return dict(conn.execute(LIVE_SQL, (since,)).fetchall())


def read_queries(conn, since):
    """The tool's query log since `since`; [] where the table isn't applied yet (read-only verbs run before init.sh)."""
    if conn.execute(QLOG_THERE).fetchone()[0] is None:
        return []
    return [{"asker": a, "returned": list(r), "ts": t} for a, r, t in conn.execute(QLOG_SQL, (since,)).fetchall()]


def read_cache(conn, scope=SCOPE):
    return [{"kind": k, "src": s, "dst": d, "ts": ts, "ask_ts": at, "ref": ref, "topic": tp, "coverage": cov}
            for k, s, d, ts, at, ref, tp, cov in conn.execute(CACHE_SQL, (scope,)).fetchall()]


# ── derive ────────────────────────────────────────────────────────────────────────────────────────────────────────
def derive(conn, since, until, repo=REPO, ref="main", roster=None, queries_since=None):
    """Every kind's ledger for [since, until), from the authorities. Pure graph calls over the reads above."""
    roster = set(roster if roster is not None else charter.roster())
    commits, tip = git_history(repo, ref)
    merges = graph.main_merges(commits, tip, since, until) if tip else []
    cited = {int(i) for m in merges for i in graph.CITED_RE.findall(m["subject"])}
    rows = read_messages(conn, since, until, cited)
    by_id = {r["id"]: r for r in rows}
    parents = {s: c["parents"] for s, c in commits.items()}
    in_window = [r for r in rows if since <= r["ts"] < until]
    ledgers = {"pass_land": graph.pass_land_edges(merges, parents, by_id, roster, address.suggest),
               "delegation": graph.delegation_edges(in_window, roster)}
    queries = read_queries(conn, queries_since or since - timedelta(hours=LOOP_W_H))
    for k in ("pass_land", "delegation"):
        kept, routed = graph.loop_discount(ledgers[k]["edges"], queries, LOOP_W_H * 3600)
        ledgers[k]["edges"] = kept
        if routed:
            ledgers[k]["unmeasured"]["routed by the tool (loop discount)"] += routed
    calls, tcov = read_tool_calls(conn, since, until)
    ledgers["tool_call"] = graph.tool_edges(calls, roster, tcov)
    return ledgers, in_window, calls, roster


def globals_of(ledgers, in_window, calls, roster, now):
    """(GLOBAL values, unmapped share per agent, gated weights, all edges)."""
    w = graph.kind_weights({k: graph.coverage_of(lg) for k, lg in ledgers.items()})
    edges = [e for lg in ledgers.values() for e in lg["edges"]]
    unmapped, active = graph.agent_coverage(in_window, calls, ledgers, w, roster)
    v = graph.global_view(w, active or sorted(roster))
    return graph.scores(edges, v, sorted(roster), now), unmapped, w, edges


# ── the verbs ─────────────────────────────────────────────────────────────────────────────────────────────────────
class Refused(Exception):
    """compute() wrote nothing, for the named reason (graph.refuse_compute)."""


def compute(conn, days=DAYS, repo=REPO, ref="main", now=None, roster=None):
    """The nightly job: replace the scope's edge cache, append the GLOBAL view's values. Returns the report lines.
    REFUSES (raises Refused, writes nothing) on a roster of < 2 names or an empty edge set over a non-empty cache."""
    now = now or datetime.now(timezone.utc)
    ledgers, in_window, calls, roster = derive(conn, now - timedelta(days=days), now, repo, ref, roster)
    values, unmapped, w, edges = globals_of(ledgers, in_window, calls, roster, now)
    cov = {k: graph.coverage_of(lg) for k, lg in ledgers.items()}
    why = graph.refuse_compute(roster, conn.execute(CACHE_ANY, (SCOPE,)).fetchone() is not None, edges)
    if why:
        raise Refused(why)
    with conn.transaction():
        conn.execute(CACHE_DROP, (SCOPE,))
        with conn.cursor() as cur:
            cur.executemany(CACHE_ADD, [(SCOPE, e["kind"], e["src"], e["dst"], e["ts"], e["ask_ts"], e["ref"],
                                         e["topic"], cov[e["kind"]], now) for e in edges])
            cur.executemany(VALUE_ADD, [(SCOPE, "global", a, values[a], unmapped.get(a, 1.0), now)
                                        for a in sorted(values)])
    return graph.report(ledgers, values, unmapped) + [f"cached {len(edges)} edges, {len(values)} values at {now}"]


def proxy_liveness(conn, now, w_h=LIVE_W_H):
    """The shell's tracked liveness PROXY: an agent with a steps row within W. Its error both ways, stated: a WEDGED
    agent still writes no step yet reads live for up to W after its last one; a smaller W would drop healthy agents
    that wake once a day. It is not wedge_watch."""
    seen = last_steps(conn, now - timedelta(hours=w_h))
    return (f"proxy last-step<=W={w_h}h (not wedge_watch)", lambda a: a in seen)


def ask(conn, asker, topic=None, k=5, now=None, roster=None, liveness=None):
    """WHO SHOULD I ASK: the routing view over the edge cache at QUERY time, never the asker, liveness-filtered (the
    proxy unless one is injected), neighbours beside each. Appends (asker, returned, t, view) to the query log in the
    SAME call: the loop discount's one writer. Advisory. Liveness defaults to the shell's PROXY here (graph's own
    default is none); the reply's `liveness:` line names whichever ran."""
    now = now or datetime.now(timezone.utc)
    roster = sorted(roster if roster is not None else charter.roster())
    edges = read_cache(conn)
    cov = {}
    for e in edges:
        cov[e["kind"]] = e["coverage"]
    live = liveness or proxy_liveness(conn, now)
    out = graph.who_should_i_ask(asker, edges, cov, roster, now, k, live, topic)
    conn.execute(QLOG_ADD, (asker, out["returned"], out["view"], live[0]))
    return out


def backtest(conn, days=DAYS, repo=REPO, ref="main", now=None, roster=None, history_days=DAYS):
    """For each answered delegation and each landed review in the last `days`: the routing view from edges strictly
    BEFORE the ask (teleport on the asker) ranks the agent who delivered; baselines uniform and GLOBAL."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    ledgers, in_window, calls, roster = derive(conn, since - timedelta(days=history_days), now, repo, ref, roster)
    cov = {k: graph.coverage_of(lg) for k, lg in ledgers.items()}
    w = graph.kind_weights(cov)
    edges = [e for lg in ledgers.values() for e in lg["edges"]]
    nodes = sorted(roster)
    res, by_kind = graph.backtest(edges, nodes, w, since)
    lines = [f"backtest: events in [{since:%Y-%m-%d %H:%M}, {now:%Y-%m-%d %H:%M}) UTC, history from "
             f"{since - timedelta(days=history_days):%Y-%m-%d}; candidates = {len(nodes)} roster names minus the asker",
             "kind weights (coverage-gated): " + ", ".join(f"{k} {w[k]:g} ({cov.get(k, 0):.0%})" for k in graph.LIVE_KINDS),
             f"events: {sum(by_kind.values())} ({', '.join(f'{k} {n}' for k, n in sorted(by_kind.items()))})"]
    for m in ("routing", "global", "uniform"):
        xs = res[m]
        lines.append(f"  {m:8s} median rank {statistics.median(xs) if xs else float('nan'):5.2f}   "
                     f"mean rank {statistics.mean(xs) if xs else float('nan'):5.2f}")
    if res["routing"]:
        wins = sum(a < b for a, b in zip(res["routing"], res["global"]))
        loss = sum(a > b for a, b in zip(res["routing"], res["global"]))
        better = statistics.mean(res["routing"]) < statistics.mean(res["global"])
        lines.append(f"routing vs global per event: better {wins}, worse {loss}, tied {len(res['routing']) - wins - loss}"
                     f"; routing {'BEATS' if better else 'does NOT beat'} global on mean rank")
    return lines


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("verb", choices=("report", "compute", "ask", "backtest"))
    p.add_argument("asker", nargs="?")
    p.add_argument("--days", type=int, default=DAYS)
    p.add_argument("--topic")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--dsn")
    p.add_argument("--repo", default=str(REPO))
    p.add_argument("--ref", default="main")
    p.add_argument("--agents", default=str(charter.AGENTS), help="the agents/ tree the roster is read from")
    a = p.parse_args(argv)
    roster = charter.roster(Path(a.agents))
    if a.verb == "report":
        now = datetime.now(timezone.utc)
        with connect(a.dsn) as conn:
            ledgers, in_window, calls, roster = derive(conn, now - timedelta(days=a.days), now, a.repo, a.ref, roster)
            values, unmapped, _, _ = globals_of(ledgers, in_window, calls, roster, now)
        print("\n".join(graph.report(ledgers, values, unmapped)))
        amb = ledgers["delegation"]["ambiguous"]
        print(f"delegation ambiguous domain (thread, recipient with >=2 askers): {len(amb)}")
        for (th, rc), askers in amb:
            print(f"    {th} -> {rc}: {', '.join(askers)}")
    elif a.verb == "compute":
        with connect(a.dsn, readonly=False) as conn:
            try:
                print("\n".join(compute(conn, a.days, a.repo, a.ref, roster=roster)))
            except Refused as e:
                print(f"compute REFUSED, nothing written: {e}", file=sys.stderr)
                return 2
    elif a.verb == "ask":
        if not a.asker:
            p.error("ask needs <asker>")
        with connect(a.dsn, readonly=False) as conn:
            print("\n".join(ask(conn, a.asker, a.topic, a.k, roster=roster)["lines"]))
    else:
        with connect(a.dsn) as conn:
            print("\n".join(backtest(conn, a.days, a.repo, a.ref, roster=roster)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
