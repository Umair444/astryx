#!/usr/bin/env python3
"""Oracle for src/astryx/influence/graph.py (plan-11324 S2: the influence graph and "who should I ask").

TWO PHASES, the DB-free one first and in full (test_schema_parity's rule: a run already red pays no fixture):
  DB-FREE. graph.py is loaded from INFLUENCE_SRC (mutation_probe's seam), never by a bare import. Its inputs are
  built here: a REAL git repo in a tempdir (real merges, read back through shell.git_history's one `git log` pass,
  GIT_* scrubbed) and in-memory message rows carrying EXACTLY the read tools' columns (BC-R). Arms:
    PPR known answers (star, chain, two components; the routing view's closed form), the dangling-mass rule;
    the SHA join (exact, suffix-only marker, shared suffix, stale+non-merge, stale+merge-of-main, stale+merge of a
    non-main branch, neither, symbolic base, non-sha head); BC-A (lander, alias, no prefix, no cited id); BC-D
    (asker, one-to-one both ways, verdict review, request without verdict, revise to the asker / a third agent,
    chat, pulse, owner-originated, self-task, the ambiguous domain); tool calls (core, self-use, demand, direction);
    direction and self-loops per live kind; BC-R (the column list derived from channel/server.mjs); the coverage
    gate and the hard UNMEASURED kinds; the loop discount; the tool (never the asker, liveness named and applied).
  DB, ONE arm (one fixture Batch, closed in finally): shell.compute()/ask() on a stamped fixture database, every
    shell SQL read EMPTY and populated (sqlguard grades a WHERE RESPONSIVE only when it took 0 and >=1 rows); the
    cache cites refs and no body; the query log is appended in the same call as the reply; the loop discount reads it.
Exit 0 pass · 1 fail · 77 no database on a committed-only tree (the estate rule).
"""
import contextlib
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
SUBJECT = Path(os.environ.get("INFLUENCE_SRC") or REPO / "src" / "astryx" / "influence" / "graph.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def load():
    spec = importlib.util.spec_from_file_location("influence_graph_under_test", SUBJECT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ROSTER = {"abstractor-1", "abstractor-2", "abstractor-3", "abstractor-4", "seed", "steward", "memory", "forge"}
A1, A2, A3, A4 = "abstractor-1", "abstractor-2", "abstractor-3", "abstractor-4"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)      # after every fixture row's ts (a git commit is "now": not used in PPR)
FAR = (datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc))


def row(i, frm, to, intent, body="", thread=None, ts=None, from_org="local", to_org="local"):
    return {"id": i, "ts": ts or T0 + timedelta(minutes=i), "from_agent": frm, "from_org": from_org, "to_agent": to,
            "to_org": to_org, "thread": thread, "intent": intent, "body": body}


# ── the git fixture ─────────────────────────────────────────────────────────────────────────────────────────────────
class Git:
    def __init__(self, d):
        self.d = d
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", HOME=d, GIT_AUTHOR_NAME="fx", GIT_AUTHOR_EMAIL="fx@fx",
                        GIT_COMMITTER_NAME="fx", GIT_COMMITTER_EMAIL="fx@fx")
        self("init", "-q", "-b", "main")
        self.n = 0

    def __call__(self, *a):
        return subprocess.run(["git", "-C", self.d, *a], capture_output=True, text=True, check=True,
                              env=self.env).stdout.strip()

    def commit(self, label):
        self.n += 1
        Path(self.d, f"f{self.n}.txt").write_text(label)
        self("add", "-A")
        self("commit", "-q", "-m", label)
        return self("rev-parse", "HEAD")

    def branch(self, name, start="main"):
        self("checkout", "-q", "-b", name, start)

    def land(self, branch, subject):
        self("checkout", "-q", "main")
        self("merge", "-q", "--no-ff", "-m", subject, branch)
        return self("rev-parse", "HEAD")


def build_repo(d):
    """Every scenario lands on main in order; returns {name: shas} and the expected main-merge count."""
    g = Git(d)
    s = {"c0": g.commit("c0")}
    g.branch("a4/feat-a"); s["A1"] = g.commit("A1"); s["mA"] = g.land("a4/feat-a", "Merge a4/feat-a (a2 PASS #101)")
    g.branch(f"{A1}/fix-x"); s["B1"] = g.commit("B1")
    g.branch(f"{A3}/fix-x", "main"); s["B3"] = g.commit("B3")
    s["mB1"] = g.land(f"{A1}/fix-x", f"Merge {A1}/fix-x (#102 #103)")
    s["mB3"] = g.land(f"{A3}/fix-x", f"Merge {A3}/fix-x (#102 #103)")
    g.branch(f"{A1}/stale-c"); s["C1"] = g.commit("C1"); s["C2"] = g.commit("C2")
    s["mC"] = g.land(f"{A1}/stale-c", f"Merge {A1}/stale-c (#104)")
    g.branch(f"{A1}/stale-d"); s["D1"] = g.commit("D1")
    g("checkout", "-q", "main"); s["Mx"] = g.commit("Mx on main")
    g("checkout", "-q", f"{A1}/stale-d"); g("merge", "-q", "--no-ff", "-m", "merge main into stale-d", "main")
    s["mD"] = g.land(f"{A1}/stale-d", f"Merge {A1}/stale-d (#105)")
    g.branch("x-side"); s["X1"] = g.commit("X1 unreviewed")
    g.branch(f"{A1}/stale-e", "main"); s["E1"] = g.commit("E1")
    g("merge", "-q", "--no-ff", "-m", "merge x-side into stale-e", "x-side")
    s["mE"] = g.land(f"{A1}/stale-e", f"Merge {A1}/stale-e (#106)")
    g.branch(f"{A1}/feat-f"); s["F1"] = g.commit("F1")
    s["mF"] = g.land(f"{A1}/feat-f", f"Merge {A1}/feat-f (#107)")
    g.branch(f"{A3}/sym-g"); s["G1"] = g.commit("G1")
    s["mG"] = g.land(f"{A3}/sym-g", f"Merge {A3}/sym-g (#108)")
    g.branch(f"{A1}/x-h"); s["H1"] = g.commit("H1")
    s["mH"] = g.land(f"{A1}/x-h", f"Merge {A1}/x-h (#109)")
    g.branch(f"{A1}/feat-i"); s["I1"] = g.commit("I1")
    s["mI"] = g.land(f"{A1}/feat-i", f"Merge {A1}/feat-i (#110)")
    g.branch(f"{A1}/feat-j"); s["J1"] = g.commit("J1")
    s["mJ"] = g.land(f"{A1}/feat-j", f"Merge {A1}/feat-j: no cited id")
    g.branch("plain-k"); s["K1"] = g.commit("K1")
    s["mK"] = g.land("plain-k", "Merge plain-k (#111)")
    g.branch(f"{A1}/self-l"); s["L1"] = g.commit("L1")
    s["mL"] = g.land(f"{A1}/self-l", f"Merge {A1}/self-l (#112)")
    return s, 13


