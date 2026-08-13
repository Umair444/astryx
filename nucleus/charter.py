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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: charter.py <name>", file=sys.stderr)
        sys.exit(2)
    try:
        path = resolve(sys.argv[1])
    except Collision as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    if path is None:
        print(f"no charter for '{sys.argv[1]}' under agents/", file=sys.stderr)
        sys.exit(1)
    print(path)
