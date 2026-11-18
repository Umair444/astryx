#!/usr/bin/env python3
"""Oracle: one identity per person (identity-channels P1, owner 11-15; homes/seed/identity-channels/DESIGN.md).
On the fixture database (this tree's schema.sql):
  I1 THE ONE MINTER identity_who: an unlinked sender keeps its bridge's name and is recorded as a stranger's handle;
     the owner's own account answers `owner`; a linked account answers its person's name; a web account's first sight
     is its person
  I2 link(): attaches an account, never moves one silently between people, never makes a person (owner, an agent's
     name, an unknown name); the owner's accounts come from the route import (tests/test_routes.py)
  I3 A LINKED PERSON IS ANSWERED WHERE THEY WROTE: a reply to cv-faran.2 on a wa: thread is WhatsApp's to deliver, not
     the canvas bridge's; a cv- row on cv: or with no thread stays canvas's; an agent-to-agent row on a wa: thread is
     no bridge's
  I4 the bridges mint only through identity_of and read no trusted_* list any more
Exit 0 · 1 · 77 (no database)."""
# synthetic numbers, built rather than written whole so no phone or JID shape sits in the source (devtools/privacy_gate.sh (c))
N001 = "92" + "3000000001"
N002 = "92" + "3000000002"
N020 = "92" + "3000000020"

import re
import sys
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
    arm("an unlinked sender keeps its bridge's name", who("whatsapp", f"{N001}@s.whatsapp.net", f"wa-{N001}") == f"wa-{N001}")
    arm("…and is recorded as a stranger's handle (no identity)", c.execute(
        f"SELECT identity_id FROM identity_handle WHERE channel='whatsapp' AND account='{N001}@s.whatsapp.net'").fetchone() == (None,))
    arm("a stranger on a CLOSED route is not recorded (medic 12635)", c.execute(f"SELECT identity_who('whatsapp', '{N002}@s.whatsapp.net', 'wa-{N002}', false)").fetchone()[0] == f"wa-{N002}"
        and c.execute(f"SELECT count(*) FROM identity_handle WHERE account='{N002}@s.whatsapp.net'").fetchone()[0] == 0)
    arm("a web account's first sight is its person", who("web", "2@cog", "cv-faran.2") == "cv-faran.2"
        and c.execute("SELECT count(*) FROM identity WHERE wire_name='cv-faran.2'").fetchone()[0] == 1)

    print("\nI2 LINK")
    identity.link(c, "cv-faran.2", "whatsapp", f"{N001}@s.whatsapp.net")
    arm("a linked account answers its person's name", who("whatsapp", f"{N001}@s.whatsapp.net", f"wa-{N001}") == "cv-faran.2")
    try:
        identity.link(c, "cv-other.3", "whatsapp", f"{N001}@s.whatsapp.net")
        moved = True
    except ValueError:
        moved = False
    refused = []
    for name in ("owner", "db", "nobody-yet"):
        try:
            identity.link(c, name, "whatsapp", f"{N020}@s.whatsapp.net")
        except ValueError:
            refused.append(name)
    arm("a link never makes a person: owner, an agent's name, an unknown name are all refused (medic 12637)",
        refused == ["owner", "db", "nobody-yet"], refused)
    arm("an account linked to one person is never moved to another silently", not moved
        and who("whatsapp", f"{N001}@s.whatsapp.net", "x") == "cv-faran.2")
    print("\nI5 A SIGNED-IN ACCOUNT'S EMAIL IS ONE OF ITS CHANNELS (owner 11-18)")
    web = lambda uid, w, e: c.execute("SELECT identity_web(%s, %s, %s)", (uid, w, e)).fetchone()[0]  # noqa: E731
    web("7@cog", "cv-sana.7", " Sana@Example.org ")
    arm("a member's sign-in email is linked to them, as one form (lowercase, trimmed)",
        who("email", "sana@example.org", "em-x") == "cv-sana.7" and who("web", "7@cog", "x") == "cv-sana.7")
    web("1@cog", "owner", "boss@example.org")
    arm("the owner's own email goes through identity_own", who("email", "boss@example.org", "em-x") == "owner")
    web("8@cog", "cv-mallory.8", "sana@example.org")
    arm("an email linked to someone else stays theirs: no error, never moved",
        who("email", "sana@example.org", "em-x") == "cv-sana.7" and who("web", "8@cog", "x") == "cv-mallory.8")
    web("9@cog", "cv-noemail.9", "")
    arm("no email: the person is made, nothing linked", who("web", "9@cog", "x") == "cv-noemail.9")
    from astryx.security import identity as tok
    from nacl.signing import SigningKey
    k = SigningKey.generate()
    ver = {tok.kid_of(k.verify_key): k.verify_key}
    both = tok.claims(tok.mint(k, "7@cog", "astryx", name="sana", email="sana@example.org"), ver, "astryx")
    none = tok.claims(tok.mint(k, "7@cog", "astryx"), ver, "astryx")
    arm("the signed identity carries the proven email, and '' when the front sends none",
        both and both["email"] == "sana@example.org" and none and none["email"] == "", (both, none))
    import types
    sys.path.insert(0, str(REPO / "observatory"))
    import front
    v = ("7@cog", "sana", "sana@example.org")
    proved = tok.claims(front._mint(types.SimpleNamespace(key=k, mail=object()), v, "astryx"), ver, "astryx")
    unproved = tok.claims(front._mint(types.SimpleNamespace(key=k, mail=None), v, "astryx"), ver, "astryx")
    arm("a cog with no mailbox proves no address, so its token vouches for none (medic 13734)",
        proved["email"] == "sana@example.org" and unproved["email"] == "", (proved, unproved))
    gate_src = (REPO / "observatory" / "api" / "main.py").read_text()
    gate_src = gate_src[gate_src.index("async def privacy_gate("):]
    arm("the backend's gate makes every signed-in account a person with its email (census: _account_seen is awaited)",
        "await _account_seen(request)" in gate_src[:gate_src.index("\n\n\n")])

    print("\nI3 ANSWERED WHERE THEY WROTE")
    wa = f"(to_agent='owner' OR to_agent LIKE 'wa-%' OR {address.reaches_sql('whatsapp')})"
    import importlib
    canvas_where = re.search(r"WHERE status='pending' AND to_org='local' AND \((.*)\)\n  ORDER BY", importlib.import_module("bridges.canvas").CLAIM, re.S).group(1)

    def claims(pred, to, thread):
        return c.execute(f"SELECT {pred.replace('%', '%%')} FROM (SELECT %s::text AS to_agent, %s::text AS thread) m", (to, thread)).fetchone()[0] is True
    rows = [("cv-faran.2", f"wa:{N001}@s.whatsapp.net", True, False), ("cv-faran.2", "cv:x", False, True),
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
