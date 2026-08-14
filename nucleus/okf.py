#!/usr/bin/env python3
"""astryx · OKF frontmatter — the ONE reader/writer for the memory estate's metadata.

Open Knowledge Format v0.1 (Google Cloud, 2026-06-12) says a knowledge bundle IS "a
directory of markdown files with YAML frontmatter"; the file path is the identity, `type`
is the only required field, and the same file must be readable by a human and parseable
by an agent without a translation layer. `memory/` is already that directory in every
respect except the frontmatter. This adds it — ADDITIVELY. Not one byte below the closing
`---` changes, so the notation, the `[[links]]`, and the three lints that parse them are
untouched.

WHY THIS IS HAND-ROLLED AND NOT PyYAML — the strictness IS the lint.
A parser that accepts only `key: scalar`, `key: "quoted"`, `key: [a, b]`, comments and
blanks, and HARD-FAILS on tabs, indentation, nesting, anchors, duplicate keys, unknown
keys and over-long values, is the thing that keeps the block flat forever. A general YAML
loader would cheerfully accept an estate that grows nesting one page at a time, and by
then flatness can no longer be asserted. It also keeps this importable from the gitignored
triggers/ lints with zero install coupling. Third-party confirmation without a third-party
runtime, in the same idiom as the card verifier's rfc8785: nucleus/test_okf.py ALSO
cross-checks every parse against yaml.safe_load WHEN PyYAML happens to be importable.

THE TWO RULES THAT PROTECT THE EXISTING LINTS (both machine-checked below, because a
convention that is only written down is not a guarantee):

  1. NO FORBIDDEN KEY. A frontmatter field may never restate a fact the body already
     holds — `state`, `status`, `links`, `inbound`, `compiled-through`. The reason is the
     TWO-WRITER LAW and nothing else: memory spent compiles #11 and #12 discovering that
     goal state had two writers (goal-N.md and index.md) and drifted silently within
     hours; a `state:` key would make it three.

     CORRECTION (memory, msg 3822, verified 2026-08-13): this rule originally cited a
     second, more dramatic reason — that a `state:` key would SHADOW wiki_drift's
     first-match STATE_RE. That mechanism does not hold. STATE_RE is
     `state\s*·\s*([a-z-]+)`; `state: shipped` carries a colon, not a `·`, so it never
     matches and the body line is still the first hit. Probed and confirmed. Worse, the
     story was circular: the only way a frontmatter value COULD contain a `·` is if
     rule 2 did not exist, so rule 1's cited mechanism silently depended on rule 2.
     The rule stays — it was right — but a correct rule with a false reason is a
     liability, because the reason is exactly what a future reader audits when deciding
     whether the rule can be relaxed.
  2. NO `·` AND NO `[[` IN ANY VALUE. `·` (U+00B7) is the notation's field separator, so a
     value containing one could be read as a fact line by a naive body splitter. `[[`
     would be harvested by link_integrity's LINK_RE as a real edge from a metadata field.

Library:
    parse(text)      -> (meta: dict, body: str)   raises OKFError on any violation
    render(meta)     -> the `---` block, canonically ordered and deterministic
    attach(text, m)  -> a full file with frontmatter, body byte-identical
    validate(meta)   -> list[str] of problems (empty == conformant)
    strip(text)      -> body only; the identity every parser downstream relies on
"""
from __future__ import annotations

import re

MIDDOT = "·"
DELIM = "---"
MAX_VALUE = 200

# OKF v0.1 reserved names, exact spelling and semantics, so a generic OKF tool can read
# the bundle. `resource` is accepted but unused: astryx pages have no external URI.
OKF_FIELDS = ("type", "title", "description", "tags", "timestamp", "resource")

# astryx extensions, `x-` prefixed so they can never collide with a future OKF reserved
# name, and flat so the parser stays one level deep.
X_FIELDS = ("x-layer", "x-region", "x-dialect", "x-entity", "x-compile",
            "x-source", "x-visibility")

KNOWN = OKF_FIELDS + X_FIELDS
REQUIRED = ("type", "x-layer", "x-dialect")     # x-region is linted, not required: memory
                                                # declares regions on its own schedule.