def pass_rows(s):
    c0 = s["c0"][:9]
    mk = lambda i, frm, to, line: row(i, frm, to, "review", f"PASS\nmerge-ready: {line}\n", thread=f"rv-{i}")
    return {r["id"]: r for r in (
        row(100, A4, A2, "review", "review request: feat-a", thread="rv-101", ts=T0 + timedelta(hours=1)),
        {**mk(101, A2, A4, f"feat-a {c0}..{s['A1'][:7]}"), "ts": T0 + timedelta(hours=80)},  # suffix-only, abbreviated
        mk(102, "steward", A1, f"fix-x {c0}..{s['B1']}"),               # two branches share the suffix fix-x
        mk(103, "memory", A3, f"fix-x {c0}..{s['B3']}"),
        mk(104, "steward", A1, f"stale-c {c0}..{s['C1']}"),             # stale, a non-merge commit after it
        mk(105, "steward", A1, f"stale-d {c0}..{s['D1']}"),             # stale, only a merge of main after it
        mk(106, "steward", A1, f"stale-e {c0}..{s['E1']}"),             # stale, a merge of x-side after it
        mk(107, "steward", A1, f"feat-f {c0}..{s['A1']}"),              # head neither M^2 nor on its path
        mk(108, "memory", A3, f"sym-g main..{s['G1']}"),                # a SYMBOLIC base
        mk(109, "steward", A1, f"x-h {c0}..feature-tip"),               # a non-sha head
        mk(110, "steward", "seed", f"feat-i {c0}..{s['I1']}"),          # PASS addressed to the lander
        mk(111, "steward", A1, f"plain-k {c0}..{s['K1']}"),             # a branch with no owner prefix
        mk(112, A1, A1, f"self-l {c0}..{s['L1']}"),                     # a self-review
    )}


