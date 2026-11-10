"""Authored mutants for src/astryx/influence/graph.py's GROUP VIEW (plan-11324 S3d), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_groups_graph.py

Each is a group view that would rank the wrong agents: the GLOBAL teleport kept, dangling mass sent everywhere, the
coverage gate skipped, an empty group ranked anyway. The S2 graph's own mutants stay in tests/mutants_influence.py.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "influence" / "graph.py"
ORACLE = REPO / "tests" / "test_groups.py"
ENV = "INFLUENCE_SRC"
TIMEOUT = 60

MUTANTS = {
    "V1 the group view teleports on every node (GLOBAL's vector)":
        ("    return scores(edges, group_view(kind_weights(coverages), group_id, members), nodes, now)",
         "    return scores(edges, group_view(kind_weights(coverages), group_id, nodes), nodes, now)"),
    "V2 dangling mass returns uniformly, not to the group":
        ("    return view(f\"group:{group_id}\", weights, {a: 1.0 for a in members})",
         "    return view(f\"group:{group_id}\", weights, {a: 1.0 for a in members}, dangling=\"uniform\")"),
    "V3 the coverage gate is skipped (raw coverages used as weights)":
        ("    return scores(edges, group_view(kind_weights(coverages), group_id, members), nodes, now)",
         "    return scores(edges, group_view(dict(coverages), group_id, members), nodes, now)"),
    "V4 an empty group is ranked anyway (no refusal)":
        ("    if not members:\n        raise ValueError(f\"group {group_id!r} has no members: a view needs teleport mass\")\n", ""),
    "V5 the view is named like GLOBAL":
        ("view(f\"group:{group_id}\", weights,", "view(\"global\", weights,"),
    "V6 a group no edge touches reads as measured (pure teleport passed off as evidence, a3 #60189)":
        ("    return any(s in m or t in m\n", "    return True or any(s in m or t in m\n"),
    "V7 only an edge's src counts as touching the group":
        ("    return any(s in m or t in m\n", "    return any(s in m\n"),
    "V8 the weight test dropped: a coverage-gated or future edge counts as measured (a3 #60194)":
        ("               for s, t, _ in weighted(edges, group_view(kind_weights(coverages), group_id, members), now))",
         "               for s, t in ((e[\"src\"], e[\"dst\"]) for e in edges))"),
}
