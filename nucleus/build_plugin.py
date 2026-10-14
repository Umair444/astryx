#!/usr/bin/env python3
"""astryx · build the Claude Code plugin as a STANDALONE directory, ready to be its own git repo.

The repo is the one source of truth; the plugin repo (Umair444/astryx-plugin) is generated from it:
  plugin/                     -> the plugin's own files (manifest, skills, hooks, README), minus plugin/templates/
  LICENSE                     -> LICENSE
  channel/*.mjs               -> channel/*.mjs   (the wire server and its sibling modules, byte for byte)
  channel/package.json + lock -> package.json, package-lock.json at the plugin ROOT, where Claude Code installs
                                 the lockfile's packages at install time (node then resolves them from channel/)
  agents/seed/seed.md         -> agents/seed.md, behind plugin/templates/seed-agent.md, with onboard.md appended
  agents/seed/onboard.md      -> skills/onboard/onboard.md
  (generated)                 -> .claude-plugin/marketplace.json, so the repo is also its own marketplace

CLI: python nucleus/build_plugin.py [--out DIR]     (default dist/astryx-plugin; the dir is replaced)
     python nucleus/build_plugin.py --check DIR     exit 0 when DIR matches what a build would write, else 1 + diff
tests/test_build_plugin.py pins the copies to the repo (the drift test).
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "dist" / "astryx-plugin"
SKIP = {"templates", "__pycache__", ".DS_Store"}


def manifest(repo: Path = REPO) -> dict:
    return json.loads((repo / "plugin" / ".claude-plugin" / "plugin.json").read_text())


def marketplace(repo: Path = REPO) -> str:
    m = manifest(repo)
    return json.dumps({
        "name": "astryx",
        "owner": {"name": m["author"]["name"], "url": m["author"]["url"]},
        "metadata": {"description": "The ASTRYX plugin for Claude Code."},
        "plugins": [{"name": m["name"], "source": "./", "description": m["description"]}],
    }, indent=2) + "\n"


def seed_agent(repo: Path = REPO) -> str:
    head = (repo / "plugin" / "templates" / "seed-agent.md").read_text()
    seed = (repo / "agents" / "seed" / "seed.md").read_text()
    onboard = (repo / "agents" / "seed" / "onboard.md").read_text()
    return head + seed.rstrip("\n") + "\n\n---\n\n" + onboard.rstrip("\n") + "\n"


def files(repo: Path = REPO) -> dict[str, bytes]:
    """{relative path in the plugin: content} for everything a build writes."""
    out: dict[str, bytes] = {}
    src = repo / "plugin"
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_file() and not (set(rel.parts) & SKIP) and not p.name.endswith(".pyc"):
            out[rel.as_posix()] = p.read_bytes()
    out["LICENSE"] = (repo / "LICENSE").read_bytes()
    for p in sorted((repo / "channel").glob("*.mjs")):
        out[f"channel/{p.name}"] = p.read_bytes()
    out["package.json"] = (repo / "channel" / "package.json").read_bytes()
    out["package-lock.json"] = (repo / "channel" / "package-lock.json").read_bytes()
    out["agents/seed.md"] = seed_agent(repo).encode()
    out["skills/onboard/onboard.md"] = (repo / "agents" / "seed" / "onboard.md").read_bytes()
    out[".claude-plugin/marketplace.json"] = marketplace(repo).encode()
    return out


def build(out_dir: Path, repo: Path = REPO) -> dict[str, bytes]:
    want = files(repo)
    if out_dir.exists():
        keep_git = out_dir / ".git"
        for p in out_dir.iterdir():                 # replace everything but a .git (the plugin repo's history)
            if p == keep_git:
                continue
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    for rel, data in want.items():
        f = out_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        if rel.endswith((".py", ".sh")):
            f.chmod(0o755)
    return want


def check(out_dir: Path, repo: Path = REPO) -> list[str]:
    """What differs between `out_dir` and a fresh build: missing, changed and extra files."""
    want = files(repo)
    have = {p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(out_dir).parts
            and "node_modules" not in p.relative_to(out_dir).parts}
    probs = [f"missing {r}" for r in sorted(set(want) - have)]
    probs += [f"changed {r}" for r in sorted(set(want) & have) if (out_dir / r).read_bytes() != want[r]]
    probs += [f"extra {r}" for r in sorted(have - set(want))]
    return probs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the ASTRYX Claude Code plugin as a standalone directory.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", type=Path, metavar="DIR", help="compare DIR with a fresh build; write nothing")
    a = ap.parse_args(argv)
    if a.check:
        probs = check(a.check)
        for p in probs:
            print(p)
        print(f"{a.check}: " + ("matches the repo" if not probs else f"{len(probs)} difference(s)"))
        return 1 if probs else 0
    written = build(a.out)
    print(f"built {a.out} ({len(written)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