def db_free(G, shell, address, tmp):
    s, n_merges = build_repo(tmp)
    commits, tip = shell.git_history(tmp, "main")
    parents = {k: c["parents"] for k, c in commits.items()}
    merges = G.main_merges(commits, tip, *FAR)
    check("main's merges are its FIRST-PARENT merges only (a branch's own merges excluded)",
          len(merges) == n_merges, f"{len(merges)} != {n_merges}")
    rows = pass_rows(s)
    lg = G.pass_land_edges(merges, parents, rows, ROSTER, address.suggest)
    by_msg = {}
    for e in lg["edges"]:
        by_msg.setdefault(e["authority"][0], []).append(e)
    sha_of = {e["ref"].split()[0][4:]: e for e in lg["edges"]}
    print("    pass_land:", len(lg["edges"]), "edges;", dict(lg["unmeasured"]))
    e101 = by_msg.get(101, [{}])[0]
    check("SHA join: a marker naming only the suffix, with the right (abbreviated) head, is an edge",
          e101.get("src") == A4 and e101.get("dst") == A2, str(e101))
    check("BC-A: the alias a4 resolves to abstractor-4 through address.suggest()",
          G.resolve_owner("a4", ROSTER, address.suggest) == (A4, "alias") and e101.get("src") == A4)
    check("SHA join: two merged branches sharing a suffix each resolve by sha to their own PASS",
          [e["authority"][0] for e in lg["edges"] if e["ref"].startswith(f"sha:{s['mB1']}")] == [102]
          and [e["authority"][0] for e in lg["edges"] if e["ref"].startswith(f"sha:{s['mB3']}")] == [103])
    ok, how = G.head_joins(s["C1"], s["mC"], parents)
    check("SHA join: a stale head with a NON-merge commit after it does not join", not ok and 104 not in by_msg, how)
    ok, how = G.head_joins(s["D1"], s["mD"], parents)
    check("SHA join: a stale head followed only by a merge of main joins", ok and 105 in by_msg, how)
    ok, how = G.head_joins(s["E1"], s["mE"], parents)
    check("SHA join: a stale head followed by a merge of a NON-main branch does not join",
          not ok and "non-main" in how and 106 not in by_msg, how)
    ok, how = G.head_joins(s["A1"], s["mF"], parents)
    check("SHA join: a head that is neither M^2 nor on its first-parent path does not join",
          not ok and 107 not in by_msg and "neither" in how, how)
    e108 = by_msg.get(108, [{}])[0]
    check("symbolic base: the head alone joins, the base is reported 'unresolved base: main' and never resolved "
          "against today's main", e108.get("src") == A3 and "unresolved base: main" in e108.get("ref", "")
          and tip not in e108.get("ref", ""), str(e108))
    check("a non-sha head is UNMEASURED 'non-sha head'", G.parse_ready("merge-ready: x-h abc1234..feature-tip")
          == [{"error": "non-sha head"}] and lg["unmeasured"].get("non-sha head") == 1, str(dict(lg["unmeasured"])))
    check("BC-A: a PASS addressed to the lander for someone else's branch is no edge, counted UNMEASURED",
          110 not in by_msg and lg["unmeasured"].get("BC-A: author (to_agent) is not the branch's owner prefix") == 1,
          str(dict(lg["unmeasured"])))
    check("BC-A: a branch with no owner prefix is no edge, counted", lg["unmeasured"].get("BC-A: no owner prefix") == 1)
    check("a merge with no cited id is UNMEASURED 'no cited id'", lg["unmeasured"].get("no cited id") == 1)
    check("pass_land: a self-review is no edge (self-loop excluded)", 112 not in by_msg
          and lg["unmeasured"].get("self-loop") == 1, str(dict(lg["unmeasured"])))
    check("pass_land coverage = merges with an edge / merges (5 of 13)", lg["measured"] == 5 and lg["domain"] == 13,
          f"{lg['measured']}/{lg['domain']}")
    check("pass_land direction: author → reviewer on every edge",
          all(e["src"] == rows[e["authority"][0]]["to_agent"] and e["dst"] == rows[e["authority"][0]]["from_agent"]
              for e in lg["edges"]) and lg["edges"])
    one = [e for e in lg["edges"] if e["authority"][0] == 101]
    sc = G.scores(one, G.global_view({"pass_land": 1.0}, [A2, A4]), [A2, A4], one[0]["ts"] + timedelta(days=1))
    check("pass_land direction drives the ranking: the reviewer outranks the author", sc[A2] > sc[A4], str(sc))
    check("the edge's ts is the merge commit's committer time", e101.get("ts") == commits[s["mA"]]["ts"])
    check("ask anchor: a PASS's ask_ts is its review cycle's first request, not the answer",
          e101.get("ask_ts") == T0 + timedelta(hours=1), str(e101.get("ask_ts")))
    check("ask anchor: every PASS with no request before it falls back to its own ts, and is counted (4 of 5)",
          lg["ask_fallback"] == 4 and all(e["ask_ts"] == rows[e["authority"][0]]["ts"] for e in lg["edges"]
                                          if e["authority"][0] != 101), str(lg["ask_fallback"]))
    kept, routed = G.loop_discount([e101], [{"asker": A4, "returned": [A2], "ts": T0}], 72 * 3600)
    check("ask anchor (a): query t0, request t0+1h, PASS t0+80h → discounted under W=72h", routed == 1, str(routed))
    rep = "\n".join(G.report({"pass_land": lg}, {}, {}))
    check("ask anchor: the report prints the fallback count",
          "pass_land ask time = answer time (fallback): 4 edges" in rep, rep)
    bad = dict(rows)
    bad[101] = {**rows[101], "delivery": {}}
    try:
        G.pass_land_edges(merges, parents, bad, ROSTER, address.suggest)
        check("BC-R: a PASS row carrying a column the read tools don't return is refused", False)
    except ValueError:
        check("BC-R: a PASS row carrying a column the read tools don't return is refused", True)
    return sha_of


def anchors(G):
    t = lambda h: T0 + timedelta(hours=h)
    b = [row(1, A1, A2, "task", thread="rb", ts=t(1)), row(2, A2, A1, "review", "PASS", thread="rb", ts=t(2)),
         row(3, A1, A2, "review", "review request: round 2", thread="rb", ts=t(3)),
         row(4, A2, A1, "review", "PASS", thread="rb", ts=t(4))]
    check("ask anchor (b): a reused thread anchors on the NEW request after the previous PASS",
          G.review_anchor(b[3], b) == (t(3), False), str(G.review_anchor(b[3], b)))
    c = [row(1, A1, A2, "task", thread="rc", ts=t(1)), row(2, A2, A1, "review", "REVISE: two fixes", thread="rc",
                                                           ts=t(2)),
         row(3, A1, A2, "review", "re-request", thread="rc", ts=t(3)), row(4, A2, A1, "review", "PASS", thread="rc",
                                                                         ts=t(4))]
    check("ask anchor (c): request, REVISE, re-request, PASS anchors on the FIRST request (REVISE is no boundary)",
          G.review_anchor(c[3], c) == (t(1), False), str(G.review_anchor(c[3], c)))
    d = [row(1, A2, A1, "chat", "starting", thread="rd", ts=t(1)), row(2, A2, A1, "review", "PASS", thread="rd",
                                                                      ts=t(2))]
    check("ask anchor (d): no author → reviewer message before the PASS → the PASS's ts, flagged a fallback",
          G.review_anchor(d[1], d) == (t(2), True), str(G.review_anchor(d[1], d)))
    e = [row(1, A1, A2, "task", thread="re", ts=t(1)),
         row(2, A2, A1, "review", "re-review after your REVISE: PASS\nmerge-ready: a1/x 1234567..89abcde", thread="re",
             ts=t(2)),
         row(3, A1, A2, "review", "review request: round 2", thread="re", ts=t(3)),
         row(4, A2, A1, "review", "PASS", thread="re", ts=t(4))]
    check("ask anchor (e): a merge-ready marker row closes the cycle even when it also says REVISE (a3 #58419)",
          G.review_anchor(e[3], e) == (t(3), False), str(G.review_anchor(e[3], e)))
    f = [e[0], {**e[1], "body": "REVISE: two fixes, then\nmerge-ready: <branch> <base>..<head>"}, e[2], e[3]]
    check("ask anchor (e'): a TEMPLATE marker in a REVISE does not close the cycle",
          G.review_anchor(f[3], f) == (t(1), False), str(G.review_anchor(f[3], f)))


