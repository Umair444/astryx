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
CLI:      python nucleus/charter.py NAME     prints the path, or errors nonzero.
"""
import sys
from pathlib import Path

AGENTS = Path(__file__).resolve().parent.parent / "agents"

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
#              memory, tools off by default. Invoked via nucleus/station.py, never spawned.
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


def roster(agents_dir: Path = AGENTS) -> list[str]:
    """Every real agent name in the tree, at any depth — the ONE roster derivation.

    Same exclusion rule as resolve() (examples, .git) plus the structural files a
    directory-composite carries (.organ.md, README.md), which are not charters.
    Derive-at-use: callers that need "who is in this org" must read the tree here
    rather than keep a list, because a hardcoded roster silently goes wrong the
    moment an agent is created, retired, or moved between composites.
    """
    return sorted(p.stem for p in agents_dir.rglob("*.md")
                  if ".git" not in p.parts and not _is_example(p, agents_dir)
                  and p.name not in NON_CHARTERS)


def resolve(name: str, agents_dir: Path = AGENTS) -> Path | None:
    """The charter for `name`, or None if absent. Raises Collision on a
    duplicated stem. Same rule everywhere: any depth, examples/.git excluded,
    the name sanitised so it can never escape the tree."""
    safe = "".join(c for c in name if c.isalnum() or c in "-_").lower()
    if not safe:
        return None
    hits = [p for p in agents_dir.rglob(f"{safe}.md")
            if ".git" not in p.parts and not _is_example(p, agents_dir)]
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
