#!/usr/bin/env python3
"""astryx · influence graph — EVERY rule of plan-11324 S2, pure (no SQL, no git, no clock, no environment).

The graph: typed, timestamped, DIRECTED edges. A→B means A's work relied on B, so credit flows to B. Each kind is
derived at COMPUTE time from its ONE authority, never from a hand-kept edge table. Self-loops are excluded from
every kind. An edge's ts is its authority event's time (the merge commit's committer time for pass_land, the
outcome's ts for delegation): the backtest depends on it.

  pass_land     author → reviewer   main's first-parent merges in the window; every `#<id>` the merge SUBJECT cites;
                                    the cited row's `merge-ready:` marker HEAD joins the merge's 2nd parent by SHA
                                    (head_joins below); BC-A: the author (the row's to_agent) must be the owner
                                    prefix of the branch the merge subject names, normalised to a roster name.
  delegation    asker → recipient   intent='task' rows; an OUTCOME answers the nearest earlier UNANSWERED task from
                                    THAT asker to THAT recipient on THAT thread (BC-D).
  tool_call     caller → author     econ's tool ledger (econ._v2_tool_rows, forge's ledger), demand-qualified,
                                    toolreg.CORE_SERVERS excluded, self-use excluded.
  merge_landed  UNMEASURED in S2    "no recorded merger: a rule, not a fact"
  goal_shipped  UNMEASURED in S2    "goals has no filer column"

A NODE is a name the agents/ tree resolves (charter.roster(), passed in); an edge with an end outside it is
UNMEASURED, counted. A kind whose coverage is under COVERAGE_FLOOR has weight 0 in every view and prints UNMEASURED.

WHY ONE MODULE: devtools/mutation_probe.py mutates ONE subject, so every rule a mutant should be able to break lives
here; src/astryx/influence/shell.py is the IO (SQL, one git pass, the cache write, the CLI) and holds no rule.

BC-R: rows are dicts carrying EXACTLY MSG_COLS, the columns the wire's own read tools return to a resident
(channel/server.mjs read_message). check_rows() refuses any other key, so a reader that selects `delivery` or
`status` fails loudly instead of quietly widening what an edge may cite.
PRIVACY: an edge carries authority REFS (a merge sha, message ids, a tool id), never a body. Bodies are read in
memory to parse a marker or a verdict, and nothing derived from them leaves this module but the parse.
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
import math  # noqa: E402
import re  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402

from astryx.core.toolreg import CORE_SERVERS  # noqa: E402  the platform's servers: toolreg's set, never re-typed
from astryx.core.verdicts import HEX, MARKER_RE, PROSE_PASS_RE, READY_RE, REVISE_RE  # noqa: E402

KINDS = ("pass_land", "delegation", "tool_call", "merge_landed", "goal_shipped")
LIVE_KINDS = ("pass_land", "delegation", "tool_call")
HARD_UNMEASURED = {"merge_landed": "no recorded merger: a rule, not a fact",
                   "goal_shipped": "goals has no filer column"}
# BC-R: read_message's SELECT list (channel/server.mjs), minus the two computed peer flags. The shell's SELECT is
# this list verbatim; the oracle derives the server's list from server.mjs and compares.
MSG_COLS = ("id", "ts", "from_agent", "from_org", "to_agent", "to_org", "thread", "intent", "body")
COVERAGE_FLOOR = 0.5
DAMPING = 0.85
DANGLING = ("teleport", "uniform")
TASK_INTENT = "task"
OUTCOME_INTENTS = ("receipt", "result", "revise")       # plus a review carrying a verdict (is_outcome)
# pulse authorship under BC-R (no `delivery` column): the senders the pulse writes as, the trigger intent, and the
# body prefixes the pulse stamps (schema.txt: pulse.py say()/emit(), senses.py, the pulse-down witness)
PULSE_SENDERS = ("pulse", "pulse-witness", "senses")
PULSE_PREFIXES = ("[trigger ", "[held wake")
PULSE_ELIDED_RE = re.compile(r"^\[\d+ earlier held wakes elided")
SUBJECT_BRANCH_RE = re.compile(r"^Merge (?:branch |remote-tracking branch )?'?([^\s':]+)'?")
CITED_RE = re.compile(r"#(\d+)\b")
LOOSE_READY_RE = re.compile(r"^(\S+)\s+(\S+)\.\.(\S+)")


# ── rows ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def check_rows(rows):
    """BC-R: every row carries exactly MSG_COLS. Returns the rows; raises on a wider (or narrower) row."""
    want = set(MSG_COLS)
    for r in rows:
        if set(r) != want:
            raise ValueError(f"BC-R: a message row must carry exactly the read tools' columns; extra "
                             f"{sorted(set(r) - want)}, missing {sorted(want - set(r))}")
    return rows


def is_pulse(row) -> bool:
    b = row.get("body") or ""
    return (row["from_agent"] in PULSE_SENDERS or row["intent"] == "trigger"
            or b.startswith(PULSE_PREFIXES) or bool(PULSE_ELIDED_RE.match(b)))


def is_node(name, org, roster) -> bool:
    return (org or "local") == "local" and name in roster


def resolve_owner(name, roster, suggest):
    """(roster name | None, how). Exact stem first; else `suggest(name, roster)` (address.suggest: the nickname rule
    a4 → abstractor-4, then edit distance), taken ONLY when it yields exactly one roster name."""
    if not name:
        return None, "no owner prefix"
    low = name.strip().lower()
    if low in roster:
        return low, "exact"
    hits = [h for h in suggest(low, sorted(roster)) if h in roster]
    if len(hits) == 1:
        return hits[0], "alias"
    return None, ("ambiguous alias " + "|".join(hits)) if hits else "unresolvable owner prefix"


# ── the marker (verdicts.py grammar) ───────────────────────────────────────────────────────────────────────────────
def parse_ready(body):
    """Every `merge-ready:` marker in a body → [{branch, base, head} | {error}]. A quoted template ("<") is skipped.
    A symbolic base is NOT resolved: it is reported as "unresolved base: <ref>" (seed alone reads a ref's reflog at
    the marker's ts; today's ref is not what the reviewer read). The join needs only the HEAD, which is hex."""
    out = []
    for kind, args in MARKER_RE.findall(body or ""):
        if kind != "merge-ready" or "<" in args:
            continue
        g = READY_RE.match(args)
        if g:
            base = g[2] if re.fullmatch(HEX, g[2]) else f"unresolved base: {g[2]}"
            out.append({"branch": g[1], "base": base, "head": g[3]})
            continue
        loose = LOOSE_READY_RE.match(args)
        out.append({"error": "non-sha head" if loose and not re.fullmatch(HEX, loose[3]) else "malformed marker"})
    return out


# ── git: the SHA join (inputs are plain dicts from ONE `git log` pass) ─────────────────────────────────────────────
def first_parent_chain(parents, tip):
    """main's first-parent history from `tip`, newest first."""
    out, c = [], tip
    while c is not None and c in parents:
        out.append(c)
        ps = parents[c]
        c = ps[0] if ps else None
    return out