def delegation(G):
    rows = [
        row(201, A1, A2, "task", thread="t1"), row(202, A3, A2, "task", thread="t1"),
        row(203, A2, A1, "receipt", thread="t1"),
        row(211, A1, A2, "task", thread="t2"), row(212, A1, A2, "task", thread="t2"),
        row(213, A2, A1, "result", thread="t2"),
        row(221, A1, A3, "task", thread="t2b"), row(222, A3, A1, "receipt", thread="t2b"),
        row(223, A3, A1, "receipt", thread="t2b"),
        row(231, A1, A4, "task", thread="t3"), row(232, A4, A1, "review", "Verdict: PASS, ship it", thread="t3"),
        row(241, A3, A4, "task", thread="t4"), row(242, A4, A3, "review", "review request: please look", thread="t4"),
        row(251, A4, A3, "task", thread="t5"), row(252, A3, A4, "revise", "two fixes", thread="t5"),
        row(261, A4, A1, "task", thread="t6"), row(262, A1, "memory", "revise", "two fixes", thread="t6"),
        row(271, "memory", A1, "task", thread="t7"), row(272, A1, "memory", "chat", "ok", thread="t7"),
        row(281, A2, A3, "task", "[trigger nudge] look at this", thread="t8"),
        row(282, A3, A2, "receipt", thread="t8"),
        row(291, "owner", A3, "task", thread="t9"), row(292, A3, "owner", "receipt", thread="t9"),
        row(301, A4, A4, "task", thread="t10"), row(302, A4, A4, "receipt", thread="t10"),
    ]
    lg = G.delegation_edges(rows, ROSTER)
    got = {e["task_id"]: (e["src"], e["dst"], e["authority"][1]) for e in lg["edges"]}
    print("    delegation:", len(lg["edges"]), "edges;", dict(lg["unmeasured"]))
    check("BC-D (i): two askers on one thread, a receipt to A credits A only",
          got.get(201) == (A1, A2, 203) and 202 not in got, str(got))
    check("BC-D (ii): two tasks and one outcome → exactly one edge, the nearest task",
          [t for t in got if t in (211, 212)] == [212], str(got))
    check("BC-D (ii): one task and two outcomes → one edge (a task is answered once)",
          [t for t in got if t == 221] == [221] and sum(1 for e in lg["edges"] if e["task_id"] == 221) == 1)
    check("BC-D: a review carrying a PASS verdict is an outcome", got.get(231) == (A1, A4, 232))
    check("BC-D: a review request without a verdict is no outcome", 241 not in got)
    check("BC-D: a revise to the asker is an outcome", got.get(251) == (A4, A3, 252))
    check("BC-D: a revise to a third agent is no outcome, counted UNMEASURED (i)", 261 not in got
          and lg["unmeasured"].get("(i) outcome to_agent is not the open task's asker") == 1,
          str(dict(lg["unmeasured"])))
    check("BC-D: a chat reply is no outcome", 271 not in got)
    check("BC-D: a pulse-originated task is never an edge", 281 not in got and lg["unmeasured"].get("pulse task") == 1)
    check("nodes rider: an owner-originated task with an outcome is no edge, counted UNMEASURED",
          291 not in got and lg["unmeasured"].get("end outside the agents/ tree") == 1)
    check("delegation: a self-task is no edge (self-loop excluded)", 301 not in got
          and lg["unmeasured"].get("self-loop") == 1)
    check("delegation direction: asker → recipient, ts = the outcome's ts, ask_ts = the task's",
          all(e["src"] == next(r for r in rows if r["id"] == e["task_id"])["from_agent"] for e in lg["edges"])
          and next(e for e in lg["edges"] if e["task_id"] == 201)["ts"] == rows[2]["ts"]
          and next(e for e in lg["edges"] if e["task_id"] == 201)["ask_ts"] == rows[0]["ts"])
    one = [e for e in lg["edges"] if e["task_id"] == 251]
    sc = G.scores(one, G.global_view({"delegation": 1.0}, [A3, A4]), [A3, A4], NOW)
    check("delegation direction drives the ranking: the recipient outranks the asker", sc[A3] > sc[A4], str(sc))
    check("BC-D (iii): the ambiguous domain lists (t1, abstractor-2) with both askers",
          (("t1", A2), [A1, A3]) in lg["ambiguous"], str(lg["ambiguous"]))
    check("R-1: a task answered ONLY outside the outcome grammar (a chat to the asker) is UNMEASURED, not a measured "
          "zero", 271 not in got and lg["unmeasured"].get("answered outside the outcome grammar") == 2,
          str(dict(lg["unmeasured"])))
    check("R-1: a task whose only reply is an outcome given to a nearer task is UNMEASURED, its own reason",
          211 not in got and lg["unmeasured"].get("answered by an outcome the one-to-one rule gave a nearer task") == 1,
          str(dict(lg["unmeasured"])))
    check("R-1: a task with no reply at all is measured (a judged silence), counted in the 7 of 13",
          202 not in got and lg["domain"] == 13 and lg["measured"] == 7, f"{lg['measured']}/{lg['domain']}")
    check("R-1: the yield is edges / tasks (5 of 13)", abs(lg["yield"] - 5 / 13) < 1e-12, str(lg.get("yield")))
    try:
        G.delegation_edges([{**rows[0], "delivery": {}}], ROSTER)
        check("BC-R: a task row carrying a column the read tools don't return is refused", False)
    except ValueError:
        check("BC-R: a task row carrying a column the read tools don't return is refused", True)
    return lg


