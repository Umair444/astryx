#!/usr/bin/env python3
"""Oracle for plan-9139 S1b-2b's python half: the bridges' tier-route ingress and the door's read rule.

  ROUTE      route_tier(): an exact `"tier": "<declared>"` declares; a value outside TIERS, or a key that looks like a
             tier key but isn't exactly `tier`, REFUSES (never reads as untiered)
  INGRESS    bridges/common.wire_insert(route=…) on a declared DM route to the owner, through the bridges' own driver
             (asyncpg) on a stamped fixture DB: ONE row, to the ROUTE's agent (never an @mention's), body a size
             marker, delivery {pointer, body_mac, tier} + identity fields; the body AND the quoted reply's text are
             absent from every column and resolve through read_for(). A malformed tier, a bad key, an open route, a
             group route or no key → a metadata-only WITHHELD row and NOTHING stored. No tier / no route → today's row
  READ       read_for(): the pointer's tiers ⊆ the agent's label; an org or UNKNOWN agent, another tier's member and a
             wrong MAC are refused; a member holding the tier among others reads it. The CLI form needs the MAC
  PAIRING    each bridge's inbound CHAT insert passes route= (an AST read of the three bridge files)
Fixtures only: a temp root (charters, the tier store), fixture chat ids under 7 digits, a synthetic key.
Exit 0 pass · 1 fail · 77 no fixture DB.
"""
import ast
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import importlib.util  # noqa: E402


