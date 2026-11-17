#!/usr/bin/env python3
"""Oracle: THE one channel table (src/astryx/core/channels.py; owner 11-16: "channels stuff should be a standard … we
can't patch it by each channel. later we will add slack and teams too").

  H1 SAME ANSWERS: every reader now derived from the table answers as its hand-written copy did on the shapes the wire
     holds: who is a person (address), which names no peer may take (orgname, + 'frontend', the frontends bridge's
     stamp, which was missing), a chat's kind (routing, release), a group conversation and a bridged owner row in SQL
     (owed, owner_surfaces, run on the fixture database next to the old predicates)
  H2 PAIRING: each channel's bridge file exists; each provider class names a channel, and each channel the owner
     connects has a provider
  H3 A NEW CHANNEL IS ONE ROW: a fake `slack` row, and every reader admits it with no other edit: its people are
     addressable and persons, its stamp reserved, its group threads owe a reply only when addressed, its owner rows
     are bridged, its chats have kinds, `astryx connect` and the channel screen know it, its unit is in the census
  H4 THE PLACES THAT CAN'T IMPORT IT, pinned: init.sh and deploy.sh name every connectable channel's unit, and the
     web's reserved names are orgname's
Exit 0 · 1 · 77 (no database: H1's SQL arms are not run)."""
# synthetic numbers, built rather than written whole so no phone or JID shape sits in the source (devtools/privacy_gate.sh (c))
N000 = "92" + "3000000000"

import importlib
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]
from astryx.core import channels as C  # noqa: E402

fails, skipped = [], []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


def fresh(*mods):
    """Re-import the readers, so each derives from the table as it is now."""
    return [importlib.reload(importlib.import_module(m)) for m in mods]


print("H1 SAME ANSWERS")
address, orgname, owed, release = fresh("astryx.core.address", "astryx.core.orgname", "astryx.core.owed",
                                        "astryx.security.release")
routing, owner_surfaces = fresh("bridges.routing", "bridges.owner_surfaces")
OLD_PERSON = re.compile(r"^(owner|wa-[^\s@]+|tg-[^\s@]+|dc-[^\s@]+|cv-[^\s@]+|fe-[^\s@]+)$")
names = ["owner", f"wa-{N000}", "tg-123", "dc-9", "cv-pat.2", "fe-dash", "db", "seed", "canvas-3", "room", "pulse"]
arm("who is a person: as before", [address.surface_of(n) in address.PERSONS for n in names] == [bool(OLD_PERSON.match(n)) for n in names],
    [(n, address.surface_of(n)) for n in names])
arm("names no peer may take: the old six, 'frontend' (the frontends bridge's stamp) and 'sms' (its row, 11-18)",
    orgname.RESERVED_ORGS == {"local", "whatsapp", "telegram", "discord", "canvas", "owner", "frontend", "sms"},
    sorted(orgname.RESERVED_ORGS))


def old_chat_kind(channel, chat):                # release.chat_kind as it was
    if channel == "whatsapp":
        return "group" if chat.endswith("@g.us") else "dm" if chat.endswith(("@s.whatsapp.net", "@lid")) else "unknown"
    if channel == "telegram":
        return "group" if re.fullmatch(r"-\d+", chat) else "dm" if re.fullmatch(r"\d+", chat) else "unknown"
    return "group" if channel == "discord" else "unknown"


chats = [("whatsapp", "1203@g.us"), ("whatsapp", "92300@s.whatsapp.net"), ("whatsapp", "77@lid"), ("whatsapp", "x@y"),
         ("telegram", "-100123"), ("telegram", "12345"), ("telegram", "abc"), ("discord", "123"), ("canvas", "c1")]
arm("a chat's kind (release, the audience gate): as before", [release.chat_kind(*c) for c in chats] == [old_chat_kind(*c) for c in chats],
    [(c, release.chat_kind(*c), old_chat_kind(*c)) for c in chats])
arm("a chat's glyph (routing): group or person as before, on the ids routes hold",
    [routing.kind_of(*c) for c in chats[:3] + chats[4:6] + chats[7:8]] == ["group", "person", "person", "group", "person", "group"])

threads = ["wa:1203@g.us", "wa:92300@s.whatsapp.net", "tg:-100", "tg:55", "dc:9", "cv:x", "obs:seed", "chat:1", "fe:dash:1",
           "t-1", "", None, "tier-1", "ear-1", "w:x"]
try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    with fixture_db() as d, psycopg.connect(d["url"]) as conn:
        q = lambda pred, t: conn.execute(f"SELECT {pred} FROM (SELECT %s::text AS thread, NULL::jsonb AS delivery) m", (t,)).fetchone()[0]  # noqa: E731
        arm("the regexes' backslashes reach Postgres as written (standard_conforming_strings on; medic 12631)",
            conn.execute("SHOW standard_conforming_strings").fetchone()[0] == "on")
        old_group = "(thread LIKE 'wa:%%@g.us' OR thread LIKE 'tg:-%%' OR thread LIKE 'dc:%%')"
        arm("a group conversation (owed): as before", [q(owed.GROUP.replace("m.thread", "thread"), t) for t in threads] == [q(old_group, t) for t in threads])
        old_bridged = ("(thread IS NULL OR thread = '' OR thread LIKE 't-%%' OR thread LIKE 'wa:%%' OR thread LIKE 'tg:%%' "
                       "OR thread LIKE 'dc:%%' OR thread LIKE 'cv:%%' OR thread LIKE 'tier-%%' OR thread LIKE 'ear-%%' "
                       "OR delivery->'release' IS NOT NULL)")
        new_bridged = owner_surfaces.OWNER_ROW_BRIDGED_SQL.replace("%", "%%")
        arm("an owner row a bridge delivers (owner_surfaces): as before", [q(new_bridged, t) for t in threads] == [q(old_bridged, t) for t in threads])