def tools(G):
    from astryx.core import toolreg
    calls = [{"rid": "script:devtools/x.py", "caller": A1, "author": "forge", "dq": True, "ts": T0},
             {"rid": "mcp:astryx/send", "caller": A1, "author": "forge", "dq": True, "ts": T0},
             {"rid": "mcp:tools/run", "caller": A2, "author": "forge", "dq": True, "ts": T0},
             {"rid": "script:devtools/y.py", "caller": "forge", "author": "forge", "dq": True, "ts": T0},
             {"rid": "script:devtools/z.py", "caller": A3, "author": "forge", "dq": False, "ts": T0},
             {"rid": "script:devtools/w.py", "caller": A3, "author": "unknown", "dq": True, "ts": T0}]
    lg = G.tool_edges(calls, ROSTER, 0.8)
    pairs = [(e["src"], e["dst"], e["ref"]) for e in lg["edges"]]
    check("tool calls: core servers come from toolreg.CORE_SERVERS (the same object, never re-typed)",
          G.CORE_SERVERS is toolreg.CORE_SERVERS)
    check("tool calls: a core server's call is outside the domain and no edge", lg["domain"] == 4
          and not any("mcp:astryx" in p[2] or "mcp:tools" in p[2] for p in pairs), str(pairs))
    check("tool calls: self-use is no edge", not any(p[0] == p[1] for p in pairs))
    check("tool calls: one edge, caller → author, demand-qualified only",
          pairs == [(A1, "forge", "tool:script:devtools/x.py")], str(pairs))
    check("tool calls: an unresolved author is UNMEASURED", lg["unmeasured"].get("author unresolved") == 1)
    sc = G.scores(lg["edges"], G.global_view({"tool_call": 1.0}, [A1, "forge"]), [A1, "forge"], NOW)
    check("tool direction drives the ranking: the author outranks the caller", sc["forge"] > sc[A1], str(sc))


def pagerank(G):
    def e(s, d, k="delegation"):
        return {"kind": k, "src": s, "dst": d, "ts": T0, "ask_ts": T0, "ref": "", "topic": None, "authority": []}
    w = {k: 1.0 for k in G.KINDS}
    star = [e(f"s{i}", "hub") for i in range(1, 6)]
    nodes = ["hub"] + [f"s{i}" for i in range(1, 6)]
    now = T0 + timedelta(days=1)
    r = G.scores(star, G.global_view(w, nodes), nodes, now)
    check("PPR star (global): the hub ranks first, the spokes tie, mass sums to 1",
          max(r, key=r.get) == "hub" and max(r[f's{i}'] for i in range(1, 6)) - min(r[f's{i}'] for i in range(1, 6))
          < 1e-12 and abs(sum(r.values()) - 1) < 1e-9, str(r))
    chain = [e("a", "b"), e("b", "c"), e("c", "d")]
    r = G.scores(chain, G.global_view(w, "abcd"), list("abcd"), now)
    check("PPR chain a→b→c→d (global): strictly monotone d > c > b > a", r["d"] > r["c"] > r["b"] > r["a"], str(r))
    two = [e("x1", "x2"), e("x2", "x1"), e("y1", "y2"), e("y3", "y2")]
    nn = ["x1", "x2", "y1", "y2", "y3"]
    r = G.scores(two, G.global_view(w, nn), nn, now)
    check("PPR two components (global): every node carries non-zero mass", all(r[n] > 0 for n in nn), str(r))
    rt = G.scores(star, G.routing_view(w, "s1"), nodes, now)
    d = G.DAMPING
    check("PPR routing (teleport on spoke s1, dangling→teleport): the closed form s1 = 1/(1+d), hub = d/(1+d), "
          "every other spoke 0", abs(rt["s1"] - 1 / (1 + d)) < 1e-9 and abs(rt["hub"] - d / (1 + d)) < 1e-9
          and all(rt[f"s{i}"] < 1e-12 for i in range(2, 6)), str(rt))
    vu = {**G.routing_view(w, "s1"), "dangling": "uniform"}
    ru = G.scores(star, vu, nodes, now)
    check("PPR: the dangling rule flipped to 'uniform' changes the ranking (unreached spokes gain mass)",
          all(ru[f"s{i}"] > 1e-6 for i in range(2, 6)) and G.top_k(ru, "nobody", 6, lambda a: True, [])
          != G.top_k(rt, "nobody", 6, lambda a: True, []), str(ru))
    check("PPR: an edge at or after `now` is not used (strictly before)",
          G.weighted([e("a", "b")], G.global_view(w, "ab"), T0) == [])
    hl = G.weighted([{**e("a", "b"), "ts": now - timedelta(days=14)}], G.global_view(w, "ab"), now)
    check("PPR: the half-life halves a 14-day-old edge", abs(hl[0][2] - 0.5) < 1e-12, str(hl))
    for kind in G.LIVE_KINDS:
        sl = G.weighted([e("a", "a", kind)], G.global_view(w, "a"), now)
        check(f"PPR: a {kind} self-loop never weighs", sl == [], str(sl))