def ancestors(parents, start):
    """Every commit reachable from `start`, `start` included."""
    seen, stack = set(), [start]
    while stack:
        c = stack.pop()
        if c in seen or c not in parents:
            continue
        seen.add(c)
        stack.extend(parents[c])
    return seen


def resolve_sha(prefix, parents):
    """A marker's (possibly abbreviated) hex head → the ONE full sha in the history it prefixes, else None."""
    hits = [s for s in parents if s.startswith(prefix)]
    return hits[0] if len(hits) == 1 else None


def head_joins(head, merge, parents):
    """(joins, how) for a marker HEAD against a main merge commit M (parents[M] = [M^1, M^2]).
    EXACT: head is M^2 (an abbreviated head is that sha's prefix, unique in the history).
    STALE-BUT-CLEAN: head lies on M^2's FIRST-PARENT path before that path enters main (an ancestor of M^1), and EVERY
    commit on the path above head is a merge whose every non-first parent is an ancestor of M^1: a "merge of main",
    bringing in only what main already carried. A non-merge commit there is unreviewed content; so is a merge of
    anything main didn't carry. Anything else (head off that path, unknown, ambiguous) does not join."""
    ps = parents.get(merge) or []
    if len(ps) < 2:
        return False, "not a merge commit"
    p2 = ps[1]
    full = resolve_sha(head, parents)
    if full is None:
        return False, "head not in main's history"
    if full == p2:
        return True, "exact"
    main_side = ancestors(parents, ps[0])
    path, c = [], p2
    while c is not None and c != full and c not in main_side:
        path.append(c)
        cps = parents.get(c) or []
        c = cps[0] if cps else None
    if c != full:
        return False, "head neither the 2nd parent nor on its first-parent path"
    for x in path:
        xps = parents.get(x) or []
        if len(xps) < 2:
            return False, "stale head: a non-merge commit after it"
        if not all(p in main_side for p in xps[1:]):
            return False, "stale head: a merge after it brings in non-main content"
    return True, "stale head, only merges of main after it"