LIST_FIELDS = frozenset({"tags", "x-source"})

# Keys that restate a body fact, or that another parser already owns. See rule 1 above.
FORBIDDEN = {
    "state":            "goal state lives in the body's `state ·` line; a second writer drifts "
                        "silently and would shadow wiki_drift's first-match STATE_RE",
    "status":           "same as `state` — one writer per fact",
    "links":            "the [[wikilinks]] in the body ARE the edges; link_integrity owns them",
    "inbound":          "derived from the graph, never stored",
    "compiled-through": "compile_lag + recon.sh both parse that marker out of index.md",
}

ENUMS = {
    # EXTENDED 2026-08-14 on memory's measured ruling. It found that `concept` was not
    # a type at all but four incompatible SLOT-USAGES under one word — a registry
    # enumerates members, a subject is one entity with many properties, a roster is
    # typed at the entity level, a law is prose that must never be split. Searching for
    # shared FIELDS found nothing; the real shape was structural. `mixed` exists so a
    # page can be honestly UNRULED rather than given a type nobody can defend.
    "type":         {"concept", "goal", "brief", "experiment", "schema", "index", "log",
                     "note", "registry", "subject", "roster", "law", "mixed"},
    "x-layer":      {"system1", "system2"},
    "x-dialect":    {"a", "b", "prose"},
    "x-visibility": {"public", "org"},
}

# Canonical emit order: OKF block first (so a generic reader sees what it knows at the
# top), astryx extensions after. Deterministic, so re-rendering an unchanged page is a
# no-op diff.
ORDER = KNOWN


class OKFError(ValueError):
    """A frontmatter block that violates the format. Always names the line."""


# YAML 1.1 auto-typing is the one place a hand-rolled reader and a real YAML reader can
# silently DISAGREE rather than one of them erroring: an unquoted `2026-08-12` is a
# datetime.date to PyYAML and a string to us, and `3` is an int to one and "3" to the
# other. Found by the cross-check arm in nucleus/test_okf.py on its first run — which is
# exactly what a conformance-to-SPEC check is for, as opposed to conformance-to-self.
# We emit strings, so render() QUOTES anything a YAML parser would coerce, and the bundle
# reads identically to us and to any generic OKF tool. Word-like values stay bare so the
# block still looks like OKF's own examples (`type: concept`, not `type: "concept"`).
_YAML_TYPED = frozenset({
    "true", "false", "yes", "no", "on", "off", "null", "none", "~", "",
})
_BARE_OK = re.compile(r"^[A-Za-z][A-Za-z0-9 _./#()+-]*$")


def _emit(s: str) -> str:
    """A scalar as it should appear in the block: bare when unambiguous, quoted when a
    YAML reader would otherwise give it a non-string type."""
    if s.lower() in _YAML_TYPED or not _BARE_OK.match(s) or s.strip() != s:
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _split(text: str):
    """(block_lines, body) — block_lines is None when the file has no frontmatter.

    A block exists only if line 1 is exactly `---`. That is deliberate: a `---` horizontal
    rule anywhere later in a markdown body must never be mistaken for a frontmatter fence.
    """
    if not text.startswith(DELIM + "\n") and text.rstrip("\n") != DELIM:
        return None, text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == DELIM:
            return lines[1:i], "\n".join(lines[i + 1:])
    raise OKFError("frontmatter opened with `---` but never closed")