def _load(name: str, path: str):
    """The mutation probe hands a mutated copy of a SUBJECT; it is installed UNDER THE REAL NAME, so the bridge's own
    lazy `from astryx.security import release` (and `from bridges import common`) gets the copy, not the original."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if os.environ.get("RELEASE_SRC"):
    import astryx.security  # noqa: E402
    R = _load("astryx.security.release", os.environ["RELEASE_SRC"])
    astryx.security.release = R
else:
    from astryx.security import release as R  # noqa: E402

fails = []
SENT = "S1B2B-SENTINEL-inbound-body-91d2"
QUOTE = "S1B2B-QUOTED-reply-body-5e07"
KEY = "q" * 40


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except R.Refused as e:
        return e
    return None


root = Path(tempfile.mkdtemp(prefix="relingress."))
(root / "agents").mkdir()
(root / "agents" / "member.md").write_text("# member\nGrants: owner_private:career\n")
(root / "agents" / "wide.md").write_text("# wide\nGrants: owner_private:career, owner_private:family\n")
(root / "agents" / "fam.md").write_text("# fam\nGrants: owner_private:family\n")
(root / "agents" / "plain.md").write_text("# plain\nGrants: gmail\n")
R.REPO = root                                   # charters and the tier store live under the module's REPO
os.environ[R.MAC_KEY_ENV] = KEY
DM = {"chat": "202@s.whatsapp.net", "agent": "member", "enabled": True, "counterpart": "owner", "tier": "career"}

print("route_tier:")
check("an exact declaration → its tier", R.route_tier(DM) == "career")
check("no declaration → None (today's path)", R.route_tier({"chat": "1", "agent": "x"}) is None)
for bad in ({**DM, "tier": "carrer"}, {**DM, "tier": "Career"}, {**DM, "tier": None},
            {k: v for k, v in DM.items() if k != "tier"} | {"Tier": "career"},
            {k: v for k, v in DM.items() if k != "tier"} | {"tiers": ["career"]}):
    check(f"a malformed declaration {({k: v for k, v in bad.items() if 'tier' in k.lower()})} REFUSES",
          isinstance(refused(R.route_tier, bad), R.GrantError))

print("read_for:")
store = R.TierStore()
_, meta = R.ingress("whatsapp", DM, SENT, KEY.encode(), store)
ptr, mac = meta["ingress"]["pointer"], meta["ingress"]["body_mac"]
check("the member reads its tier's body", R.read_for("member", ptr, mac, key=KEY.encode(), store=store) == SENT)
check("a member holding the tier AMONG others reads it (⊆, not ==)",
      R.read_for("wide", ptr, mac, key=KEY.encode(), store=store) == SENT)
check("another tier's member is refused", refused(R.read_for, "fam", ptr, mac, key=KEY.encode(), store=store))
check("an org agent is refused", refused(R.read_for, "plain", ptr, mac, key=KEY.encode(), store=store))
check("an UNKNOWN agent (no charter) is refused", refused(R.read_for, "ghost", ptr, mac, key=KEY.encode(),
                                                          store=store))
check("a wrong MAC is refused (a swapped body or a lifted pointer resolves to nothing)",
      refused(R.read_for, "member", ptr, R.body_mac(KEY.encode(), "other"), key=KEY.encode(), store=store))
check("a pointer to nothing is refused, not a crash",
      refused(R.read_for, "member", "career/" + "A" * 32, mac, key=KEY.encode(), store=store))
os.environ["ASTRYX_AGENT"] = "member"
buf = io.StringIO()
with redirect_stdout(buf):
    rc2 = R.main(["read", ptr])
buf3 = io.StringIO()
with redirect_stdout(buf3):
    rc3 = R.main(["read", ptr, mac])
check("CLI: `read <pointer>` without its MAC is not a read (usage, no body)", rc2 == 2 and SENT not in buf.getvalue())
check("CLI: `read <pointer> <mac>` returns the body", rc3 == 0 and buf3.getvalue() == SENT)

print("store:")
_real_write = R.os.write
def _enospc(fd, data):
    raise OSError(28, "No space left on device")
R.os.write = _enospc
n_before = sum(1 for p in (root / "tier" / "release").rglob("*") if p.is_file())
try:
    store.put(frozenset({"career"}), SENT)
    raised = False
except OSError:
    raised = True
finally:
    R.os.write = _real_write
check("a write that fails leaves NO half-body under a pointer (put is all or nothing)",
      raised and sum(1 for p in (root / "tier" / "release").rglob("*") if p.is_file()) == n_before)
R.os.write = lambda fd, data: _real_write(fd, bytes(data[:1]))      # the kernel may write SHORT: one byte a call
try:
    p1 = store.put(frozenset({"career"}), SENT)
finally:
    R.os.write = _real_write
check("a SHORT write still stores the whole body", store.get(p1, frozenset({"career"})) == SENT)
R.os.write = _enospc
try:
    e = refused(R.ingress, "whatsapp", DM, SENT, KEY.encode(), store)
finally:
    R.os.write = _real_write
check("ingress maps a store OSError to Refused (every caller withholds; a4 #53081)",
      e is not None and "store could not take the body" in str(e) and SENT not in str(e), repr(e))

print("pairing:")
# every insert a bridge makes FROM its own channel (an inbound human's text, a poll a human posted, a vote) passes
# the route it arrived on, so a tier route can never be bypassed by one site; the pulse-witness row (from 'local')
# and the reaction signal (common.py, no route in scope: it quotes stored bodies, markers on a tier route) are not
for f, ch in (("whatsapp.py", "whatsapp"), ("discord.py", "discord"), ("telegram.py", "telegram")):
    calls = [n for n in ast.walk(ast.parse((REPO / "bridges" / f).read_text()))
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "wire_insert"
             and len(n.args) > 2 and isinstance(n.args[2], ast.Constant) and n.args[2].value == ch]
    bare = [n.lineno for n in calls if not any(k.arg == "route" for k in n.keywords)]
    check(f"{f}: all {len(calls)} of its own-channel inserts pass route=", calls and not bare, f"bare at {bare}")
    tree = ast.parse((REPO / "bridges" / f).read_text())
    targets = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "route_target"]
    saids = [n for n in calls if any(k.arg == "said" for k in n.keywords)]
    check(f"{f}: each route_target'd insert passes said= (a tier route stores the text as typed)",
          targets and len(saids) == len(targets), f"route_target {len(targets)}, said= {len(saids)}")

try:
    import asyncpg
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from astryx.security.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  db arms: {type(e).__name__}: {e}")
    print(f"\n{'FAIL' if fails else 'SKIP (partial)'}")
    sys.exit(1 if fails else 77)

if os.environ.get("BRIDGE_COMMON_SRC"):
    import bridges  # noqa: E402
    common = _load("bridges.common", os.environ["BRIDGE_COMMON_SRC"])
else:
    from bridges import common  # noqa: E402


def files() -> int:
    return sum(1 for p in (root / "tier" / "release").rglob("*") if p.is_file())


async def db_arms():
    ci = conninfo_to_dict(fx["dsn"])
    pool = await asyncpg.create_pool(host=ci.get("host"), port=int(ci.get("port") or 5432), user=ci.get("user"),
                                     password=ci.get("password"), database=ci.get("dbname"), min_size=1, max_size=2)
    meta = {"sender_jid": "202@s.whatsapp.net", "phone": "202", "push_name": "Owner", "reply_to_id": "m-7",
            "reply_to_body": QUOTE}
    try:
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            def blob():
                return "\n".join(r[0] for r in c.execute("SELECT m::text FROM messages m").fetchall())

            def last():
                return c.execute("SELECT from_agent, to_agent, thread, intent, body, delivery FROM messages "
                                 "ORDER BY id DESC LIMIT 1").fetchone()

            print("ingress:")
            n0 = files()
            # to_agent 'seed': an @mention resolved by route_target; a tier route pins the ROUTE's agent
            await common.wire_insert(pool, "owner", "whatsapp", "seed", "wa:202@s.whatsapp.net", "chat",
                                     f"hello {SENT}", meta, route=DM)
            row = last()
            ing = (row[5] or {}).get("ingress", {})
            check("ONE row, to the ROUTE's agent (not the @mention's), body the size marker",
                  row[1] == "member" and row[4].startswith("[tier-routed: ") and row[4].endswith(" bytes, career]"),
                  repr(row[:5]))
            check("the body and the quoted reply's text are ABSENT from every messages column",
                  SENT not in blob() and QUOTE not in blob())
            check("delivery keeps the identity fields, drops reply_to_body",
                  (row[5] or {}).get("sender_jid") == "202@s.whatsapp.net" and "reply_to_body" not in (row[5] or {}))
            body = R.read_for("member", ing.get("pointer"), ing.get("body_mac"), key=KEY.encode(), store=R.TierStore())
            check("the pointer resolves to the body WITH the quoted text", SENT in body and QUOTE in body, body)
            check("one body stored", files() == n0 + 1)
            withheld = [("an undeclared tier value", {**DM, "tier": "carrer"}),
                        ("a mis-spelled tier key", {k: v for k, v in DM.items() if k != "tier"} | {"Tier": "career"}),
                        ("an OPEN tier route", {**DM, "open": True}),
                        ("a GROUP tier route", {**DM, "chat": "303@g.us"}),
                        ("a DM whose counterpart isn't declared the owner", {**DM, "counterpart": "someone"})]
            for what, route in withheld:
                n0 = files()
                await common.wire_insert(pool, "owner", "whatsapp", "member", "wa:x", "chat", f"x {SENT}", meta,
                                         route=route)
                row = last()
                check(f"{what}: a WITHHELD marker row, nothing stored, no content",
                      row[4].startswith("[tier-routed message withheld") and files() == n0
                      and "ingress_withheld" in (row[5] or {}) and SENT not in blob() and QUOTE not in blob(),
                      repr(row[4:]))
            os.environ.pop(R.MAC_KEY_ENV)
            n0 = files()
            await common.wire_insert(pool, "owner", "whatsapp", "member", "wa:x", "chat", f"k {SENT}", meta, route=DM)
            os.environ[R.MAC_KEY_ENV] = KEY
            row = last()
            check("no release key: WITHHELD, nothing stored", row[4].startswith("[tier-routed message withheld")
                  and files() == n0 and SENT not in blob(), repr(row[4:]))

            cdir = root / "tier" / "release" / "career"
            n0 = files()
            cdir.chmod(0o500)                   # the tier store can't take a body (a4 #53081: was a traceback, no row)
            try:
                await common.wire_insert(pool, "owner", "whatsapp", "member", "wa:x", "chat", f"u {SENT}", meta,
                                         route=DM)
            finally:
                cdir.chmod(0o700)
            row = last()
            check("an UNWRITABLE store: one WITHHELD row (Refused), nothing stored, no content",
                  row[4] == "[tier-routed message withheld: Refused]" and "ingress_withheld" in (row[5] or {})
                  and files() == n0 and SENT not in blob(), repr(row[4:]))
            await common.wire_insert(pool, "owner", "whatsapp", "seed", "wa:202@s.whatsapp.net", "chat", f"hi {SENT}",
                                     {}, route=DM, said=f"@seed hi {SENT}")
            ing = (last()[5] or {}).get("ingress", {})
            body = R.read_for("member", ing.get("pointer"), ing.get("body_mac"), key=KEY.encode(), store=R.TierStore())
            check("a tier route stores the text AS TYPED (the @mention kept, so the member sees who was addressed)",
                  body == f"@seed hi {SENT}" and last()[1] == "member", body)

            print("today's path:")
            plain_route = {k: v for k, v in DM.items() if k != "tier"}
            m2 = {"sender_jid": "202@s.whatsapp.net", "reply_to_body": "quoted as ever"}
            await common.wire_insert(pool, "owner", "whatsapp", "seed", "wa:9", "chat", "plain text", m2,
                                     route=plain_route)
            check("an untiered route: today's row (to the @mention, body and meta as given)",
                  last() == ("owner", "seed", "wa:9", "chat", "plain text", m2), repr(last()))
            await common.wire_insert(pool, "owner", "whatsapp", "seed", "wa:9", "chat", "stripped", m2,
                                     route=plain_route, said="@seed stripped")
            check("an untiered route ignores said= (today's row carries the stripped text, as ever)",
                  last() == ("owner", "seed", "wa:9", "chat", "stripped", m2), repr(last()))
            await common.wire_insert(pool, "owner", "whatsapp", "seed", "wa:9", "chat", "no route", m2)
            check("no route passed: today's row", last() == ("owner", "seed", "wa:9", "chat", "no route", m2),
                  repr(last()))
    finally:
        await pool.close()


try:
    asyncio.run(db_arms())
finally:
    _fx.__exit__(None, None, None)
    shutil.rmtree(root, ignore_errors=True)
print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