def gates(G):
    from collections import Counter
    lg = {"pass_land": {"domain": 10, "measured": 4, "unmeasured": Counter({"x": 6}), "edges": []},
          "delegation": {"domain": 10, "measured": 5, "unmeasured": Counter(), "edges": []},
          "tool_call": {"domain": 10, "measured": 9, "unmeasured": Counter(), "edges": [], "coverage": 0.49}}
    cov = {k: G.coverage_of(v) for k, v in lg.items()}
    w = G.kind_weights(cov)
    check("coverage gate: a kind under 50% weighs 0 (40% and econ's 49%); exactly 50% weighs 1",
          w["pass_land"] == 0 and w["tool_call"] == 0 and w["delegation"] == 1.0, str(w))
    check("merge_landed and goal_shipped weigh 0 whatever their coverage",
          G.kind_weights({"merge_landed": 1.0, "goal_shipped": 1.0})["merge_landed"] == 0
          and G.kind_weights({"merge_landed": 1.0, "goal_shipped": 1.0})["goal_shipped"] == 0)
    rep = "\n".join(G.report(lg, {A1: 0.6, A2: 0.4}, {A1: 0.9, A2: 0.2}))
    check("report: a kind under 50% prints UNMEASURED", re.search(r"pass_land: .*UNMEASURED \(coverage under 50%", rep)
          is not None, rep)
    check("report: merge_landed prints UNMEASURED with its reason",
          "merge_landed: UNMEASURED (no recorded merger: a rule, not a fact)" in rep, rep)
    check("report: goal_shipped prints UNMEASURED with its reason",
          "goal_shipped: UNMEASURED (goals has no filer column)" in rep, rep)
    check("report: a mostly-unmapped agent reads 'unmeasured' (never a low rank), a mapped one 'measured'",
          re.search(rf"{A1}\s+0\.6000\s+unmapped 90%\s+unmeasured", rep) is not None
          and re.search(rf"{A2}\s+0\.4000\s+unmapped 20%\s+measured", rep) is not None, rep)
    rows = [row(1, A1, A2, "task", thread="q"), row(2, A2, A1, "receipt", thread="q"),
            row(3, A1, A2, "chat", thread="q"), row(4, A1, A2, "chat", thread="q"), row(5, A1, A2, "chat", thread="q")]
    dl = G.delegation_edges(rows, ROSTER)
    un, active = G.agent_coverage(rows, [], {"delegation": dl}, {"delegation": 1.0}, ROSTER)
    check("agent coverage: the share of an agent's messages that are no weighted edge's authority",
          abs(un[A1] - 0.75) < 1e-12 and un[A2] == 0.0 and active == [A1, A2], str(un))
    un0, _ = G.agent_coverage(rows, [], {"delegation": dl}, {"delegation": 0.0}, ROSTER)
    check("agent coverage: an edge in a weight-0 kind maps nothing", un0[A1] == 1.0 and un0[A2] == 1.0, str(un0))


def bcr(G, shell):
    src = (REPO / "channel" / "server.mjs").read_text()
    m = re.search(r"SELECT (id, ts, from_agent[^`]*?)FROM messages WHERE id=\$1", src, re.S)
    cols = [c.strip() for c in m.group(1).split(",")] if m else []
    cols = [c for c in cols if c and " AS " not in c and not c.startswith("$")]
    check("BC-R: graph.MSG_COLS is exactly read_message's column list (channel/server.mjs)",
          m is not None and tuple(cols) == G.MSG_COLS, f"{cols} vs {G.MSG_COLS}")
    # PREMISE PIN (steward #58414, a3 #58419): BC-R's "S2 reads what any reader reads" holds BY CONSTRUCTION only while
    # the read tools have no reader-dependent predicate. The day one appears, this trips, not the column parity above.
    def wheres(tool):
        blk = re.search(rf"if \(name === '{tool}'\)(.*?)(?=\n  if \(name ===)", src, re.S)
        return re.findall(r"WHERE ([^`)]*?)(?=\s+ORDER\b|`|\))", blk.group(1)) if blk else None
    check("BC-R premise: read_message's SQL filters on exactly `WHERE id=$1` (no reader-dependent predicate)",
          wheres("read_message") == ["id=$1"], str(wheres("read_message")))
    check("BC-R premise: query_thread's SQL filters on exactly `WHERE thread=$1` (no reader-dependent predicate)",
          wheres("query_thread") == ["thread=$1"], str(wheres("query_thread")))
    sel = re.match(r"SELECT (.*?) FROM messages", shell.MSG_SQL)
    check("BC-R: the shell's messages SELECT reads exactly graph.MSG_COLS",
          sel is not None and tuple(c.strip() for c in sel.group(1).split(",")) == G.MSG_COLS)


