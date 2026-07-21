#!/usr/bin/env python
"""ASTRYX identity scribe — the SOLE writer of the private agents/ repo (plan-2 §3).

The git analogue of the channel server: agents never commit identity directly; they
PROPOSE, the scribe validates (P), stamps authorship from its own invocation (not
self-asserted content), and appends. The one writer only ever appends — history is
linear by construction.

Usage (invoked by the channel server's self_edit tool, or by seed for owner acts):
    identity_commit.py <agent> <relpath> [--b64] [--owner] < content

P (the validator):
  - the target must live inside the proposing agent's OWN identity (its folder;
    a flat charter auto-migrates to folder form on first self-edit — the opt-in)
  - CORE is refused on the self path: machine lines (Model:/Grants:/Rank:/Heartbeat:)
    and CORE headings (## Law, ## Tombstone) must be byte-identical; changing them
    takes the amendment law (--owner, seed acting on Umair's authorization)
  - reserved names (.organ.md, README.md, anything .example*) are never charters
    and never self-writable
  - no path escapes, no deletes, no history rewrites — the scribe only adds

Trust boundary (stated, per §3): at single-uid this is detection-grade — an agent
with bash could write the repo directly. That act is visible (git author lies are
diffable against wire activity) and is a charter violation; prevention arrives with
the separate-uid follow-up (goal 4).
"""
import base64
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/umair/astryx")
AGENTS = ROOT / "agents"

CORE_LINE = re.compile(r"^(Model|Grants|Rank|Heartbeat):", re.M)
CORE_HEADINGS = ("## Law", "## Tombstone")
# CLAUDE.md is reserved: an agent's context loads a GENERATED CLAUDE.md (charter +
# local.md, rebuilt every spawn), so an agent writing "CLAUDE.md" thinks it is
# editing its self but produces an inert copy — the charter <name>.md is the self.
RESERVED = {".organ.md", "README.md", "CLAUDE.md"}


def die(msg: str) -> None:
    print(f"REFUSED: {msg}", file=sys.stderr)
    sys.exit(1)


def find_charter(agent: str) -> Path:
    hits = [p for p in AGENTS.rglob(f"{agent}.md")
            if not p.name.endswith(".example.md")
            and not any(part.endswith(".example") for part in p.relative_to(AGENTS).parts)]
    if not hits:
        die(f"no charter for '{agent}'")
    if len(hits) > 1:
        die(f"name collision for '{agent}': {[str(h) for h in hits]} — owner must resolve")
    return hits[0]


def core_fields(text: str) -> list[str]:
    """The CORE projection of a charter: machine lines + CORE-heading sections."""
    out = [m.group(0) + text[m.end():text.find('\n', m.end())]
           for m in CORE_LINE.finditer(text)]
    for h in CORE_HEADINGS:
        i = text.find(h)
        if i >= 0:
            j = text.find("\n## ", i + 1)
            out.append(text[i:j if j > 0 else len(text)].strip())
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 2:
        die("usage: identity_commit.py <agent> <relpath> [--b64] [--owner]")
    agent, relpath = args
    owner_act = "--owner" in flags

    raw = sys.stdin.buffer.read()
    content = base64.b64decode(raw) if "--b64" in flags else raw

    charter = find_charter(agent)
    # folder form is the self's home; flat charters migrate on first self-edit
    if charter.parent == AGENTS or charter.parent.name != agent:
        home = charter.parent / agent
        home.mkdir(exist_ok=True)
        subprocess.run(["git", "mv", charter.name if charter.parent == AGENTS
                        else str(charter.relative_to(AGENTS)),
                        str((home / charter.name).relative_to(AGENTS))],
                       cwd=AGENTS, check=True, capture_output=True)
        charter = home / charter.name
    home = charter.parent

    # Normalize the path an agent passes: agents address files RELATIVE TO THEIR OWN
    # HOME and should never need to know their coordinates in the tree. Strip any
    # leading spelling of that location ('agents/philosophers/p2/', 'philosophers/p2/',
    # or a bare duplicate 'p2/') so 'p2.md', its tree path, and its repo path all
    # resolve to the SAME file — a doubly-nested identity was possible before this.
    parts = [p for p in Path(relpath).parts if p not in (".", "")]
    if ".." in parts:
        die(f"path escapes {agent}'s own identity: {relpath}")
    home_parts = list(home.relative_to(AGENTS).parts)
    for prefix in (["agents"] + home_parts, home_parts, [agent]):
        if parts[:len(prefix)] == prefix:
            parts = parts[len(prefix):]
            break
    if not parts:
        die("path resolves to your folder itself, not a file")
    relpath = "/".join(parts)
    target = (home / relpath).resolve()
    if not str(target).startswith(str(home.resolve()) + "/"):
        die(f"path escapes {agent}'s own identity: {relpath}")
    if target.name in RESERVED or ".example" in target.name:
        die(f"reserved name: {target.name}")

    # P: CORE immutable on the self path
    if target == charter and not owner_act:
        old = charter.read_text()
        try:
            new = content.decode()
        except UnicodeDecodeError:
            die("charter must be text")
        if core_fields(old) != core_fields(new):
            die("CORE fields (Model/Grants/Rank/Heartbeat, ## Law, ## Tombstone) are "
                "owner-eternal — propose through steward; the amendment law commits them")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    rel = str(target.relative_to(AGENTS))
    author = "owner <owner@astryx.local>" if owner_act else f"{agent} <{agent}@astryx.local>"
    subprocess.run(["git", "add", rel], cwd=AGENTS, check=True, capture_output=True)
    r = subprocess.run(["git", "commit", "--author", author, "-m",
                        f"{'owner' if owner_act else agent}: {rel}"],
                       cwd=AGENTS, capture_output=True, text=True)
    if r.returncode != 0:
        if "nothing to commit" in r.stdout + r.stderr:
            print(f"no change: {rel} is already exactly that")
            return
        die(f"commit failed: {r.stderr.strip()[:200]}")
    print(f"committed: {rel} (author {author.split(' ')[0]})")

    # Ratified amendments must not ship silently (steward, 2026-07-22): every
    # owner-path charter commit lands one org-news line so "read org-news before
    # proposing" covers CORE law too — the dedup check has no blind spot.
    if owner_act and target.suffix == ".md":
        try:
            import psycopg
            dsn = next(l.split("=", 1)[1].strip()
                       for l in open(ROOT / ".env") if l.startswith("ASTRYX_DSN="))
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute(
                    "INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body) "
                    "VALUES ('seed','local','steward','local','org-news','milestone',%s)",
                    (f"org-news (auto, scribe) — charter amendment ratified via owner path: {rel}. "
                     f"Read the file for the diff before proposing anything in its territory.",))
        except Exception:
            pass  # the commit stands even if the announcement fails


if __name__ == "__main__":
    main()