def main_merges(commits, tip, since, until):
    """The window's merges ON main: commits on main's FIRST-PARENT history from `tip` with >=2 parents and a committer
    time in [since, until). A merge reachable only through a 2nd parent is a branch's own merge, not a land.
    commits = {sha: {parents, ts, subject}} from one `git log` pass."""
    parents = {s: c["parents"] for s, c in commits.items()}
    return [{"sha": s, "ts": commits[s]["ts"], "subject": commits[s]["subject"]}
            for s in first_parent_chain(parents, tip)
            if len(commits[s]["parents"]) >= 2 and since <= commits[s]["ts"] < until]


def merge_branch(subject):
    m = SUBJECT_BRANCH_RE.match(subject or "")
    return m.group(1) if m else None


def pass_land_edges(merges, parents, msgs_by_id, roster, suggest):
    """pass_land: author → reviewer. merges = [{sha, ts, subject}] (main's first-parent merges in the window),
    parents = {sha: [parent shas]} over main's history, msgs_by_id = {id: MSG_COLS row}. Returns a ledger:
    {edges, unmeasured: Counter(reason), domain: #merges, measured: #merges with an edge}."""
    check_rows(msgs_by_id.values())
    edges, unmeasured, measured = [], Counter(), 0
    for m in merges:
        ids = [int(i) for i in CITED_RE.findall(m["subject"])]
        if not ids:
            unmeasured["no cited id"] += 1
            continue
        branch = merge_branch(m["subject"])
        prefix = branch.split("/", 1)[0] if branch and "/" in branch else None
        owner, how = resolve_owner(prefix, roster, suggest) if prefix else (None, "no owner prefix")
        found, why = [], []
        for i in ids:
            row = msgs_by_id.get(i)
            if row is None:
                why.append("cited id not in messages")
                continue
            markers = parse_ready(row["body"])
            if not markers:
                why.append("cited row has no merge-ready marker")
                continue
            joined = None
            for mk in markers:
                if "error" in mk:
                    why.append(mk["error"])
                    continue
                ok, j = head_joins(mk["head"], m["sha"], parents)
                if ok:
                    joined = (mk, j)
                    break
                why.append(j)
            if joined is None:
                continue
            if is_pulse(row):
                why.append("pulse row")
                continue
            author, reviewer = row["to_agent"], row["from_agent"]
            if not (is_node(author, row["to_org"], roster) and is_node(reviewer, row["from_org"], roster)):
                why.append("end outside the agents/ tree")
                continue
            if owner is None:
                why.append(f"BC-A: {how}")
                continue
            if author != owner:
                why.append("BC-A: author (to_agent) is not the branch's owner prefix")
                continue
            if author == reviewer:
                why.append("self-loop")
                continue
            found.append({"kind": "pass_land", "src": author, "dst": reviewer, "ts": m["ts"],
                          "ask_ts": row["ts"], "ref": f"sha:{m['sha']} msg:{i} ({joined[1]}; base {joined[0]['base']})",
                          "topic": row.get("thread"), "authority": [i]})
        if found:
            measured += 1
            edges += found
        else:
            unmeasured["; ".join(sorted(set(why))) or "no edge"] += 1
    return {"edges": edges, "unmeasured": unmeasured, "domain": len(merges), "measured": measured}


