#!/usr/bin/env python3
"""Oracle: one identity per person (identity-channels P1, owner 11-15; homes/seed/identity-channels/DESIGN.md).
On the fixture database (this tree's schema.sql):
  I1 THE ONE MINTER identity_who: an unlinked sender keeps its bridge's name and is recorded as a stranger's handle;
     the owner's own account answers `owner`; a linked account answers its person's name; a web account's first sight
     is its person
  I2 link(): attaches an account, never moves one silently between people; import_owner turns every account a route
     TRUSTED into a handle of `owner`, once (a second run changes nothing)
  I3 A LINKED PERSON IS ANSWERED WHERE THEY WROTE: a reply to cv-faran.2 on a wa: thread is WhatsApp's to deliver, not
     the canvas bridge's; a cv- row on cv: or with no thread stays canvas's; an agent-to-agent row on a wa: thread is
     no bridge's
  I4 the bridges mint only through identity_of and read no trusted_* list any more
Exit 0 · 1 · 77 (no database)."""
import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_identity", REPO, deps=("psycopg",), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from astryx.core import address, identity  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


import psycopg  # noqa: E402

with fixture_db() as d, psycopg.connect(d["url"], autocommit=True) as c:
    who = lambda ch, acct, fb: c.execute("SELECT identity_who(%s, %s, %s)", (ch, acct, fb)).fetchone()[0]  # noqa: E731
    print("I1 THE ONE MINTER")
    arm("an unlinked sender keeps its bridge's name", who("whatsapp", "923000000001@s.whatsapp.net", "wa-923000000001") == "wa-923000000001")
    arm("…and is recorded as a stranger's handle (no identity)", c.execute(
        "SELECT identity_id FROM identity_handle WHERE channel='whatsapp' AND account='923000000001@s.whatsapp.net'").fetchone() == (None,))
    arm("a web account's first sight is its person", who("web", "2@cog", "cv-faran.2") == "cv-faran.2"
        and c.execute("SELECT count(*) FROM identity WHERE wire_name='cv-faran.2'").fetchone()[0] == 1)

    print("\nI2 LINK")
    identity.link(c, "cv-faran.2", "whatsapp", "923000000001@s.whatsapp.net")
    arm("a linked account answers its person's name", who("whatsapp", "923000000001@s.whatsapp.net", "wa-923000000001") == "cv-faran.2")
    try:
        identity.link(c, "cv-other.3", "whatsapp", "923000000001@s.whatsapp.net")
        moved = True
    except ValueError:
        moved = False
    arm("an account linked to one person is never moved to another silently", not moved
        and who("whatsapp", "923000000001@s.whatsapp.net", "x") == "cv-faran.2")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "bridges").mkdir()
        (Path(td) / "bridges" / "routes-whatsapp.json").write_text(json.dumps(
            [{"chat": "1@g.us", "agent": "seed", "enabled": True, "trusted_jids": ["923000000009@s.whatsapp.net"]}]))
        (Path(td) / "bridges" / "routes-telegram.json").write_text(json.dumps(
            [{"chat": "55", "agent": "seed", "enabled": True, "trusted_ids": [4242]}]))
        n1 = identity.import_owner(c, Path(td))
        n2 = identity.import_owner(c, Path(td))
    arm("import_owner: every trusted account is the owner's", n1 == 2 and who("whatsapp", "923000000009@s.whatsapp.net", "wa-x") == "owner"
        and who("telegram", "4242", "tg-4242") == "owner", n1)
    arm("…once: a second run changes nothing", n2 == 2 and c.execute("SELECT count(*) FROM identity WHERE wire_name='owner'").fetchone()[0] == 1)

    print("\nI3 ANSWERED WHERE THEY WROTE")
    wa = f"(to_agent='owner' OR to_agent LIKE 'wa-%' OR {address.reaches_sql('whatsapp')})"
    import importlib
    canvas_where = re.search(r"WHERE status='pending' AND to_org='local' AND \((.*)\)\n  ORDER BY", importlib.import_module("bridges.canvas").CLAIM, re.S).group(1)

    def claims(pred, to, thread):
        return c.execute(f"SELECT {pred.replace('%', '%%')} FROM (SELECT %s::text AS to_agent, %s::text AS thread) m", (to, thread)).fetchone()[0] is True
    rows = [("cv-faran.2", "wa:923000000001@s.whatsapp.net", True, False), ("cv-faran.2", "cv:x", False, True),
            ("cv-faran.2", None, False, True), ("lending", "wa:1@g.us", False, False), ("wa-92300", "wa:1@g.us", True, False),
            ("owner", "obs:seed", True, False)]
    got = [(t, th, claims(wa, t, th), claims(canvas_where, t, th)) for t, th, _, _ in rows]
    arm("whatsapp / canvas claim exactly as a person's channel says", got == rows, [g for g, r in zip(got, rows) if g != r])

print("\nI4 THE BRIDGES")
for b in ("whatsapp", "telegram", "discord"):
    src = (REPO / "bridges" / f"{b}.py").read_text()
    arm(f"{b}: mints through identity_of, reads no trusted list", "identity_of(pool" in src
        and not re.search(r"route\.get\(\"trusted_(jids|ids)\"", src))

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: one identity per person")
sys.exit(1 if fails else 0)
