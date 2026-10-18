#!/usr/bin/env python3
"""Oracle for plan-11324 S3d, GROUP SCOPES (design #58435): groups derived from the agents/ tree, and their
influence views. agent → group → org → cog → federation; a group sits inside one org.

DB-FREE, all of it. charter.py is loaded from CHARTER_SRC and graph.py from INFLUENCE_SRC (mutation_probe's seams),
never by a bare import. Arms:
  THE TREE: a planted agents/ tree (nesting, a self-folder, a document beside a self-folder charter, a composite's
    README, an *.example dir and file, a directory with no charter) reads back as its known groups, members, direct
    members and parents; the self-folder is never a group; the CLI prints the same JSON.
  THE ONE RULE: the observatory's agent_meta reads group_path through charter.group_path, and holds no copy of the
    self-folder rule (the drift class: two copies of a tree rule).
  GROUP VIEWS: the closed form on a 3-node graph (teleport on the group, dangling mass back to it); the group view
    differs from GLOBAL where the closed forms say it must; an empty group refuses; group_views() reads exactly the
    ask() cache SQL, writes nothing, and keys every group charter.groups() gives.
  REACH UNCHANGED (a2 #58433 A, a3 #58434 Q2): group scope moves ATTENTION, never reach. read_message and
    query_thread still filter on exactly id / thread (bbeb901's premise pin, re-run here), and no read tool in
    channel/server.mjs names a group.
Exit 0 pass · 1 fail.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
CHARTER = Path(os.environ.get("CHARTER_SRC") or REPO / "src" / "astryx" / "core" / "charter.py")
GRAPH = Path(os.environ.get("INFLUENCE_SRC") or REPO / "src" / "astryx" / "influence" / "graph.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def plant(root: Path):
    files = {
        "solo.md": "# solo",
        "home/home.md": "# a self-folder agent",
        "home/onboard.md": "# a document beside a self-folder charter",
        "team/x/x.md": "# x",
        "team/y.md": "# y",
        "team/README.md": "# the composite's readme",
        "team/sub/z/z.md": "# z",
        "team/sub/w.md": "# w",
        "pair/p.md": "# p",
        "pair/q/q.md": "# q",
        "team.example/e.md": "# an example dir",
        "ex.example.md": "# an example file",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text + "\n")
    (root / "empty" / "deeper").mkdir(parents=True)


WANT = {
    "pair": {"name": "pair", "parent": None, "depth": 1, "members": ["p", "q"], "direct": ["p", "q"]},
    "team": {"name": "team", "parent": None, "depth": 1, "members": ["w", "x", "y", "z"], "direct": ["x", "y"]},
    "team/sub": {"name": "sub", "parent": "team", "depth": 2, "members": ["w", "z"], "direct": ["w", "z"]},
}


def tree(C):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "agents"
        plant(root)
        got = C.groups(root)
        check("tree: the planted agents/ reads back as exactly its groups (members, direct, parents, depth)",
              got == WANT, json.dumps(got))
        check("tree: a self-folder (home/home.md) is the agent's home, never a group", "home" not in got)
        check("tree: an *.example dir and a directory with no charter below it are not groups",
              not any(k.startswith(("team.example", "empty")) for k in got))
        gp = {p.stem: C.group_path(p, root) for p in C.charter_files(root)}
        check("tree: group_path for each charter (self-folder dropped, root = [])",
              gp == {"solo": [], "home": [], "x": ["team"], "y": ["team"], "z": ["team", "sub"],
                     "w": ["team", "sub"], "p": ["pair"], "q": ["pair"]}, json.dumps(gp, sort_keys=True))
        members = sorted({m for g in got.values() for m in g["members"]} | {"solo", "home"})
        check("tree: every grouped member is a roster name, and the roster is what the groups cover",
              members == C.roster(root), f"{members} vs {C.roster(root)}")
        # the CLI's JSON, for non-python readers
        out = subprocess.run([sys.executable, str(CHARTER), "--groups", str(root)], capture_output=True, text=True)
        try:
            cli = json.loads(out.stdout)
        except ValueError:
            cli = None
        check("tree: `charter.py --groups` prints the same groups as JSON", cli == WANT, (out.stdout + out.stderr)[-300:])


def one_rule():
    src = (REPO / "observatory" / "api" / "main.py").read_text()
    blk = re.search(r"\ndef agent_meta\(\).*?(?=\n@app\.|\ndef )", src, re.S)
    body = blk.group(0) if blk else ""
    check("one rule: observatory agent_meta reads group_path through charter.group_path",
          "_charter.group_path(f, root)" in body, body[-200:])
    check("one rule: agent_meta holds no copy of the self-folder rule",
          "parts[-2] == f.stem" not in body and "relative_to(root).parts" not in body)


def views(G):
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    e = [{"kind": "pass_land", "src": "A", "dst": "B", "ts": now - timedelta(hours=1)}]
    cov = {"pass_land": 1.0, "delegation": 1.0, "tool_call": 1.0}
    nodes = ["A", "B", "C"]
    sc = G.group_scores(e, cov, nodes, "g", ["A"], now)
    # teleport on A; B and C dangle, and their mass returns to the group (A): r_A = .15 + .85 r_B, r_B = .85 r_A
    ra = 0.15 / (1 - 0.85 * 0.85)
    check("views: the group view's closed form (r_A = .15/(1-.85²), r_B = .85 r_A, r_C = 0)",
          abs(sc["A"] - ra) < 1e-9 and abs(sc["B"] - 0.85 * ra) < 1e-9 and abs(sc["C"]) < 1e-12,
          json.dumps(sc))
    gl = G.scores(e, G.global_view(G.kind_weights(cov), nodes), nodes, now)
    check("views: GLOBAL over the same graph gives C mass (uniform teleport) and the group view gives it none",
          gl["C"] > 0.1 and sc["C"] < 1e-12, json.dumps(gl))
    sc2 = G.group_scores(e, cov, nodes, "g2", ["B", "C"], now)
    check("views: a group of {B, C} ranks A last (no walk from the group reaches A)",
          sc2["A"] < 1e-12 and sc2["B"] > 0 and sc2["C"] > 0, json.dumps(sc2))
    low = e + [{"kind": "delegation", "src": "A", "dst": "C", "ts": now - timedelta(hours=1)}]
    sc3 = G.group_scores(low, {"pass_land": 1.0, "delegation": 0.2, "tool_call": 1.0}, nodes, "g", ["A"], now)
    check("views: a kind under the coverage floor weighs 0 in a group view too (C, reached only by it, gets none)",
          sc3["C"] < 1e-12 and abs(sc3["A"] - ra) < 1e-9, json.dumps(sc3))
    v = G.group_view(G.kind_weights(cov), "team/sub", ["w", "z"])
    check("views: a group view is named group:<id> and teleports on its members only",
          v["name"] == "group:team/sub" and v["teleport"] == {"w": 1.0, "z": 1.0} and v["dangling"] == "teleport",
          json.dumps(v["teleport"]))
    try:
        G.group_view({}, "empty", [])
        check("views: an empty group refuses (no teleport mass)", False)
    except ValueError:
        check("views: an empty group refuses (no teleport mass)", True)


def shell_reads(C):
    from astryx.influence import shell

    class Conn:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append(sql)
            now = datetime.now(timezone.utc)
            rows = [("pass_land", "x", "y", now - timedelta(hours=2), None, "sha", "t", 1.0)]
            return type("R", (), {"fetchall": lambda s: rows, "fetchone": lambda s: rows[0]})()

    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "agents"
        plant(root)
        conn = Conn()
        got = shell.group_views(conn, agents_dir=root)
        check("shell: group_views reads exactly ask()'s cache SQL, once, and nothing else (no write, no new site)",
              conn.sql == [shell.CACHE_SQL], str(conn.sql))
        check("shell: group_views keys exactly the groups charter.groups() gives, with their members",
              {k: g["members"] for k, g in got.items()} == {k: g["members"] for k, g in WANT.items()},
              json.dumps({k: g["members"] for k, g in got.items()}))
        check("shell: in team's view the cached edge's target y outranks w, which nothing points at",
              got["team"]["scores"]["y"] > got["team"]["scores"]["w"], json.dumps(got["team"]["scores"]))


def reach():
    src = (REPO / "channel" / "server.mjs").read_text()

    def block(tool):
        b = re.search(rf"if \(name === '{tool}'\)(.*?)(?=\n  if \(name ===)", src, re.S)
        return b.group(1) if b else None

    def wheres(tool):
        b = block(tool)
        return re.findall(r"WHERE ([^`)]*?)(?=\s+ORDER\b|`|\))", b) if b else None
    check("reach: read_message filters on exactly `WHERE id=$1` (bbeb901's pin)", wheres("read_message") == ["id=$1"],
          str(wheres("read_message")))
    check("reach: query_thread filters on exactly `WHERE thread=$1` (bbeb901's pin)",
          wheres("query_thread") == ["thread=$1"], str(wheres("query_thread")))
    tools = ("read_message", "query_thread", "query_steps")
    named = [t for t in tools if block(t) is None or re.search(r"group|charter|agents/", block(t))]
    check("reach: no read tool (read_message, query_thread, query_steps) names a group, a charter or the tree",
          not named, str(named))


def main():
    print("S3d group scopes: tree, one rule, views, shell reads, reach")
    try:
        C = load(CHARTER, "charter_under_test")
        G = load(GRAPH, "influence_graph_under_test")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  the subjects load ({type(e).__name__}: {e})")
        return 1
    tree(C)
    one_rule()
    views(G)
    shell_reads(C)
    reach()
    print(f"{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
