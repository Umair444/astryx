#!/usr/bin/env python3
"""Tool-GDP census on the LIVE ledger (goal 11324 S1 Done, plan-11324 #57873 item 4): two deltas on a fixed domain,
two instruments, and the residual named. Read-only.

    venv/bin/python devtools/tool_census.py [--days 7] [--before <git ref>] [--dsn <fixture>]

(a) DOMAIN CHANGE, declared once: econ's tool GDP with core servers in vs out (toolreg.CORE_SERVERS rebound to ()
    for the "in" side, so the toggle is the one econ reads). This is a change of what is measured, not a fix.
(b) S1's FIXES, before vs after, on the agent-authored domain (core out on both sides):
    - canonical + authorship folds: the same live rows, authored by --before's toolreg (no canonical(), no MOVED
      fold) and by this tree's. Only (b) is S1's achievement.
    - worktree stamps (LEDGER_V 2): a stamp happens at call time, so history keeps its old stamps. This counts the
      transcript tool calls of the window that --before's resolver gave no id and this tree's does (a counterfactual
      re-resolution of the same inputs). Re-measure post-land on rows stamped v2.
(c) TWO INSTRUMENTS over one window:
    A  econ (_v2_tool_rows → the domain), the number the [econ] line shows;
    B1 steps kind=tool whose content names mcp__<server>__<tool> for a registry.json server: steps CONTENT, no
       toolreg resolver (independent of the resolver);
    B2 transcript tool_use blocks (turns.raw_payload) whose Bash command NAMES a tracked script under a tool root,
       by a regex re-derived here (not toolreg.ids_in_command). Naming is an upper bound on running: a `cat x.sh`
       counts in B2 and not in A. Its independent axis is the WRITER (the Stop transcript vs step.py's row).
    Each difference is printed with its domain.
(d) RESIDUAL: unresolved (before) = moved (resolved by S1's folds) + residual (still unknown), with residual's causes.

PRIVACY (I5 posture): tool inputs are read in memory and never printed or stored; output is ids, agent names and
counts only.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
from astryx.econ import econ  # noqa: E402
from astryx.core import toolreg  # noqa: E402
from astryx.paths import common_dir  # noqa: E402

# the live tree is the one the hook resolved against: the common dir's checkout, wherever this copy runs from
LIVE = Path(os.environ.get("ASTRYX_LIVE_REPO") or common_dir(HERE).parent)
ROOTS = ("nucleus", "src/astryx", "scripts", "devtools", "skills", "mcp")
SCRIPT_RE = re.compile(r"(?:^|[\s'\"=;&|(<>/])((?:%s)/[\w.@+-]+(?:/[\w.@+-]+)*\.(?:py|sh|mjs|js))(?=$|[\s'\";&|)<>])"
                       % "|".join(re.escape(r) for r in ROOTS))


_SEG = re.compile(r"&&|\|\||[;&|\n(]|\$\(")
_WRAP = re.compile(r"^(?:timeout|env|nice|nohup|exec|time|stdbuf|command)$")
_INTERP = re.compile(r"^(?:\S*/)?(?:python[\d.]*|bash|sh|node|uv|pytest)$")


def exec_scripts(cmd):
    """Tracked-script candidates at an EXECUTION position, re-derived here (not toolreg.ids_in_command): the first
    word of each command segment after VAR=x assignments, wrappers (timeout 60, env, nice …), interpreter flags
    and `-m`-less interpreters. Coarser than toolreg on purpose: a quoted ; or a heredoc body splits it wrongly."""
    out = []
    for seg in _SEG.split(cmd):
        w = seg.strip().split()
        while w and (re.fullmatch(r"[A-Za-z_]\w*=\S*", w[0]) or _WRAP.match(w[0]) or re.fullmatch(r"-\S+|\d+[smh]?", w[0])):
            w = w[1:]
        if w and _INTERP.match(w[0]):
            w = w[1:]
            while w and w[0].startswith("-"):
                w = w[1:]
        if w:
            out += SCRIPT_RE.findall(" " + w[0])
    return out


def load_toolreg(ref):
    """--before's toolreg.py as a module, its REPO pointed at the live tree (so its absolute-path test is the one
    the live hook ran)."""
    src = subprocess.run(["git", "-C", str(LIVE), "show", f"{ref}:src/astryx/core/toolreg.py"], check=True,
                         capture_output=True, text=True).stdout
    d = tempfile.mkdtemp(prefix="census-")
    p = Path(d) / "toolreg_before.py"
    p.write_text(src)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("toolreg_before", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.REPO, m.REPO_S = LIVE, str(LIVE)
    shutil.rmtree(d)
    return m


def gdp(rows):
    g = econ._v2_tool_gdp(rows)
    return {"calls": len(econ._v2_domain(rows)) if rows else 0, "value": g["value"], "coverage": g["coverage"]}


def fmt(x):
    return f"{x['calls']} calls · coverage {x['coverage']:.2%} · value {x['value']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--until", help="the window's end, ISO 8601 (default now): re-measure a past window exactly")
    ap.add_argument("--dsn", help="a database other than the org's (tests/test_tool_census.py's fixture)")
    ap.add_argument("--before", help="git ref whose toolreg is the 'before' side of (b) (e.g. the pre-S1 main)")
    a = ap.parse_args()
    import psycopg
    until = datetime.fromisoformat(a.until) if a.until else datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    since = until - timedelta(days=a.days)
    conn = psycopg.connect(a.dsn or econ._dsn(), autocommit=True, connect_timeout=5)
    conn.execute("SET default_transaction_read_only = on")
    print(f"tool census · window {since:%Y-%m-%d %H:%M} → {until:%Y-%m-%d %H:%M} UTC ({a.days} d) · "
          f"core = toolreg.CORE_SERVERS {tuple(toolreg.CORE_SERVERS)}")

    toolreg.REPO, toolreg.REPO_S = LIVE, str(LIVE)   # resolve as the live hook does, from any checkout
    after, ok = econ._v2_tool_rows(conn, since.isoformat(), until.isoformat())
    if not ok:
        print("authorship unavailable: nothing measured")
        return 1
    # (a) the domain change, declared once: the same rows, the toggle econ reads
    saved = toolreg.CORE_SERVERS
    try:
        toolreg.CORE_SERVERS = ()
        all_in = gdp(after)
    finally:
        toolreg.CORE_SERVERS = saved
    dom = gdp(after)
    print("\n(a) DOMAIN CHANGE (declared, not a fix):")
    print(f"    core in : {fmt(all_in)}")
    print(f"    core out: {fmt(dom)}")

    # (b) before vs after on the fixed (agent-authored) domain
    raw = conn.execute(f"""
        SELECT s.meta->>'registry_id', s.agent, {econ._V2_DEMAND}
        FROM steps s JOIN turns t ON t.id = s.turn_id
        WHERE s.kind = 'tool' AND s.meta ? 'registry_id' AND s.meta ? 'v'
          AND s.ts >= %s AND s.ts < %s""", (sorted(econ.INTERNAL_ORGS), since, until)).fetchall()
    before = None
    if a.before:
        tb = load_toolreg(a.before)
        with conn.cursor() as cur:
            wb = tb.authorship(cur, sorted({r[0] for r in raw}))
            wa = toolreg.authorship(cur, sorted({r[0] for r in raw}))
        before = [(rid, caller, (wb.get(rid) or {}).get("author"), bool(dq)) for rid, caller, dq in raw]
        # the same raw rows, after: econ's own post-processing, paired with `before` row for row
        paired = [(toolreg.canonical(rid), caller, (wa.get(rid) or {}).get("author"), bool(dq)) for rid, caller, dq in raw]
        if Counter(paired) != Counter(after):
            print("    NOTE: the paired re-derivation differs from econ._v2_tool_rows (rows moved between the two reads)")
        b = gdp(before)
        try:
            toolreg.CORE_SERVERS = ()
            b_in = gdp(before)
        finally:
            toolreg.CORE_SERVERS = saved
        print(f"    (a) on --before's rows: core in {fmt(b_in)} → core out {fmt(b)}")
        print(f"\n(b) S1's FIXES on the agent-authored domain (before = toolreg@{a.before}, after = this tree):")
        print(f"    before: {fmt(b)}")
        print(f"    after : {fmt(dom)}")
        canon_only = [(toolreg.canonical(r[0]), r[1], r[2], r[3]) for r in before]
        print(f"    canonical() alone (before's authors): {fmt(gdp(canon_only))}: value moves by ids MERGING "
              f"(a pre-move id and its moved id were 2 tools); the rest of the value move is self-use the new "
              f"authors make discountable")
        dv = f"{dom['value'] - b['value']:+d}" if dom["value"] is not None and b["value"] is not None else "n/a"
        print(f"    delta : coverage {dom['coverage'] - b['coverage']:+.2%} · value {dv} · "
              f"distinct tools {len({r[0] for r in econ._v2_domain(before)})} → {len({r[0] for r in econ._v2_domain(after)})}")
    else:
        print("\n(b) skipped: no --before ref given")

    # transcripts: the stamp counterfactual (b) and instrument B2 (c), over turns that ENDED in the window
    turns = conn.execute("SELECT id, agent, raw_payload->'messages' FROM turns "
                         "WHERE ended_at >= %s AND ended_at < %s AND raw_payload ? 'messages'", (since, until)).fetchall()
    tracked = set(subprocess.run(["git", "-C", str(LIVE), "ls-files", *ROOTS], check=True, capture_output=True,
                                 text=True).stdout.split())
    blocks = named = execd = 0
    gained, gained_ids, gained_edits = 0, Counter(), 0
    per_turn = Counter()
    for turn_id, agent, msgs in turns:
        for msg in msgs or []:
            m = msg.get("message") if isinstance(msg, dict) else None
            for blk in (m.get("content") if isinstance(m, dict) and isinstance(m.get("content"), list) else []):
                if not (isinstance(blk, dict) and blk.get("type") == "tool_use"):
                    continue
                blocks += 1
                name, inp = blk.get("name"), blk.get("input")
                if name == "Bash" and isinstance(inp, dict) and isinstance(inp.get("command"), str):
                    if any(p in tracked for p in SCRIPT_RE.findall(inp["command"])):
                        named += 1
                    if any(p in tracked for p in exec_scripts(inp["command"])):
                        execd += 1
                        per_turn[turn_id] += 1
                if a.before:
                    nb, na = tb._resolve(name, inp), toolreg._resolve(name, inp)
                    if na.get("registry_id") and not nb.get("registry_id"):
                        gained += 1
                        gained_ids[toolreg.canonical(na["registry_id"]).split("/")[0]] += 1
                    if na.get("edits") and not nb.get("edits"):
                        gained_edits += 1
    if a.before:
        print(f"    stamps (counterfactual, LEDGER_V 2): of {blocks} transcript tool calls in the window, {gained} "
              f"get an id from this tree's resolver and none from toolreg@{a.before}, and {gained_edits} Writes/Edits "
              f"gain authorship evidence. History keeps its v1 stamps: re-measure on v2-stamped rows post-land.")

    # (c) two instruments
    a_rows = econ._v2_domain(after)
    a_mcp = sum(1 for r in a_rows if r[0].startswith("mcp:"))
    a_scr = sum(1 for r in a_rows if r[0].startswith("script:"))
    reg = set(json.loads((LIVE / "mcp" / "registry.json").read_text())) - set(toolreg.CORE_SERVERS)   # the domain
    b1 = conn.execute(r"""
        SELECT count(*), count(*) FILTER (WHERE NOT meta ? 'registry_id'), count(*) FILTER (WHERE NOT meta ? 'v'),
               count(*) FILTER (WHERE turn_id IS NULL)
        FROM steps WHERE kind = 'tool' AND ts >= %s AND ts < %s
          AND substring(content from '^mcp__(.+?)__[^_:]') = ANY(%s)""", (since, until, sorted(reg))).fetchone()
    print("\n(c) TWO INSTRUMENTS (agent-authored domain):")
    print(f"    A  econ: {len(a_rows)} calls ({a_mcp} mcp, {a_scr} script), coverage {dom['coverage']:.2%}")
    print(f"    B1 steps content naming a registry.json server's tool: {b1[0]} (A's mcp: {a_mcp}; difference "
          f"{b1[0] - a_mcp:+d}: {b1[1]} carry no registry_id, {b1[2]} no meta.v, {b1[3]} no closed turn yet)")
    print(f"    B2 transcript Bash calls naming a tracked script: {named} of {blocks} tool calls (A's script: {a_scr}; "
          f"difference {named - a_scr:+d}: B2 counts naming, A counts execution positions; B2's window is turns "
          f"ENDED in it, A's is steps stamped in it)")
    print(f"    B2x the same calls with a tracked script at an EXECUTION position (re-derived rule): {execd} "
          f"(A's script: {a_scr}; difference {execd - a_scr:+d}, same window caveat)")
    # the B2x − A difference, bucketed by turn: A's script rows of the SAME turns, whatever their stamp time
    a_turn = Counter(dict(conn.execute(r"""
        SELECT s.turn_id, count(*) FROM steps s JOIN turns t ON t.id = s.turn_id
        WHERE s.kind = 'tool' AND s.meta ? 'v' AND s.meta->>'registry_id' LIKE 'script:%%'
          AND t.ended_at >= %s AND t.ended_at < %s GROUP BY 1""", (since, until)).fetchall()))
    a_in = sum(1 for r in conn.execute(r"""
        SELECT 1 FROM steps s JOIN turns t ON t.id = s.turn_id
        WHERE s.kind = 'tool' AND s.meta ? 'v' AND s.meta->>'registry_id' LIKE 'script:%%'
          AND s.ts >= %s AND s.ts < %s AND NOT (t.ended_at >= %s AND t.ended_at < %s)""",
        (since, until, since, until)).fetchall())
    over = sum(max(0, per_turn[t] - a_turn[t]) for t in per_turn)
    under = sum(max(0, a_turn[t] - per_turn[t]) for t in a_turn)
    print(f"      by turn: A on the transcript turns' own rows = {sum(a_turn.values())} (A rows stamped in the window "
          f"whose turn ended outside it: {a_in}); per turn, B2x exceeds A by {over} and A exceeds B2x by {under} "
          f"(B2x's rule is coarser than toolreg's: a turn's excess is a call it reads as executing that toolreg "
          f"doesn't, or the reverse)")

    # (d) the residual
    if before is not None:
        bad = (None, "unknown")
        both = [(b, p) for b, p in zip(before, paired) if not econ._v2_core(p[0])]
        ub = [b for b, _ in both if b[2] in bad]
        moved = [p for b, p in both if b[2] in bad and p[2] not in bad]
        ua = [p for b, p in both if b[2] in bad and p[2] in bad]
        regress = [p for b, p in both if b[2] not in bad and p[2] in bad]
        print("\n(d) RESIDUAL (agent-authored domain, the same rows before and after):")
        print(f"    unresolved before {len(ub)} = moved {len(moved)} (resolved by S1's folds) + residual {len(ua)}"
              f" · resolved before and unresolved after: {len(regress)}")
        with conn.cursor() as cur:
            who = toolreg.authorship(cur, sorted({r[0] for r in ua} | {r[0] for r in regress}))
        cause, gone_memo = Counter(), {}
        for r in ua:
            sp = toolreg.source_path(r[0])
            if sp is None:
                cause["no source file (an MCP server whose args name no script)"] += 1
            elif not (who.get(r[0]) or {}).get("contributors"):
                tails = "|".join(re.escape(t) for t in [sp] + [k for k, v in toolreg._MOVED.items() if v == sp])
                gone = conn.execute("SELECT count(*) FROM steps WHERE kind = 'tool' AND NOT coalesce(meta ? 'edits', "
                                    "false) AND content ~ ('^(Write|Edit|MultiEdit|NotebookEdit): /\\S*/(' || %s || ')$')",
                                    (tails,)).fetchone()[0] if sp not in gone_memo else gone_memo[sp]
                gone_memo[sp] = gone
                cause["its Writes are recorded only at another checkout's path that no longer resolves"
                      if gone else "no Write or Edit of it in the ledger"] += 1
            else:
                cause["first recorded event is an Edit (the file predates the ledger)"] += 1
        for k, v in cause.most_common():
            print(f"      {v:6d}  {k}")
        top = Counter(r[0] for r in ua).most_common(8)
        print("    top residual ids: " + ", ".join(f"{rid} ×{n}" for rid, n in top))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