except SystemExit as e:                 # fixture_db exits 77 with no database
    if e.code != 77:
        raise
    skipped.append("H1 SQL")
    print("  SKIP  H1's SQL arms: no database")

print("\nH2 PAIRING")
arm("each channel's bridge is bridges/<name>.py", all((REPO / "bridges" / f"{c.name}.py").exists() for c in C.CHANNELS),
    [c.name for c in C.CHANNELS if not (REPO / "bridges" / f"{c.name}.py").exists()])
provided = {m.group(1) for f in (REPO / "bridges" / "providers").glob("*.py")
            for m in re.finditer(r'^\s+NAME = "([a-z]+)"', f.read_text(), re.M)}
arm("each provider names a channel", provided <= set(C.BY_NAME), provided - set(C.BY_NAME))
arm("each channel the owner connects has a provider", {c.name for c in C.connectable()} <= provided, {c.name for c in C.connectable()} - provided)

print("\nH3 A NEW CHANNEL IS ONE ROW")
slack = C.Channel("slack", "Slack", person="sl", thread="sl", group=r"C[A-Z0-9]+", dm=r"D[A-Z0-9]+",
                  token_key="SLACK_BOT_TOKEN", token_ask="Slack bot token", token_shape=r"xoxb-[A-Za-z0-9-]+")
saved = C.CHANNELS, C.BY_NAME
C.CHANNELS = (*C.CHANNELS, slack)
C.BY_NAME = {c.name: c for c in C.CHANNELS}
try:
    address, orgname, owed, release, cli, census = fresh("astryx.core.address", "astryx.core.orgname", "astryx.core.owed",
                                                         "astryx.security.release", "astryx.cli", "astryx.security.dsn_census")
    routing, owner_surfaces = fresh("bridges.routing", "bridges.owner_surfaces")
    arm("its people are addressable, and persons", address.surface_of("sl-U123") == "slack" and "slack" in address.PERSONS
        and "x LIKE 'sl-%'" in address.person_sql("x", params=False))
    arm("its stamp is reserved: no peer may pose as it", "slack" in orgname.RESERVED_ORGS)
    arm("its group threads are groups (a reply is owed there only when addressed)", "'^sl:(C[A-Z0-9]+)$'" in owed.GROUP, owed.GROUP)
    arm("its owner rows are its bridge's", "thread LIKE 'sl:%'" in owner_surfaces.OWNER_ROW_BRIDGED_SQL)
    arm("its chats have kinds", (release.chat_kind("slack", "C01AB"), release.chat_kind("slack", "D02CD"), routing.kind_of("slack", "C01AB"))
        == ("group", "dm", "group"))
    arm("`astryx connect slack` knows its token and unit (its routes are rows, made on the rail)",
        cli.CHANNELS.get("slack") == {"key": "SLACK_BOT_TOKEN", "ask": "Slack bot token",
                                      "unit": "astryx-slack", "generate": False}, cli.CHANNELS.get("slack"))
    arm("its unit is in the DSN census", "astryx-slack" in census.SERVICES)
    main_src = (REPO / "observatory" / "api" / "main.py").read_text()
    arm("the channel screen enumerates the table, not a list", "for ch in (c.name for c in _channels.connectable()):" in main_src
        and '("whatsapp", "telegram", "discord")' not in main_src)
finally:
    C.CHANNELS, C.BY_NAME = saved
    fresh("astryx.core.address", "astryx.core.orgname", "astryx.core.owed", "astryx.cli", "astryx.security.dsn_census",
          "bridges.owner_surfaces")

print("\nH4 THE PLACES THAT CAN'T IMPORT IT")
for f in ("init.sh", "scripts/deploy.sh"):
    text = (REPO / f).read_text()
    missing = [c.name for c in C.connectable() if c.name not in text]
    arm(f"{f} names every connectable channel", not missing, missing)
ts = (REPO / "observatory/web/src/components/CogNewOrg.tsx").read_text()
web = set(re.findall(r"'([a-z]+)'", re.search(r"const RESERVED = new Set\(\[([^\]]*)\]\)", ts).group(1)))
arm("the web's reserved org names are orgname's", web == set(orgname.RESERVED_ORGS), web ^ set(orgname.RESERVED_ORGS))
web_src = "\n".join(p.read_text() for p in (REPO / "observatory/web/src").rglob("*.ts*"))
arm("the web keeps no channel's chat-id rule of its own", "endsWith('@g.us')" not in web_src and "startsWith('-') ?" not in web_src)

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: one table, every reader" + (f" ({', '.join(skipped)} skipped)" if skipped else ""))
sys.exit(1 if fails else 77 if skipped else 0)