# ── delegation under BC-D ──────────────────────────────────────────────────────────────────────────────────────────
def is_outcome(row) -> bool:
    """receipt / result / revise, or a review whose body carries a verdict (PROSE_PASS_RE or REVISE_RE)."""
    if row["intent"] in OUTCOME_INTENTS:
        return True
    return row["intent"] == "review" and bool(PROSE_PASS_RE.search(row["body"] or "")
                                              or REVISE_RE.search(row["body"] or ""))


def delegation_edges(rows, roster):
    """delegation: asker → recipient. rows = MSG_COLS rows (any order). Every task in `rows` is the domain.
    (i) an outcome counts only toward a task whose asker is the outcome's to_agent; an outcome whose recipient has
        open tasks on the thread, none from its addressee, is UNMEASURED (counted) and answers nobody.
    (ii) ONE-TO-ONE: an outcome answers only the nearest earlier unanswered task from that asker to that recipient
        on that thread; a task is answered once.
    Pulse rows are never edges. Returns a ledger plus `ambiguous`: (thread, recipient) keys with >=2 askers."""
    rows = sorted(check_rows(rows), key=lambda r: r["id"])
    open_by = defaultdict(list)
    edges, unmeasured, tasks = [], Counter(), []
    bad_tasks, mismatched, answered = set(), set(), set()
    for r in rows:
        if r["intent"] == TASK_INTENT:
            tasks.append(r)
            if is_pulse(r):
                unmeasured["pulse task"] += 1
                bad_tasks.add(r["id"])
            elif not r["thread"]:
                unmeasured["task has no thread"] += 1
                bad_tasks.add(r["id"])
            else:
                open_by[(r["thread"], r["to_agent"])].append(r)
            continue
        if not r["thread"] or not is_outcome(r) or is_pulse(r):
            continue
        cands = [t for t in open_by.get((r["thread"], r["from_agent"]), []) if t["id"] < r["id"]]
        mine = [t for t in cands if t["from_agent"] == r["to_agent"]]
        if not mine:
            if cands:
                unmeasured["(i) outcome to_agent is not the open task's asker"] += 1
                mismatched.update(t["id"] for t in cands)
            continue
        for t in mine[-1:]:                              # (ii): the NEAREST one, and only it
            open_by[(r["thread"], r["from_agent"])].remove(t)
            answered.add(t["id"])
            if not (is_node(t["from_agent"], t["from_org"], roster) and is_node(t["to_agent"], t["to_org"], roster)):
                unmeasured["end outside the agents/ tree"] += 1
                bad_tasks.add(t["id"])
                continue
            if t["from_agent"] == t["to_agent"]:
                unmeasured["self-loop"] += 1
                bad_tasks.add(t["id"])
                continue
            edges.append({"kind": "delegation", "src": t["from_agent"], "dst": t["to_agent"], "ts": r["ts"],
                          "ask_ts": t["ts"], "ref": f"msg:{t['id']}>{r['id']} ({r['intent']})", "topic": t["thread"],
                          "authority": [t["id"], r["id"]], "task_id": t["id"]})
    unmeasured_tasks = bad_tasks | (mismatched - answered)
    askers = defaultdict(set)
    for t in tasks:
        if t["thread"]:
            askers[(t["thread"], t["to_agent"])].add(t["from_agent"])
    ambiguous = sorted((k, sorted(v)) for k, v in askers.items() if len(v) >= 2)
    return {"edges": edges, "unmeasured": unmeasured, "domain": len(tasks),
            "measured": len(tasks) - len(unmeasured_tasks), "ambiguous": ambiguous}


def loop_discount(edges, queries, window_s):
    """THE LOOP DISCOUNT (one writer: the tool's own query log). A delegation edge whose task went from an asker to
    an agent the tool RETURNED to that asker, within window_s after the query, is ROUTED: the graph would be crediting
    its own advice. No token is needed from the sender. Returns (kept edges, routed count)."""
    kept, routed = [], 0
    for e in edges:
        hit = e["kind"] == "delegation" and any(
            q["asker"] == e["src"] and e["dst"] in q["returned"]
            and 0 <= (e["ask_ts"] - q["ts"]).total_seconds() <= window_s for q in queries)
        if hit:
            routed += 1
        else:
            kept.append(e)
    return kept, routed


