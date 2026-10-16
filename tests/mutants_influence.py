"""Authored mutants for src/astryx/influence/graph.py (plan-11324 S2) — run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_influence.py

Each is an influence graph that would credit the wrong agent: an edge pointed backwards, a self-loop admitted, the
platform counted as an author, the routed loop left in, a join that lets unreviewed commits through, a PASS to the
lander credited, an outcome answering the wrong asker or several tasks, a request read as a verdict, a kind under
its coverage floor weighed, a read wider than the wire's own tools, a tool that names the asker or a dead agent.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "influence" / "graph.py"
ORACLE = REPO / "tests" / "test_influence.py"
ENV = "INFLUENCE_SRC"
TIMEOUT = 180

MUTANTS = {
    # direction, per live kind
    "D1 pass_land points reviewer → author":
        ('"src": author, "dst": reviewer', '"src": reviewer, "dst": author'),
    "D2 delegation points recipient → asker":
        ('"kind": "delegation", "src": t["from_agent"], "dst": t["to_agent"]',
         '"kind": "delegation", "src": t["to_agent"], "dst": t["from_agent"]'),
    "D3 tool_call points author → caller":
        ('"src": c["caller"], "dst": c["author"]', '"src": c["author"], "dst": c["caller"]'),
    # self-loops, per live kind
    "S1 pass_land admits a self-review": ("            if author == reviewer:", "            if False:"),
    "S2 delegation admits a self-task": ('            if t["from_agent"] == t["to_agent"]:', "            if False:"),
    "S3 tool_call admits self-use": ('        if c["caller"] == c["author"]:', "        if False:"),
    # tool calls
    "T1 core servers' calls counted": ("return bool(m) and m.group(1) in core_servers", "return False"),
    # the loop discount
    "L1 the loop discount needs a token the sender never sends": ("        if hit:", '        if hit and e.get("token"):'),
    # PageRank
    "P1 the dangling rule is inverted": ('(v[n] if dangling == "teleport" else u)', '(u if dangling == "teleport" else v[n])'),
    "P2 an edge AT now is used (not strictly before)": ('not e["ts"] < now', 'not e["ts"] <= now'),
    # the SHA join
    "J1 the ancestor rule admits a non-merge commit after the head": ("        if len(xps) < 2:", "        if False:"),
    "J2 the ancestor rule admits a merge of a non-main branch":
        ("        if not all(p in main_side for p in xps[1:]):", "        if False:"),
    "J3 an abbreviated head no longer resolves": ("hits = [s for s in parents if s.startswith(prefix)]",
                                                  "hits = [s for s in parents if s == prefix]"),
    "J4 a symbolic base is taken as resolved": ('base = g[2] if re.fullmatch(HEX, g[2]) else f"unresolved base: {g[2]}"',
                                                "base = g[2]"),
    "J5 a non-sha head reads as merely malformed": ('out.append({"error": "non-sha head" if',
                                                    'out.append({"error": "malformed marker" if'),
    "J6 every merge reachable from main lands, not only first-parent ones":
        ("for s in first_parent_chain(parents, tip)", "for s in commits"),
    # BC-A
    "A1 the author/owner-prefix cross-check is dropped": ("            if author != owner:", "            if False:"),
    # BC-D
    "B1 the outcome's to_agent condition is dropped":
        ('mine = [t for t in cands if t["from_agent"] == r["to_agent"]]', "mine = list(cands)"),
    "B2 one outcome answers every open task (one-to-one dropped)": ("for t in mine[-1:]:", "for t in mine:"),
    "B3 a task can be answered twice": ('            open_by[(r["thread"], r["from_agent"])].remove(t)', "            pass"),
    "B4 a review needs no verdict to be an outcome":
        ('return row["intent"] == "review" and bool(', 'return row["intent"] == "review" or bool('),
    "B5 pulse rows are edges": ("def is_pulse(row) -> bool:\n", "def is_pulse(row) -> bool:\n    return False\n"),
    "B6 the nodes rider is dropped for delegation":
        ('            if not (is_node(t["from_agent"], t["from_org"], roster) and is_node(t["to_agent"], t["to_org"], '
         'roster)):', "            if False:"),
    # R-1 delegation coverage
    "C3 a task answered only outside the grammar reads measured (unanswered = judged)":
        ("        if later:", "        if False:"),
    # R-2
    "L2 the loop discount is kind-gated again (delegation only)":
        ("hit = any(", 'hit = e["kind"] == "delegation" and any('),
    # compute's refusals
    "G1 compute writes over a 1-name roster": ("    if len(roster) < 2:", "    if False:"),
    "G2 compute replaces a non-empty cache with nothing": ("    if cache_nonempty and not edges:", "    if False:"),
    # coverage
    "C1 the coverage gate is removed":
        ("if k in HARD_UNMEASURED or coverages.get(k, 0.0) < COVERAGE_FLOOR:", "if k in HARD_UNMEASURED:"),
    "C2 a mostly-unmapped agent reads measured": ('verdict = "unmeasured" if un > 0.5 else "measured"',
                                                  'verdict = "measured"'),
    # BC-R
    "R1 the read takes one more column (delivery)": ('"thread", "intent", "body")', '"thread", "intent", "body", "delivery")'),
    # the tool
    "W1 the tool may return the asker": ("a != asker and ", ""),
    "W2 the tool ignores the liveness filter": ("sc[a] > 0 and live(a)", "sc[a] > 0"),
}
