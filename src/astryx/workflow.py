#!/usr/bin/env python3
"""astryx · workflows: a goal's planned coordination, and what the substrate measured of it (plan-11324 S4).

The owner's idea (10-18): each goal carries a WORKFLOW, a simple DAG of which agent does which task, converging on ONE
agent who compiles the result and finishes the goal. It is a general structure, not a rule: agents still reach anyone on
the wire when work demands it. With timelines it renders as a Gantt chart. abstractor-1's amendments (#60109) are the
rules marked A-E below.

    body = {"goal": 11324, "converge": "seed",
            "tasks": [{"id": "S3a", "title": "org home", "agent": "forge", "review": "abstractor-2",
                       "needs": ["S2"], "plan": ["2026-10-16", "2026-10-17"], "done": true}, ...]}

THE ONLY HARD RULES (validate): an acyclic graph; exactly ONE sink, owned by `converge`; every agent and reviewer in the
roster; needs name existing ids; review is not the task's agent; ids are unique; and (C) a revision may not DELETE a
task that has measured actuals: it marks it "dropped": true, and the Gantt keeps the bar.

ACTUALS ARE MEASURED, never self-reported:
  A  a commit is attributed to a task by its `Task: <goal>/<id>` trailer (land.sh writes it from now on), else by the
     backlog normaliser below over the subject spellings the org actually uses ("plan-11324 S3b", "11324 S1",
     "plan-11324-s2"). A commit that names the goal but no task id is UNATTRIBUTED: counted and shown, never dropped.
  B  only commits REACHABLE FROM origin/main count: a merge-ready, a receipt, or a local land that rolled back is not a
     fact about main (S3a was PASSed at #59038, then went red and rolled back at #59151).
  A task's measured span is its first..last attributed commit. It is DONE when its revision marks it done AND main
  carries at least one attributed commit: the claim needs the substrate, the substrate alone cannot say "finished".

STATUS (now = the reading's clock): dropped · done · active (commits, not done) · blocked (planned start passed while a
need is not done) · late (planned end passed, needs done, not done) · planned.
CRITICAL PATH: the longest planned-duration chain into the sink (a task without a plan weighs 0).

PURE: no SQL, no git, no clock. shell functions at the bottom do the IO.
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (as influence/graph.py)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__)))))
import re  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

UNATTRIBUTED = "UNATTRIBUTED"


class WorkflowError(ValueError):
    pass


def _ts(s):
    if s is None:
        return None
    d = datetime.fromisoformat(s) if isinstance(s, str) else s
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def validate(body: dict, roster, prev: dict | None = None, measured=frozenset()) -> list[str]:
    """Every violation, as a sentence. [] means valid. `prev` is the revision this one replaces, and `measured` the ids
    that have attributed commits on main (rule C protects MEASURED history, not only claimed history: a1 #60116 R-1)."""
    errs = []
    tasks = body.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return ["a workflow needs a non-empty tasks list"]
    roster = set(roster)
    ids = [t.get("id") for t in tasks]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        errs.append("task ids must be unique non-empty strings")
    idset = set(ids)
    for t in tasks:
        if t.get("agent") not in roster:
            errs.append(f"{t.get('id')}: agent {t.get('agent')!r} is not in the roster")
        if t.get("review") is not None:
            if t["review"] not in roster:
                errs.append(f"{t.get('id')}: reviewer {t['review']!r} is not in the roster")
            if t["review"] == t.get("agent"):
                errs.append(f"{t.get('id')}: the reviewer is the task's own agent")
        for flag in ("done", "dropped"):
            if flag in t and not isinstance(t[flag], bool):
                errs.append(f"{t.get('id')}: {flag} must be true or false, not {t[flag]!r}")
        for n in t.get("needs", []):
            if n not in idset:
                errs.append(f"{t.get('id')}: needs {n!r}, which is no task")
        p = t.get("plan")
        if p is not None:
            try:
                if len(p) != 2 or _ts(p[0]) > _ts(p[1]):
                    errs.append(f"{t.get('id')}: plan must be [start, end] with start <= end")
            except (TypeError, ValueError):
                errs.append(f"{t.get('id')}: plan dates must be ISO dates")
    if errs:
        return errs
    # acyclic (Kahn), then the single sink
    needs = {t["id"]: list(t.get("needs", [])) for t in tasks}
    indeg = {i: len(needs[i]) for i in needs}
    users = {i: [j for j in needs if i in needs[j]] for i in needs}
    queue, seen = [i for i in needs if indeg[i] == 0], 0
    while queue:
        i = queue.pop()
        seen += 1
        for j in users[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                queue.append(j)
    if seen != len(needs):
        errs.append("the workflow has a cycle")
    live = [t for t in tasks if not t.get("dropped")]
    dropped = {t["id"] for t in tasks if t.get("dropped")}
    for t in live:
        for n in t.get("needs", []):
            if n in dropped:
                errs.append(f"{t['id']} needs dropped task {n}: rewire the need, or drop {t['id']} too")
    sinks = [t for t in live if not any(t["id"] in u.get("needs", []) for u in live)]
    if len(sinks) != 1:
        errs.append(f"everything must converge on ONE final task; this has {len(sinks)}: {sorted(s['id'] for s in sinks)}")
    elif sinks[0]["agent"] != body.get("converge"):
        errs.append(f"the final task {sinks[0]['id']} belongs to {sinks[0]['agent']}, not the converge agent "
                    f"{body.get('converge')!r}")
    if prev:
        for t in prev.get("tasks", []):
            if t["id"] not in idset and (t["id"] in measured or t.get("done")):
                errs.append(f"{t['id']} has measured history: mark it \"dropped\": true instead of deleting it")
    return errs


def task_re(goal: int):
    """The backlog normaliser (rule A): (plan-)?<goal>[ /:_-]+<id>, case-insensitive, the goal number not part of a
    longer number. The id is whatever word follows; attribute() decides whether it is one of the workflow's ids."""
    return re.compile(rf"(?i)(?<![0-9])(?:plan-)?{goal}(?![0-9])[ /:_-]+([a-z][a-z0-9]*)")


def attribute(goal: int, ids, subject: str, trailer: str | None = None):
    """The task id a commit belongs to, UNATTRIBUTED if it names the goal but no task, None if it is not the goal's."""
    by_lower = {i.lower(): i for i in ids}
    if trailer:
        m = re.fullmatch(rf"\s*{goal}/(\S+)\s*", trailer)
        if m and m.group(1).lower() in by_lower:
            return by_lower[m.group(1).lower()]
    for m in task_re(goal).finditer(subject):
        if m.group(1).lower() in by_lower:
            return by_lower[m.group(1).lower()]
    if re.search(rf"(?<![0-9]){goal}(?![0-9])", subject):
        return UNATTRIBUTED
    return None


def critical_path(tasks) -> set[str]:
    live = {t["id"]: t for t in tasks if not t.get("dropped")}

    def dur(t):
        p = t.get("plan")
        return (_ts(p[1]) - _ts(p[0])).total_seconds() if p else 0.0
    best = {}

    def longest(i):
        if i not in best:
            t = live[i]
            prev = [(longest(n), n) for n in t.get("needs", []) if n in live]
            top = max(prev) if prev else (0.0, None)
            best[i] = (dur(t) + top[0], top[1])
        return best[i][0]
    sinks = [i for i in live if not any(i in u.get("needs", []) for u in live.values())]
    if not sinks:
        return set()
    cur, path = max(sinks, key=longest), set()
    while cur:
        path.add(cur)
        cur = best[cur][1]
    return path


def status(body: dict, commits, now) -> dict:
    """The measured reading. `commits` = [(sha, ts, subject, trailer)] REACHABLE FROM origin/main (rule B is the
    caller's to keep: the shell reads only `git log origin/main`)."""
    goal, tasks = body["goal"], body["tasks"]
    ids = [t["id"] for t in tasks]
    got = {i: [] for i in ids}
    un = []
    for sha, ts, subject, trailer in commits:
        a = attribute(goal, ids, subject, trailer)
        if a == UNATTRIBUTED:
            un.append(_ts(ts))
        elif a is not None:
            got[a].append(_ts(ts))
    now = _ts(now)
    crit = critical_path(tasks)
    done = {t["id"] for t in tasks if t.get("done") and got[t["id"]]}
    out = []
    for t in tasks:
        c = sorted(got[t["id"]])
        actual = {"start": c[0].isoformat(), "end": c[-1].isoformat(), "commits": len(c)} if c else None
        p = t.get("plan")
        ps, pe = (_ts(p[0]), _ts(p[1])) if p else (None, None)
        needs_done = all(n in done for n in t.get("needs", []))
        if t.get("dropped"):
            st = "dropped"
        elif t["id"] in done:
            st = "done"
        elif ps and now > ps and not needs_done:
            st = "blocked"
        elif pe and now > pe:
            st = "late"
        elif c:
            st = "active"
        else:
            st = "planned"
        out.append({"id": t["id"], "title": t.get("title", ""), "agent": t["agent"], "review": t.get("review"),
                    "needs": list(t.get("needs", [])), "plan": list(p) if p else None, "actual": actual,
                    "status": st, "critical": t["id"] in crit})
    un.sort()
    return {"goal": goal, "converge": body.get("converge"),
            "domain": f"commits on origin/main naming plan-{goal}",
            "tasks": out,
            "unattributed": {"commits": len(un), "first": un[0].isoformat() if un else None,
                             "last": un[-1].isoformat() if un else None}}


def planned_edges(body: dict) -> set[tuple[str, str]]:
    """Rule E: the planned coordination as influence edges (credit flows src -> dst): an author relies on its reviewer,
    and a task's agent relies on the agent of each task it needs."""
    by = {t["id"]: t for t in body["tasks"] if not t.get("dropped")}
    e = set()
    for t in by.values():
        if t.get("review"):
            e.add((t["agent"], t["review"]))
        for n in t.get("needs", []):
            if n in by and by[n]["agent"] != t["agent"]:
                e.add((t["agent"], by[n]["agent"]))
    return e


def overlay(body: dict, measured) -> dict:
    """`measured` = [(src, dst, n)] influence edges on thread plan-<goal>. Three classes; the domain is said."""
    plan = planned_edges(body)
    m = {(s, d): n for s, d, n in measured}
    edges = [{"src": s, "dst": d, "n": m.get((s, d), 0),
              "class": "planned_happened" if (s, d) in m else "planned_unused"} for s, d in sorted(plan)]
    edges += [{"src": s, "dst": d, "n": n, "class": "unplanned"} for (s, d), n in sorted(m.items()) if (s, d) not in plan]
    return {"thread": f"plan-{body['goal']}", "edges": edges}


def unattributed(commits, workflows: dict) -> list[tuple[str, int, str]]:
    """Commits that name a goal carrying a workflow but resolve to none of its tasks: [(sha, goal, subject)].
    land.sh refuses a range holding one, so a task's work is attributed before it lands, never after (steward #60232:
    two shipped tasks read late because their subjects were off-form). `commits` = [(sha, subject, trailer)],
    `workflows` = {goal: [task ids]}."""
    out = []
    for sha, subject, trailer in commits:
        for goal, ids in sorted(workflows.items()):
            if (attribute(goal, ids, subject, trailer) == UNATTRIBUTED
                    and re.search(rf"(?i)(?:plan-|goal |\(|^){goal}(?![0-9])", subject)):   # never a cited "#<msg id>"
                out.append((sha, goal, subject))
    return out


# ------------------------------------------------------------------------------------------------- shell (IO only)
def main_commits(repo, goal: int, ref: str = "origin/main"):
    """[(sha, ts, subject, Task-trailer)] of every commit on `ref` whose subject or trailer names the goal."""
    import subprocess
    out = subprocess.run(["git", "-C", str(repo), "log", ref, "--format=%H%x1f%cI%x1f%s%x1f%(trailers:key=Task,valueonly,separator=%x2c)%x1e"],
                         capture_output=True, text=True, check=True).stdout
    pat = re.compile(rf"(?<![0-9]){goal}(?![0-9])")
    rows = []
    for rec in out.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) == 4 and (pat.search(parts[2]) or pat.search(parts[3])):
            rows.append((parts[0], parts[1], parts[2], parts[3].strip() or None))
    return rows


def load(conn, goal: int):
    """(rev, body) of the goal's latest workflow revision, or None."""
    r = conn.execute("SELECT rev, body FROM goal_workflow WHERE goal_id=%s ORDER BY rev DESC LIMIT 1", (goal,)).fetchone()
    return (r[0], r[1]) if r else None


def goals(conn) -> list[int]:
    """Every goal that carries a workflow (stale_goals retires its goal-level nag for these)."""
    return [r[0] for r in conn.execute("SELECT DISTINCT goal_id FROM goal_workflow ORDER BY 1").fetchall()]


def save(conn, goal: int, body: dict, author: str, roster, repo) -> int:
    """Validate against the roster and the previous revision (rule C), then append. Returns the new rev."""
    import json
    if body.get("goal") != goal:
        raise WorkflowError(f"the body names goal {body.get('goal')!r}, not {goal}")
    prev = load(conn, goal)
    measured = set()
    if prev:
        ids = [t["id"] for t in prev[1].get("tasks", [])]
        measured = {a for _, _, sub, tr in main_commits(repo, goal) if (a := attribute(goal, ids, sub, tr)) in ids}
    errs = validate(body, roster, prev[1] if prev else None, measured)
    if errs:
        raise WorkflowError("; ".join(errs))
    rev = (prev[0] + 1) if prev else 1
    conn.execute("INSERT INTO goal_workflow (goal_id, rev, body, author) VALUES (%s, %s, %s::jsonb, %s)",
                 (goal, rev, json.dumps(body), author))
    return rev


def _main(argv) -> int:
    """python -m astryx.workflow set <goal> <body.json> [author]   validate + append a revision
       python -m astryx.workflow check <body.json>                 validate only (no DB)
       python -m astryx.workflow show <goal>                       the measured reading, as JSON
       python -m astryx.workflow lint <A>..<B>                     rc 1 if a commit names a workflow goal but no task"""
    import json
    import os
    import sys
    from pathlib import Path
    from astryx.core.charter import roster
    if argv[:1] == ["check"] and len(argv) == 2:
        errs = validate(json.loads(Path(argv[1]).read_text()), roster())
        print("\n".join(errs) or "valid")
        return 1 if errs else 0
    import psycopg
    from astryx import config
    repo = Path(__file__).resolve().parents[2]
    try:
        conn = psycopg.connect(config.dsn(), autocommit=True)
    except Exception as e:                    # no database is NOT a finding: rc 2, which land.sh reports as NOT CHECKED
        print(f"no database: {type(e).__name__}", file=sys.stderr)
        return 2
    with conn:
        if argv[:1] == ["set"] and len(argv) in (3, 4):
            body = json.loads(Path(argv[2]).read_text())
            try:
                rev = save(conn, int(argv[1]), body, argv[3] if len(argv) == 4 else os.environ.get("ASTRYX_AGENT", "owner"), roster(), repo)
            except WorkflowError as e:
                print(f"refused: {e}", file=sys.stderr)
                return 1
            print(f"goal {argv[1]} workflow rev {rev}")
            return 0
        if argv[:1] == ["lint"] and len(argv) == 2:
            import subprocess
            log = subprocess.run(["git", "-C", str(repo), "log", argv[1],
                                  "--format=%H%x1f%s%x1f%(trailers:key=Task,valueonly,separator=%x2c)%x1e"],
                                 capture_output=True, text=True, check=True).stdout
            commits = [tuple(r.strip("\n").split("\x1f")) for r in log.split("\x1e") if r.strip()]
            commits = [(c[0], c[1], c[2].strip() or None) for c in commits if len(c) == 3]
            wfs = {g: [t["id"] for t in load(conn, g)[1]["tasks"]] for g in goals(conn)}
            bad = unattributed(commits, wfs)
            for sha, g, subj in bad:
                print(f"UNATTRIBUTED {sha[:12]} names goal {g} but none of its tasks {wfs[g]}: {subj[:90]}")
            return 1 if bad else 0
        if argv[:1] == ["show"] and len(argv) == 2:
            got = load(conn, int(argv[1]))
            if not got:
                print(f"goal {argv[1]} has no workflow", file=sys.stderr)
                return 1
            print(json.dumps({"rev": got[0], **status(got[1], main_commits(repo, int(argv[1])), datetime.now(timezone.utc))}, indent=1))
            return 0
    print(_main.__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