def loop_and_tool(G):
    q = {"asker": A1, "returned": [A2, A3], "ts": T0}

    def de(src, dst, at):
        return {"kind": "delegation", "src": src, "dst": dst, "ts": at + timedelta(hours=1), "ask_ts": at, "ref": "",
                "topic": None, "authority": []}
    edges = [de(A1, A2, T0 + timedelta(hours=1)), de(A1, A2, T0 + timedelta(hours=100)),
             de(A4, A2, T0 + timedelta(hours=1)), de(A1, A4, T0 + timedelta(hours=1))]
    kept, routed = G.loop_discount(edges, [q], 72 * 3600)
    check("loop discount: a later tokenless task from the asker to a returned agent within W is routed (dropped)",
          routed == 1 and edges[0] not in kept, f"routed={routed}")
    check("loop discount: after W, from another asker, or to an unreturned agent → kept", len(kept) == 3)
    pl = {**de(A1, A3, T0 + timedelta(hours=2)), "kind": "pass_land"}
    kept, routed = G.loop_discount([pl], [q], 72 * 3600)
    check("R-2 loop discount: the author asks, the tool returns X, a PASS by X lands within W → discounted",
          routed == 1 and kept == [], f"routed={routed}")
    check("compute guard: a roster of < 2 names is refused, named",
          "roster has 1 name(s)" in (G.refuse_compute(["seed"], False, []) or "")
          and G.refuse_compute(["seed", A1], False, []) is None)
    check("compute guard: an empty edge set over a non-empty cache is refused, named; over an empty cache it is not",
          "non-empty edge cache" in (G.refuse_compute(sorted(ROSTER), True, []) or "")
          and G.refuse_compute(sorted(ROSTER), False, []) is None
          and G.refuse_compute(sorted(ROSTER), True, [{"kind": "delegation"}]) is None)
    e = lambda s, d: {"kind": "delegation", "src": s, "dst": d, "ts": T0, "ask_ts": T0, "ref": "", "topic": "plan-9",
                      "authority": []}
    g = [e(A1, A2), e(A1, A3), e(A2, A1), e(A3, A4)]
    cov = {"delegation": 1.0}
    nodes = sorted(ROSTER)
    out = G.who_should_i_ask(A1, g, cov, nodes, T0 + timedelta(days=1), k=5)
    check("the tool never returns the asker (who ranks first under its own teleport)", A1 not in out["returned"]
          and out["returned"], str(out["returned"]))
    check("the tool's default liveness is none, and it says so", "liveness: none" in out["lines"])
    out2 = G.who_should_i_ask(A1, g, cov, nodes, T0 + timedelta(days=1), k=5,
                              liveness=("probe-x", lambda a: a != A2))
    check("the tool applies the injected liveness filter and names it",
          A2 in out["returned"] and A2 not in out2["returned"] and "liveness: probe-x" in out2["lines"],
          f"{out['returned']} / {out2['returned']}")
    check("the tool lists neighbours beside each returned agent",
          any(f"{A2} " in ln and "neighbours: " in ln and A1 in ln.split("neighbours:")[1] for ln in out["lines"]),
          "\n".join(out["lines"]))
    check("the tool prints every weight-0 kind as UNMEASURED, the hard ones with their reasons",
          "  merge_landed: UNMEASURED (weight 0: no recorded merger: a rule, not a fact)" in out["lines"]
          and "  goal_shipped: UNMEASURED (weight 0: goals has no filer column)" in out["lines"]
          and "  pass_land: UNMEASURED (weight 0: no edge of this kind in the cache)" in out["lines"]
          and not any(ln.startswith("  delegation: UNMEASURED") for ln in out["lines"]), "\n".join(out["lines"]))
    low = G.who_should_i_ask(A1, g, {"delegation": 0.4}, nodes, T0 + timedelta(days=1), k=5)
    check("the tool under a sub-50% delegation coverage returns nobody and says why",
          low["returned"] == [] and "  delegation: UNMEASURED (weight 0: coverage 40% under 50%)" in low["lines"],
          "\n".join(low["lines"]))


def db_arm(tmp_repo):
    """ONE arm on a fixture: compute → cache, ask → reply + query log in the same call, the loop discount reads the
    log; every shell read runs EMPTY first and populated after."""
    from astryx.security.sqlguard import estate
    rc = estate.gate("test_influence", REPO, deps=("psycopg",), env=True)
    if rc is not None:
        return rc
    import psycopg
    from astryx.influence import shell
    from astryx.security.sqlguard.fixture import Batch, FixtureUnavailable
    while float(Path("/proc/loadavg").read_text().split()[1]) >= 6:     # the owner's load gate
        print("  (5-min load >= 6: waiting 30 s)")
        time.sleep(30)
    batch, stack = Batch(), contextlib.ExitStack()
    sentinel = "BODY-SENTINEL-7f3a"
    try:
        try:
            fx = stack.enter_context(batch.fixture())
        except FixtureUnavailable as e:
            return estate.unavailable("test_influence", REPO, e, fails)
        c = stack.enter_context(psycopg.connect(fx["dsn"], autocommit=True, connect_timeout=5))
        R = sorted(ROSTER)
        now = c.execute("SELECT now()").fetchone()[0]
        lines = shell.compute(c, 14, tmp_repo, "main", now=now, roster=R)
        n0 = c.execute("SELECT count(*) FROM influence_edge").fetchone()[0]
        out0 = shell.ask(c, A1, now=now, roster=R)
        q0 = c.execute("SELECT count(*) FROM influence_query").fetchone()[0]
        check("DB: on an EMPTY database compute caches no edge and ask returns nobody, logging the query",
              n0 == 0 and out0["returned"] == [] and q0 == 1, f"edges={n0} returned={out0['returned']} q={q0}")
        t = c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body, ts) VALUES "
                      "(%s, %s, 'fx-th', 'task', %s, now() - interval '2 hours') RETURNING id",
                      (A1, A2, sentinel)).fetchone()[0]
        o = c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body, ts) VALUES "
                      "(%s, %s, 'fx-th', 'receipt', %s, now() - interval '1 hour') RETURNING id",
                      (A2, A1, sentinel)).fetchone()[0]
        c.execute("INSERT INTO steps (agent, kind, content) VALUES (%s, 'tool', 'fx')", (A2,))
        now = c.execute("SELECT now()").fetchone()[0]
        shell.compute(c, 14, tmp_repo, "main", now=now, roster=R)
        now = c.execute("SELECT now()").fetchone()[0]
        lines = shell.compute(c, 14, tmp_repo, "main", now=now, roster=R)       # DELETE now meets a row
        cache = shell.read_cache(c)
        check("DB: compute caches the delegation edge with its authority refs, replaced (not duplicated) per compute",
              [(e["kind"], e["src"], e["dst"], e["ref"]) for e in cache]
              == [("delegation", A1, A2, f"msg:{t}>{o} (receipt)")], str(cache))
        dump = " ".join(str(v) for r in c.execute("SELECT * FROM influence_edge").fetchall() for v in r)
        dump += " ".join(str(v) for r in c.execute("SELECT * FROM influence_value").fetchall() for v in r)
        check("DB: no body text reaches the cache or the values", sentinel not in dump)
        nv = c.execute("SELECT count(DISTINCT agent) FROM influence_value WHERE view = 'global'").fetchone()[0]
        check("DB: the GLOBAL view's values are stored per agent", nv == len(R), str(nv))
        check("DB: compute's report names the coverage of each kind",
              any(ln.startswith("  delegation: coverage 100.0% of 1") for ln in lines), "\n".join(lines))
        snap = lambda: (c.execute("SELECT count(*) FROM influence_edge").fetchone()[0],
                        c.execute("SELECT count(*) FROM influence_value").fetchone()[0])
        before = snap()
        refused = []
        for kw in ({"roster": ["seed"], "now": now}, {"roster": R, "now": now - timedelta(days=400)}):
            try:
                shell.compute(c, 14, tmp_repo, "main", **kw)
            except shell.Refused as e:
                refused.append(str(e))
        check("DB: compute REFUSES a 1-name roster and an empty edge set over a non-empty cache, writing nothing",
              len(refused) == 2 and snap() == before, f"{refused} {before} -> {snap()}")
        out = shell.ask(c, A1, now=now, roster=R)
        log = c.execute("SELECT asker, returned, view, liveness FROM influence_query ORDER BY id DESC LIMIT 1"
                        ).fetchone()
        check("DB: ask returns the recipient, prints the proxy liveness exactly, and logs (asker, returned, view) in "
              "the same call", out["returned"] == [A2] and "liveness: proxy last-step<=W=36h (not wedge_watch)"
              in out["lines"] and log == (A1, [A2], "routing", "proxy last-step<=W=36h (not wedge_watch)"),
              f"{out['returned']} {log}")
        out_dead = shell.ask(c, A2, now=now, roster=R)
        check("DB: the proxy drops an agent with no step within W (abstractor-1 wrote none)",
              A1 not in out_dead["returned"], str(out_dead["returned"]))
        t2 = c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                       "(%s, %s, 'fx-th2', 'task', %s) RETURNING id", (A1, A2, sentinel)).fetchone()[0]
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "(%s, %s, 'fx-th2', 'receipt', %s)", (A2, A1, sentinel))
        later = c.execute("SELECT now() + interval '1 minute'").fetchone()[0]
        lines = shell.compute(c, 14, tmp_repo, "main", now=later, roster=R)
        refs = [e["ref"] for e in shell.read_cache(c)]
        check("DB: a task the tool routed (asker → a returned agent, within W) is discounted from delegation",
              not any(f"msg:{t2}>" in r for r in refs) and any("routed by the tool (loop discount)" in ln
                                                                  for ln in lines), f"{refs}")
        return 1 if fails else 0
    finally:
        stack.close()
        batch.close()