# ── tool calls ─────────────────────────────────────────────────────────────────────────────────────────────────────
def is_core(rid, core_servers=CORE_SERVERS) -> bool:
    m = re.fullmatch(r"mcp:([\w.-]+)/[\w.-]+", rid) if isinstance(rid, str) else None
    return bool(m) and m.group(1) in core_servers


def tool_edges(calls, roster, coverage):
    """tool_call: caller → author. calls = [{rid, caller, author, dq, ts}] from econ's ledger reader. Core servers'
    calls are outside the domain; demand-unqualified calls and self-use are not edges (econ's tool GDP rule);
    an unresolved author or a non-roster end is UNMEASURED. `coverage` is econ's live tool_gdp coverage."""
    edges, unmeasured = [], Counter()
    domain = [c for c in calls if not is_core(c["rid"])]
    for c in domain:
        if not c["dq"]:
            continue
        if c["author"] in (None, "unknown"):
            unmeasured["author unresolved"] += 1
            continue
        if not (c["caller"] in roster and c["author"] in roster):
            unmeasured["end outside the agents/ tree"] += 1
            continue
        if c["caller"] == c["author"]:
            continue
        edges.append({"kind": "tool_call", "src": c["caller"], "dst": c["author"], "ts": c["ts"], "ask_ts": c["ts"],
                      "ref": f"tool:{c['rid']}", "topic": None, "authority": []})
    return {"edges": edges, "unmeasured": unmeasured, "domain": len(domain),
            "measured": round(coverage * len(domain)), "coverage": coverage}


# ── coverage and the gate ──────────────────────────────────────────────────────────────────────────────────────────
def coverage_of(ledger):
    if "coverage" in ledger:
        return ledger["coverage"]
    return ledger["measured"] / ledger["domain"] if ledger["domain"] else 0.0


def kind_weights(coverages, base=None):
    """{kind: weight}. A kind under COVERAGE_FLOOR, or hard-coded UNMEASURED, is weight 0 in EVERY view."""
    base = base or {}
    out = {}
    for k in KINDS:
        if k in HARD_UNMEASURED or coverages.get(k, 0.0) < COVERAGE_FLOOR:
            out[k] = 0.0
        else:
            out[k] = float(base.get(k, 1.0))
    return out


def agent_coverage(rows, calls, ledgers, weights, roster):
    """{agent: unmapped share}: of an agent's activity in the window (its non-pulse messages sent, plus its tool calls
    in the tool domain), the share that is the authority of NO edge in a weighted kind. A row is mapped when its id is
    cited by such an edge (a task, an outcome, a PASS row); a tool call when it became a weighted tool_call edge."""
    units, mapped = Counter(), Counter()
    cited = {i for lg in ledgers.values() for e in lg["edges"] if weights.get(e["kind"], 0) > 0
             for i in e["authority"]}
    for r in rows:
        if r["from_agent"] in roster and not is_pulse(r):
            units[r["from_agent"]] += 1
            mapped[r["from_agent"]] += r["id"] in cited
    for c in calls:
        if c["caller"] in roster and not is_core(c["rid"]):
            units[c["caller"]] += 1
    if weights.get("tool_call", 0) > 0:
        for e in (ledgers.get("tool_call") or {}).get("edges", []):
            mapped[e["src"]] += 1
    return {a: 1 - mapped[a] / n for a, n in units.items()}, sorted(units)


# ── views and PageRank ─────────────────────────────────────────────────────────────────────────────────────────────
def view(name, weights, teleport, dangling="teleport", half_life_days=14.0):
    """A view is a parameter row: kind weights, half-life, teleport vector, and a DECLARED dangling-mass rule."""
    if dangling not in DANGLING:
        raise ValueError(f"dangling must be one of {DANGLING}")
    return {"name": name, "weights": dict(weights), "teleport": dict(teleport), "dangling": dangling,
            "half_life_days": half_life_days}


def global_view(weights, active):
    """GLOBAL: uniform teleport over the active agents (the floor)."""
    return view("global", weights, {a: 1.0 for a in active})