def _scalar(raw: str, key: str, lineno: int):
    """One value. Lists are `[a, b]`; everything else is a string (quoted or bare)."""
    v = raw.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        items = [] if not inner else [x.strip().strip('"').strip("'") for x in inner.split(",")]
        if any(not x for x in items):
            raise OKFError(f"line {lineno}: `{key}` has an empty list item")
        return items
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse(text: str) -> tuple[dict, str]:
    """(meta, body). meta is {} when the file has no frontmatter — that is legal and is
    how every page looks before the migration. Raises OKFError on a malformed block."""
    block, body = _split(text)
    if block is None:
        return {}, body

    meta: dict = {}
    for n, line in enumerate(block, start=2):        # line 1 is the opening `---`
        if "\t" in line:
            raise OKFError(f"line {n}: tab character — frontmatter is space-only")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            raise OKFError(f"line {n}: indented — frontmatter is FLAT, no nested maps or "
                           f"list blocks (use `key: [a, b]`)")
        if ":" not in line:
            raise OKFError(f"line {n}: not `key: value` — got {line!r}")
        key, raw = line.split(":", 1)
        key = key.strip()
        if key in meta:
            raise OKFError(f"line {n}: duplicate key `{key}`")
        if key in FORBIDDEN:
            raise OKFError(f"line {n}: `{key}` is FORBIDDEN — {FORBIDDEN[key]}")
        if key not in KNOWN:
            raise OKFError(f"line {n}: unknown key `{key}` (known: {', '.join(KNOWN)})")
        val = _scalar(raw, key, n)
        for piece in (val if isinstance(val, list) else [val]):
            s = str(piece)
            if MIDDOT in s:
                raise OKFError(f"line {n}: `{key}` contains `{MIDDOT}` — that is the notation's "
                               f"field separator and must never appear in metadata")
            if "[[" in s:
                raise OKFError(f"line {n}: `{key}` contains `[[` — link_integrity would harvest "
                               f"it as a real graph edge")
            if len(s) > MAX_VALUE:
                raise OKFError(f"line {n}: `{key}` is {len(s)} chars (max {MAX_VALUE}) — "
                               f"frontmatter is metadata, prose belongs in the body")
        meta[key] = val
    return meta, body


def validate(meta: dict) -> list[str]:
    """Problems with an already-parsed block. Empty list == conformant. Separate from
    parse() so a caller can report every problem at once instead of the first."""
    out = []
    if not meta:
        return ["no frontmatter block"]
    for k in REQUIRED:
        if k not in meta:
            out.append(f"missing required field `{k}`")
    for k, allowed in ENUMS.items():
        v = meta.get(k)
        if v is not None and v not in allowed:
            out.append(f"`{k}` is {v!r}, must be one of {sorted(allowed)}")
    for k in LIST_FIELDS:
        if k in meta and not isinstance(meta[k], list):
            out.append(f"`{k}` must be a list — write `{k}: [a, b]`")
    if meta.get("x-dialect") == "b" and not meta.get("x-entity"):
        out.append("`x-dialect: b` hoists the entity to the title, so `x-entity` is required")
    return out


def render(meta: dict) -> str:
    """The `---` block, canonically ordered. Deterministic: same dict in, same bytes out,
    so re-running the migration on an unchanged page produces an empty diff."""
    problems = [f"line ?: `{k}` is FORBIDDEN — {FORBIDDEN[k]}" for k in meta if k in FORBIDDEN]
    if problems:
        raise OKFError("; ".join(problems))
    unknown = [k for k in meta if k not in KNOWN]
    if unknown:
        raise OKFError(f"unknown key(s): {', '.join(sorted(unknown))}")

    lines = [DELIM]
    for k in ORDER:
        if k not in meta:
            continue
        v = meta[k]
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(_emit(str(x)) for x in v)}]")
        else:
            lines.append(f"{k}: {_emit(str(v))}")
    lines.append(DELIM)
    return "\n".join(lines) + "\n"


def strip(text: str) -> str:
    """Body only. THE identity every downstream parser depends on: for any file,
    strip(attach(body, meta)) == body, byte for byte."""
    _, body = _split(text)
    return body


def attach(text: str, meta: dict) -> str:
    """A full file with frontmatter. Replaces an existing block; never touches the body.

    The additivity guarantee lives here and is asserted by nucleus/test_okf.py against
    every real page in the estate: the bytes below the closing `---` are unchanged.
    """
    return render(meta) + strip(text)


if __name__ == "__main__":                                   # tiny CLI for inspection
    import json
    import sys
    if len(sys.argv) != 2:
        print("usage: okf.py <file.md>", file=sys.stderr)
        sys.exit(2)
    try:
        m, b = parse(open(sys.argv[1]).read())
    except OKFError as e:
        print(f"OKF ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(m, indent=2))
    for p in validate(m):
        print(f"  problem: {p}", file=sys.stderr)
