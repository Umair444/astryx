#!/usr/bin/env python3
"""Is a LOCAL wire name addressable? The one answer `send` asks before it writes a row (seed #37905).

WHY: `send` used to INSERT whatever `to` it was given and return ok. A row to a name nothing consumes
never moves: no process delivers it, and the sender walks away believing it was sent. On 2026-10-09
two residents addressed the nickname "a3" (memory #35146, steward #36565); each sat unread for hours
until outbound_stuck caught it. 60 days of the wire show the same class: dc:<id> (colon, not dash) x4,
the retired quasar and nexus. A refusal at write time turns hours of silence into an error in the
sender's own turn, with the canonical name beside it. outbound_stuck stays the backstop for rows
written by other paths (the pulse, bridges, hand SQL).

WHAT IS ADDRESSABLE (to_org = local):
  - a charter in the agents/ tree (charter.roster(), read at CALL time, never cached: a charter
    spawned mid-session is addressable on its next send, without restarting anyone's ear);
  - a SURFACE: a name some bridge's consumer predicate actually delivers. Each class below names
    its consumer, and tests/test_send_address.py reads those consumer files and fails if a class
    has no consumer saying so, or a consumer delivers a class this list does not admit.
A name with '@<org>' for a non-local org is not judged here: the gateway owns federation, and it
re-addresses the RESERVED_ORGS surfaces (orgname.py) itself.
BOUNDARY: a surface is admitted by SHAPE (wa-<anything>), so a mistyped chat id still passes and sits
pending; only the bridges know which ids route. Its detection is outbound_stuck (the pending-age watcher).

CLI: address.py <to>  → exit 0 (addressable, prints "ok") · exit 2 (refused, prints the reason)
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402

import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(repo_root(__file__)))
from astryx.core import charter, orgname  # noqa: E402

# (class, pattern, consumer file, the to_agent predicate that consumer runs)
SURFACES = (
    ("owner",       re.compile(r"^owner$"),                 "bridges/whatsapp.py", "to_agent='owner'"),
    ("whatsapp",    re.compile(r"^wa-[^\s@]+$"),            "bridges/whatsapp.py", "to_agent LIKE 'wa-%'"),
    ("telegram",    re.compile(r"^tg-[^\s@]+$"),            "bridges/telegram.py", "to_agent LIKE 'tg-%'"),
    ("discord",     re.compile(r"^dc-[^\s@]+$"),            "bridges/discord.py",  "to_agent LIKE 'dc-%'"),
    ("canvas user", re.compile(r"^cv-[^\s@]+$"),            "bridges/canvas.py",   "to_agent LIKE 'cv-%'"),
    ("canvas page", re.compile(r"^canvas-\d+$"),            "bridges/canvas.py",   "to_agent LIKE 'canvas-%'"),
    ("room",        re.compile(r"^room$"),                  "observatory/api/room.py", "to_agent='room'"),
)


def surface_of(name: str) -> str | None:
    return next((cls for cls, rx, _, _ in SURFACES if rx.match(name)), None)


def suggest(name: str, roster: list[str]) -> list[str]:
    """Canonical names the sender probably meant. A nickname keeps the first letter and the trailing
    number ("a3" → abstractor-3); a typo is close by edit distance ("stewrd" → steward)."""
    low = name.strip().lower()
    out = []
    s = re.match(r"^(wa|tg|dc|cv|canvas)[:_.](.+)$", low)   # a surface spelled with the wrong separator
    if s and surface_of(f"{s.group(1)}-{s.group(2)}"):
        out.append(f"{s.group(1)}-{s.group(2)}")
    m = re.match(r"^([a-z]+)-?(\d+)$", low)
    if m:
        out += [n for n in roster if n.startswith(m.group(1)) and re.search(rf"\D{m.group(2)}$", n)]
    out += [n for n in difflib.get_close_matches(low, roster, n=3, cutoff=0.6) if n not in out]
    return out[:3]


def check(to: str, agents_dir: Path = charter.AGENTS) -> tuple[bool, str]:
    """(addressable, message). Never raises on a bad name; a broken agents/ tree raises (the caller decides)."""
    # NEVER normalize here (a3 #38028 A1): the value judged must be byte-identical to the to_agent that is
    # WRITTEN. A strip made "seed " pass while server.mjs inserted 'seed ', which no consumer reads. No
    # roster name or surface class contains whitespace, so " seed" is simply refused, suggesting seed.
    name, at, org = str(to).partition("@")
    if at and org != "local":
        # the ORG half is written raw too (a3 #38032): "seed@" writes to_org '', "seed@local " writes
        # 'local ' — neither is local, and no peer can hold that name, so it is a dead letter in federation.
        if not orgname.ORG_RE.match(org):
            return False, (f"no such org '{org}': an org name matches {orgname.ORG_RE.pattern} (no spaces, "
                           f"not empty). For a local resident drop the '@'. Nothing was sent.")
        return True, "ok"                                   # a well-formed peer: the gateway's to judge
    if not name:
        return False, "empty recipient"
    roster = charter.roster(agents_dir)
    if name in roster or surface_of(name):
        return True, "ok"
    hint = suggest(name, roster)
    hint = f", did you mean {' or '.join(hint)}?" if hint else "."
    return False, (f"no such resident '{name}'{hint} Nothing consumes that name, so the row would sit "
                   f"pending forever; nothing was sent. A resident is a charter's filename stem in agents/.")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: address.py <to>", file=sys.stderr)
        return 64
    ok, msg = check(argv[1])
    print(msg)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