def routing_view(weights, asker, topic_agents=()):
    """ROUTING: teleport on the asker; given a topic, half the mass on the agents linked to it."""
    tp = {asker: 1.0}
    others = [a for a in topic_agents if a != asker]
    if others:
        tp = {asker: 0.5}
        for a in others:
            tp[a] = tp.get(a, 0.0) + 0.5 / len(others)
    return view("routing", weights, tp)


def weighted(edges, v, now):
    """[(src, dst, w)] for edges strictly before `now`: kind weight x 0.5^(age / half-life)."""
    out = []
    for e in edges:
        w = v["weights"].get(e["kind"], 0.0)
        if w <= 0 or e["src"] == e["dst"] or not e["ts"] < now:
            continue
        age = (now - e["ts"]).total_seconds() / 86400.0
        w *= math.pow(0.5, age / v["half_life_days"])
        if w > 0:                                        # an edge decayed to underflow carries nothing
            out.append((e["src"], e["dst"], w))
    return out


def pagerank(nodes, wedges, teleport, dangling="teleport", d=DAMPING, tol=1e-13, max_iter=10000):
    """Pure power iteration. Credit flows src → dst. teleport = {node: mass} (normalised here). DANGLING mass (a node
    with no out-edge) returns by the declared rule: 'teleport' (the teleport vector, so a personalized view stays
    personalized) or 'uniform' (every node equally)."""
    nodes = sorted(set(nodes) | {s for s, _, _ in wedges} | {t for _, t, _ in wedges} | set(teleport))
    if not nodes:
        return {}
    z = sum(teleport.get(n, 0.0) for n in nodes)
    if z <= 0:
        raise ValueError("teleport vector has no mass")
    v = {n: teleport.get(n, 0.0) / z for n in nodes}
    out = defaultdict(lambda: defaultdict(float))
    for s, t, w in wedges:
        out[s][t] += w
    tot = {s: sum(ts.values()) for s, ts in out.items()}
    u = 1.0 / len(nodes)
    r = dict(v)
    for _ in range(max_iter):
        dm = sum(r[n] for n in nodes if not tot.get(n))
        nxt = {n: (1 - d) * v[n] + d * dm * (v[n] if dangling == "teleport" else u) for n in nodes}
        for s, ts in out.items():
            for t, w in ts.items():
                nxt[t] += d * r[s] * w / tot[s]
        if sum(abs(nxt[n] - r[n]) for n in nodes) < tol:
            return nxt
        r = nxt
    raise RuntimeError("pagerank did not converge")


def scores(edges, v, nodes, now):
    return pagerank(nodes, weighted(edges, v, now), v["teleport"], v["dangling"])