def main():
    t0 = time.monotonic()
    try:
        G = load()
    except Exception as e:  # noqa: BLE001  the subject is unloadable: every arm would fail for that
        print(f"  FAIL  the subject loads ({type(e).__name__}: {e})")
        return 1
    from astryx.core import address
    from astryx.influence import shell
    with tempfile.TemporaryDirectory() as tmp:
        print("DB-FREE")
        for arm in (lambda: db_free(G, shell, address, tmp), lambda: anchors(G), lambda: delegation(G), lambda: tools(G),
                    lambda: pagerank(G), lambda: gates(G), lambda: bcr(G, shell), lambda: loop_and_tool(G)):
            try:
                arm()
            except Exception as e:  # noqa: BLE001  a crashing arm is red, and the rest still report
                check(f"an arm raised {type(e).__name__}: {e}", False)
        lift = REPO / "triggers" / "seed" / "merge_ready.py"
        if lift.exists():
            mine = (REPO / "src" / "astryx" / "core" / "verdicts.py").read_text()
            theirs = lift.read_text()
            names = ("HEX", "REF", "READY_RE", "RANGE_RE", "PROSE_PASS_RE", "REVISE_RE")
            line = lambda txt, n: next((ln for ln in txt.splitlines() if ln.startswith(f"{n} = ")), None)
            # Two legal states: before seed's import, a byte-identical copy; after it, merge_ready.py imports all seven
            # names from verdicts.py and defines none of them (the zero-definitions grep).
            seven = set(names) | {"MARKER_RE"}
            imp = re.search(r"^from astryx\.core\.verdicts import (.+?)(?:\s+#.*)?$", theirs, re.M)
            imported = imp is not None and seven <= {n.strip() for n in imp.group(1).split(",")}
            defined = re.findall(rf"^({'|'.join(sorted(seven))}) *=", theirs, re.M)
            check("verdicts.py: triggers/seed/merge_ready.py imports the lifted group (defining none) or copies it byte-"
                  "identically", (imported and not defined) or all(line(mine, n) == line(theirs, n) is not None
                                                                   for n in names),
                  f"imported={imported} defined={defined}")
        else:
            print("  (verdicts lift parity: triggers/seed/merge_ready.py absent on this tree, not compared)")
        print(f"  DB-free phase: {time.monotonic() - t0:.1f}s")
        if fails:
            print("DB phase not run: the DB-free phase is red")
            return 1
        print("DB")
        t1 = time.monotonic()
        rc = db_arm(tmp)
        print(f"  DB phase: {time.monotonic() - t1:.1f}s")
        return rc


if __name__ == "__main__":
    rc = main()
    print()
    if fails:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
        rc = 1
    elif rc == 0:
        print("ALL PASS")
    sys.exit(rc)
