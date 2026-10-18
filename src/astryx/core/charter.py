#!/usr/bin/env python3
"""astryx · the ONE charter resolver (plan-17, item d).

A charter is agents/<name>.md at ANY depth: a self-form agent is
agents/<name>/<name>.md, a member lives inside its composite dir (nesting
allowed). The filename stem is the canonical name and a GLOBAL key — a duplicated
stem is a corrupted registry (the two-seed class) that must be resolved in the
tree, not raced past. Examples and .git are never charters.

This is the SINGLE source of that rule. spawn.sh, the observatory, and init.sh's
runner gate all resolve THROUGH here, so the collision guard and the exclusion
set can never drift between a shell copy and a python copy — they had: the
observatory silently took the first match on a duplicated stem while spawn.sh
refused (plan-17 build-confirm).

Library:  resolve(name) -> Path | None      (raises Collision on a dup stem)
          roster() -> list[str]             (every real charter name, any depth)
          groups() -> {id: {...}}           (the org's groups, derived from the tree: S3d)
CLI:      python src/astryx/core/charter.py NAME     prints the path, or errors nonzero.
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402
import sys
from pathlib import Path

AGENTS = paths.estate(__file__) / "agents"     # the org's roster (plan-11324 S3a: its HOME's agents/)

# ── AGENT TYPES ──────────────────────────────────────────────────────────────────────
# The org has more than one KIND of agent. The type is declared by a `Type:` directive
# line in the charter (sits with Model:/Rank:/Heartbeat:/Grants:), and this module is the
# ONE place that reads it — spawn.sh, station.py and the observatory all resolve through
# here, so the taxonomy can never drift between a shell copy and a python copy.
#
#   resident   the citizen: persistent, embodied (tmux), on the wire, remembers, initiates.
#              The DEFAULT — an un-typed charter is a resident, so the whole existing tree
#              keeps its meaning with no edit.
#   stationed  the API worker: stateless `claude -p` per request, no body, no wire, no
#              memory, tools off by default. Invoked via src/astryx/core/station.py, never spawned.
#   worker     RESERVED — ephemeral but stateful for one bounded job, then dies.
#   envoy      RESERVED — this org's face to a peer org across federation.
TYPES = ("resident", "stationed", "worker", "envoy")
DEFAULT_TYPE = "resident"


class Collision(Exception):
    """A duplicated stem — a corrupted registry; resolve it in the tree."""


def _is_example(p: Path, agents_dir: Path) -> bool:
    rel = p.relative_to(agents_dir)
    return p.name.endswith(".example.md") or any(
        part.endswith(".example") for part in rel.parts)


NON_CHARTERS = (".organ.md", "README.md")


def is_charter(p: Path, agents_dir: Path = AGENTS) -> bool:
    """Is this .md an AGENT? The one rule, structural rather than a list of names:
    examples, .git and a composite's structural files are not; and a SELF-FOLDER
    (agents/<x>/<x>.md) is that agent's home, so any OTHER .md beside its charter is a
    document the agent keeps (seed's onboard.md), never a second agent. A hardcoded
    filename list worked for one file and spawned a phantom 'onboard' everywhere else."""
    if ".git" in p.parts or _is_example(p, agents_dir) or p.name in NON_CHARTERS:
        return False
    d = p.parent
    if d != agents_dir and p.stem != d.name and (d / f"{d.name}.md").is_file():
        return False
    return True


def charter_files(agents_dir: Path = AGENTS) -> list[Path]:
    return sorted(p for p in agents_dir.rglob("*.md") if is_charter(p, agents_dir))


def roster(agents_dir: Path = AGENTS) -> list[str]:
    """Every real agent name in the tree, at any depth — the ONE roster derivation.

    Same exclusion rule as resolve() (examples, .git) plus the structural files a
    directory-composite carries (.organ.md, README.md), which are not charters.
    Derive-at-use: callers that need "who is in this org" must read the tree here
    rather than keep a list, because a hardcoded roster silently goes wrong the
    moment an agent is created, retired, or moved between composites.
    """
    return sorted(p.stem for p in charter_files(agents_dir))


# ── GROUPS (plan-11324 S3d, design #58435) ───────────────────────────────────────────
# agent → group → org → cog → federation. A GROUP is a directory of agents/ that holds at least one charter
# below it, and it is DERIVED here at read time, never stored (a1 #58431 §3: the tree is the one authority, so an
# agent that moves takes its history with it). A self-folder (agents/<x>/<x>.md) is that agent's home, not a group.
# A group scopes ATTENTION only (influence views, routing, the floor's zones), never reach: no read tool filters on
# it (a2 #58433 A, a3 #58434 Q2).

def group_path(charter_path: Path, agents_dir: Path = AGENTS) -> list[str]:
    """The chain of groups from the agents/ root down to this charter's own group: [outer, ..., inner], [] at the
    root. The ONE rule the observatory's zones and the influence group views both read."""
    parts = charter_path.relative_to(agents_dir).parts
    if len(parts) >= 2 and parts[-2] == charter_path.stem:     # self-folder: the agent's home drops out
        parts = parts[:-1]
    return list(parts[:-1])


def groups(agents_dir: Path = AGENTS) -> dict[str, dict]:
    """{group id: {"name", "parent", "depth", "members", "direct"}} for every group in the tree.
    id is the slash path from agents/ ("abstractors", "a/b"); parent is the enclosing group's id or None (the org);
    members is every agent at any depth below it, direct the ones whose innermost group it is. Sorted, so equal
    trees give equal answers. A directory with no charter below it is not a group."""
    out: dict[str, dict] = {}
    for p in charter_files(agents_dir):
        chain = group_path(p, agents_dir)
        for i in range(len(chain)):
            gid = "/".join(chain[:i + 1])
            g = out.setdefault(gid, {"name": chain[i], "parent": "/".join(chain[:i]) or None, "depth": i + 1,
                                     "members": [], "direct": []})
            g["members"].append(p.stem)
            if i == len(chain) - 1:
                g["direct"].append(p.stem)
    for g in out.values():
        g["members"].sort()
        g["direct"].sort()
    return dict(sorted(out.items()))


def resolve(name: str, agents_dir: Path = AGENTS) -> Path | None:
    """The charter for `name`, or None if absent. Raises Collision on a
    duplicated stem. Same rule everywhere: any depth, examples/.git excluded,
    the name sanitised so it can never escape the tree."""
    safe = "".join(c for c in name if c.isalnum() or c in "-_").lower()
    if not safe:
        return None
    hits = [p for p in agents_dir.rglob(f"{safe}.md") if is_charter(p, agents_dir)]
    if len(hits) > 1:
        raise Collision(
            f"REGISTRY COLLISION: '{name}' has {len(hits)} charters:\n"
            + "\n".join(str(h) for h in sorted(hits)))
    return hits[0] if hits else None


def agent_type(name: str, agents_dir: Path = AGENTS) -> str | None:
    """The agent's TYPE, read from its charter's `Type:` line. Returns DEFAULT_TYPE
    (resident) for a charter with no line, or None if the agent has no charter at all —
    'unknown type' and 'absent' are different answers and must not collapse. An
    unrecognised value degrades to resident (the safe, embodied default), never crashes."""
    p = resolve(name, agents_dir)
    if p is None:
        return None
    for line in p.read_text().splitlines():
        if line.startswith("Type:"):
            t = line.split(":", 1)[1].strip().lower()
            return t if t in TYPES else DEFAULT_TYPE
    return DEFAULT_TYPE


def typed_roster(agents_dir: Path = AGENTS) -> list[dict]:
    """[{name, type}, ...] for the whole tree — the roster the observatory renders."""
    return [{"name": n, "type": agent_type(n, agents_dir)} for n in roster(agents_dir)]


def roster_of_type(kind: str, agents_dir: Path = AGENTS) -> list[str]:
    """Names of one type only. `roster_of_type('resident')` is the set that gets a body,
    a heartbeat, and a vote — the thing most callers that today say roster() actually mean,
    now that a stationed agent is in the tree but is NOT an embodied wire citizen."""
    return [n for n in roster(agents_dir) if agent_type(n, agents_dir) == kind]


if __name__ == "__main__":
    if sys.argv[1:] == ["--roster"]:                 # for shell callers (spawn-all.sh)
        print("\n".join(roster())); sys.exit(0)
    if sys.argv[1:] == ["--groups"]:                 # the org's groups as JSON (S3d), for any non-python reader
        import json
        print(json.dumps(groups(), indent=1)); sys.exit(0)
    if len(sys.argv) not in (2, 3):
        print("usage: charter.py <name> [--type]", file=sys.stderr)
        sys.exit(2)
    if len(sys.argv) == 3 and sys.argv[2] == "--type":
        try:
            t = agent_type(sys.argv[1])
        except Collision as exc:
            print(exc, file=sys.stderr); sys.exit(1)
        if t is None:
            print(f"no charter for '{sys.argv[1]}' under agents/", file=sys.stderr); sys.exit(1)
        print(t); sys.exit(0)
    try:
        path = resolve(sys.argv[1])
    except Collision as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    if path is None:
        print(f"no charter for '{sys.argv[1]}' under agents/", file=sys.stderr)
        sys.exit(1)
    print(path)