def neighbours(edges, agent, n=3):
    c = Counter()
    for e in edges:
        if e["src"] == agent:
            c[e["dst"]] += 1
        elif e["dst"] == agent:
            c[e["src"]] += 1
    return [a for a, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def top_k(sc, asker, k, live, edges):
    """Advisory top-k by score: never the asker, only agents `live` admits, only a positive score; each with its
    graph neighbours beside it."""
    ranked = sorted((a for a in sc if a != asker and sc[a] > 0 and live(a)), key=lambda a: (-sc[a], a))
    return [{"agent": a, "score": sc[a], "neighbours": neighbours(edges, a)} for a in ranked[:k]]


NO_LIVENESS = ("none", lambda a: True)


def who_should_i_ask(asker, edges, coverages, nodes, now, k=5, liveness=NO_LIVENESS, topic=None):
    """THE TOOL's logic (advisory). Routing view at QUERY time over the edge cache, teleport on the asker (plus the
    agents linked to `topic`: ends of edges whose thread contains it). `liveness` is an INJECTED (name, predicate);
    the default is no filter, and the reply prints which filter ran. Returns {returned, lines}."""
    w = kind_weights(coverages)
    tagents = sorted({x for e in edges if topic and topic.lower() in (e.get("topic") or "").lower()
                      for x in (e["src"], e["dst"])}) if topic else []
    v = routing_view(w, asker, tagents)
    sc = scores(edges, v, nodes, now)
    top = top_k(sc, asker, k, liveness[1], edges)
    lines = [f"who should {asker} ask{f' about {topic!r}' if topic else ''} (advisory; routing view, PPR d={DAMPING},"
             f" dangling={v['dangling']})", f"liveness: {liveness[0]}"]
    for k_, kw in sorted(w.items()):
        if kw == 0:
            lines.append(f"  {k_}: UNMEASURED (weight 0)")
    for i, t in enumerate(top, 1):
        lines.append(f"  {i}. {t['agent']}  {t['score']:.4f}  neighbours: {', '.join(t['neighbours']) or '-'}")
    if not top:
        lines.append("  (no agent reachable from the asker in the measured graph)")
    return {"returned": [t["agent"] for t in top], "lines": lines, "view": v["name"]}


# ── the report ─────────────────────────────────────────────────────────────────────────────────────────────────────
def report(ledgers, values, agent_unmapped):
    """Lines: per kind its coverage, weight or UNMEASURED (with reasons); per agent its score beside its unmapped
    share. A mostly-unmapped agent reads 'unmeasured', never a low rank."""
    cov = {k: coverage_of(lg) for k, lg in ledgers.items()}
    w = kind_weights(cov)
    lines = ["kinds:"]
    for k in KINDS:
        if k in HARD_UNMEASURED:
            lines.append(f"  {k}: UNMEASURED ({HARD_UNMEASURED[k]})")
            continue
        lg = ledgers.get(k) or {"domain": 0, "measured": 0, "unmeasured": Counter()}
        state = f"weight {w[k]:g}" if w[k] > 0 else f"UNMEASURED (coverage under {COVERAGE_FLOOR:.0%}: weight 0)"
        lines.append(f"  {k}: coverage {cov.get(k, 0.0):.1%} of {lg['domain']}; edges {len(lg.get('edges', []))};"
                     f" {state}")
        for why, n in lg["unmeasured"].most_common():
            lines.append(f"      {n:4d}  UNMEASURED: {why}")
    lines.append("agents (global view):")
    for a in sorted(values, key=lambda a: (-values[a], a)):
        un = agent_unmapped.get(a, 1.0)
        verdict = "unmeasured" if un > 0.5 else "measured"
        lines.append(f"  {a:14s} {values[a]:.4f}  unmapped {un:.0%}  {verdict}")
    return lines


# ── the backtest's arithmetic ──────────────────────────────────────────────────────────────────────────────────────
def mid_rank(sc, target, candidates):
    """1-based rank of target among candidates by score, ties at their mid-rank (so an all-tie reads (n+1)/2)."""
    s = sc.get(target, 0.0)
    above = sum(1 for c in candidates if sc.get(c, 0.0) > s)
    ties = sum(1 for c in candidates if sc.get(c, 0.0) == s)
    return above + (ties + 1) / 2


def backtest(edges, nodes, weights, since):
    """For each answered delegation and each landed review whose ASK (task / PASS row) is at or after `since`: rank
    the agent who delivered (edge dst) among every node but the asker, under (routing) teleport on the asker, (global)
    uniform teleport over the agents active before the ask, (uniform) no information, all over edges STRICTLY before
    the ask. Returns {method: [rank, ...]} and per-kind event counts."""
    res, by_kind = {"routing": [], "global": [], "uniform": []}, Counter()
    for e in sorted((e for e in edges if e["kind"] in ("delegation", "pass_land") and e["ask_ts"] >= since),
                    key=lambda e: e["ask_ts"]):
        t, asker, got = e["ask_ts"], e["src"], e["dst"]
        cands = [n for n in nodes if n != asker]
        if got not in cands:
            continue
        by_kind[e["kind"]] += 1
        prior = [x for x in edges if x["ts"] < t]
        active = sorted({x for p in prior for x in (p["src"], p["dst"])} | {asker})
        res["routing"].append(mid_rank(scores(prior, routing_view(weights, asker), nodes, t), got, cands))
        res["global"].append(mid_rank(scores(prior, global_view(weights, active), nodes, t), got, cands))
        res["uniform"].append(mid_rank({}, got, cands))
    return res, by_kind
