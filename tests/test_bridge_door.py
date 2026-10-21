#!/usr/bin/env python3
"""Oracle for plan-9139 S1c: the door at the bridge (a4 #45091, #53717). Every chat bridge's deliver() asks it FIRST.

  PURE     release.door_org / door_stamped / route_tier / live_steps_ok: an unstamped row passes only to a DECLARED
           ORG ROUTE (never "not labelled"); a stamped one only to the ONE route its stamp names, which must still
           release to its label; a tiered route can't declare live_steps
  BRIDGES  whatsapp, telegram and discord deliver() run for real against fakes (pool, routes, provider, platform):
           off-route → 'refused', nothing sent; declared org route → delivered with the census mark; a tiered route
           takes no unstamped row; a stamped row reaches the stamp's chat, never the thread's, its receipt carries the
           marker and no chat id; forged / rebound / keyless → refused; another bridge's release → untouched;
           WhatsApp's owner fallback lands on a declared route and is marked
  PAIRING  (AST) each bridge's deliver() calls the door before any platform send; every text-carrying platform send
           sits in a declared set of functions; every live_steps job is created under live_steps_ok()
  SELECT   (fixture DB) each bridge's own pending predicate selects ITS releases and not another bridge's
Hermetic apart from SELECT: synthetic env (never the live .env), fixture chat ids under 7 digits, a synthetic key.
Exit 0 pass · 1 fail · 77 a dependency or the fixture DB is absent.
"""
import ast
import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
# synthetic config BEFORE any bridge imports: env() falls back to the repo's .env for an unset key, so set them all
for k, v in {"ASTRYX_DSN": "postgresql://oracle@127.0.0.1:1/none", "WA_WEBHOOK_SECRET": "oracle-secret",
             "WA_CLI": "false", "WA_DATA_HOST": "/nonexistent-oracle", "TG_BOT_TOKEN": "oracle-token",
             "TG_API_BASE": "http://127.0.0.1:1", "DISCORD_BOT_TOKEN": "oracle-token"}.items():
    os.environ[k] = v
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_bridge_door", REPO, deps=("fastapi", "asyncpg", "httpx", "discord"))


def _load(name: str, path: str):
    """A mutation_probe copy is installed UNDER THE REAL NAME, so the bridges' own imports get the copy."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


import astryx.security  # noqa: E402
if os.environ.get("RELEASE_SRC"):
    R = _load("astryx.security.release", os.environ["RELEASE_SRC"])
    astryx.security.release = R
else:
    from astryx.security import release as R  # noqa: E402
import bridges  # noqa: E402
from bridges.routing import Routes  # noqa: E402 — what a bridge's routes() returns (plan-11860 E2)
if os.environ.get("BRIDGE_COMMON_SRC"):
    bridges.common = _load("bridges.common", os.environ["BRIDGE_COMMON_SRC"])
SEAM = {"whatsapp": "WA_SRC", "telegram": "TG_SRC", "discord": "DC_SRC"}
BR = {ch: _load(f"bridges.{ch}", os.environ.get(SEAM[ch]) or str(REPO / "bridges" / f"{ch}.py")) for ch in SEAM}

fails = []
SENT = "S1C-SENTINEL-private-body-7a31"
KEY = "d" * 40


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


root = Path(tempfile.mkdtemp(prefix="bridgedoor."))
R.REPO = root                                   # the tier store lives under the module's REPO; no .env there
os.environ[R.MAC_KEY_ENV] = KEY
K = KEY.encode()
CAREER = R.label(["career"])

WA_ORG = {"chat": "10101@g.us", "agent": "seed", "enabled": True}
WA_PLAIN = {"chat": "30303@g.us", "agent": "plain", "enabled": True}
WA_TIER = {"chat": "20202@s.whatsapp.net", "agent": "member", "enabled": True, "counterpart": "owner",
           "tier": "career"}
TG_ORG = {"chat": "40404", "agent": "seed", "enabled": True}
TG_TIER = {"chat": "50505", "agent": "member", "enabled": True, "counterpart": "owner", "tier": "career"}
DC_ORG = {"chat": "60606", "agent": "seed", "enabled": True}
ROUTES = {"whatsapp": [WA_ORG, WA_PLAIN, WA_TIER], "telegram": [TG_ORG, TG_TIER], "discord": [DC_ORG]}
_next = iter(range(500, 900))


def plain_row(thread, to="owner", frm="seed", body="org text"):
    return {"id": next(_next), "from_agent": frm, "to_agent": to, "thread": thread, "intent": "chat", "body": body,
            "delivery": None, "status": "pending", "to_org": "local"}


def stamped_row(channel, route, body=SENT, sender="member"):
    store = R.TierStore()
    rel = R.release(sender, CAREER, body, [(channel, route, root / f"routes-{channel}.json")], K, store)
    rid = next(_next)
    rel["stamp"] = R.stamp(K, rid, rel["route_key"], CAREER, rel["pointer"], rel["body_mac"])
    return {"id": rid, "from_agent": sender, "to_agent": "owner", "thread": f"tier-{sender}", "intent": "chat",
            "body": f"[released: {rel['bytes']} bytes, career]", "delivery": json.dumps({"release": rel}),
            "status": "pending", "to_org": "local"}


# ── PURE ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("pure:")
check("door_org: a declared org route passes", R.door_org("whatsapp", "10101@g.us", ROUTES["whatsapp"]) is WA_ORG)
check("door_org: a destination on NO route is refused (the stray row; the exemption is never 'not labelled')",
      refused(R.door_org, "whatsapp", "70707@s.whatsapp.net", ROUTES["whatsapp"]))
check("door_org: a TIERED route takes no unstamped row",
      refused(R.door_org, "whatsapp", "20202@s.whatsapp.net", ROUTES["whatsapp"]))
check("door_org: a malformed tier declaration refuses",
      isinstance(refused(R.door_org, "whatsapp", "10101@g.us", [{**WA_ORG, "Tier": "career"}]), R.GrantError))
check("door_org: a disabled route is not declared", refused(R.door_org, "whatsapp", "10101@g.us",
                                                            [{**WA_ORG, "enabled": False}]))
check("route_tier: a tiered route with live_steps is refused (its second egress, a4 #53717)",
      isinstance(refused(R.route_tier, {**WA_TIER, "live_steps": True}), R.GrantError))
check("live_steps_ok: an org route yes; a tiered or malformed one no; none declared no",
      R.live_steps_ok({**WA_ORG, "live_steps": True}) and not R.live_steps_ok({**WA_TIER, "live_steps": True})
      and not R.live_steps_ok({**WA_ORG, "live_steps": True, "tiers": "x"}) and not R.live_steps_ok(WA_ORG))
srow = stamped_row("whatsapp", WA_TIER)
route, body = R.door_stamped(srow, "whatsapp", ROUTES["whatsapp"], key=K, store=R.TierStore())
check("door_stamped: the stamp's route and the resolved body", route is WA_TIER and body == SENT)
MEMBER_ORG = {"chat": "11111@g.us", "agent": "member", "enabled": True}      # the member serves an org group too
route, body = R.door_stamped(srow, "whatsapp", [MEMBER_ORG, *ROUTES["whatsapp"]], key=K, store=R.TierStore())
check("door_stamped: the route its STAMP names, not the sender's first route", route is WA_TIER and body == SENT,
      repr(route))
rel = json.loads(srow["delivery"])["release"]
for what, bad in (("a swapped body MAC", {**rel, "body_mac": R.body_mac(K, "other")}),
                  ("a forged stamp", {**rel, "stamp": "0" * 64}),
                  ("a widened label", {**rel, "label": "career,family"}),
                  ("another row's id", None)):
    r2 = dict(srow, delivery=json.dumps({"release": bad})) if bad else dict(srow, id=srow["id"] + 1)
    check(f"door_stamped: {what} is refused", refused(R.door_stamped, r2, "whatsapp", ROUTES["whatsapp"], key=K,
                                                      store=R.TierStore()))
check("door_stamped: a route REBOUND since release (counterpart dropped) is refused",
      refused(R.door_stamped, srow, "whatsapp", [WA_ORG, {k: v for k, v in WA_TIER.items() if k != "counterpart"}],
              key=K, store=R.TierStore()))
check("door_stamped: the route its stamp names must be on THIS bridge (no route_key match → refused)",
      refused(R.door_stamped, srow, "whatsapp", [WA_ORG], key=K, store=R.TierStore()))


# ── BRIDGES: deliver() for real against fakes ─────────────────────────────────────────────────────────────────────
class Pool:
    def __init__(self, rows):
        self.rows = {r["id"]: r for r in rows}
        self.sql = []

    async def execute(self, sql, *args):
        self.sql.append(sql)
        r = self.rows[args[0]]
        if "status='refused'" in sql:
            if r["status"] == "pending":
                d = json.loads(r["delivery"]) if isinstance(r["delivery"], str) else (r["delivery"] or {})
                r.update(status="refused", delivery={**d, **json.loads(args[1])})
        elif "||" in sql:
            d = json.loads(r["delivery"]) if isinstance(r["delivery"], str) else (r["delivery"] or {})
            r.update(status=args[1], delivery={**d, **json.loads(args[2])})
        else:
            r.update(status=args[1], delivery=json.loads(args[2]))

    async def fetch(self, *a):
        return []

    async def fetchrow(self, *a):
        return None


class World:
    """What reached each platform: [(chat, text)]."""
    def __init__(self, ch, rows, pool=None, on_send=None):
        self.ch, self.sends, self.pool = ch, [], pool or Pool(rows)
        self.on_send = on_send
        m = BR[ch]
        m.pool = self.pool
        m.routes = lambda: Routes(ROUTES[ch])        # the resolved table, enabled rows only (plan-11860 E2)
        m.jobs.clear()
        w = self

        class Prov:
            async def send(self, chat, text):
                w.sends.append((str(chat), text))
                if w.on_send:
                    w.on_send()
                return SimpleNamespace(ok=True, message_id="m-1", error=None)
        m.PROVIDER = Prov()
        if ch == "whatsapp":
            async def wacli(*args):
                if args[:1] != ("presence",):       # typing/paused carries no text
                    w.sends.append(("wacli", " ".join(args)))
                return "{}"
            m.wacli, m.DATA_HOST = wacli, ""
        if ch == "telegram":
            async def tg(method, **kw):
                w.sends.append((str(kw.get("chat_id")), kw.get("text", method)))
                return {"message_id": 1, "poll": {"id": "p"}}
            m.tg = tg
        if ch == "discord":
            class Chan:
                def __init__(self, cid):
                    self.cid = cid

                async def send(self, content=None, **kw):
                    w.sends.append((self.cid, content))
                    if w.on_send:
                        w.on_send()
                    return SimpleNamespace(id=7)
            m.client = SimpleNamespace(get_channel=lambda cid: Chan(str(cid)))

    async def deliver(self, row):
        await BR[self.ch].deliver(self.pool.rows[row["id"]])
        return self.pool.rows[row["id"]]


def wire_text(row):
    return json.dumps(row.get("delivery")) if not isinstance(row.get("delivery"), str) else row["delivery"]


async def bridge_arms():
    off = {"whatsapp": "wa:70707@s.whatsapp.net", "telegram": "tg:80808", "discord": "dc:90909"}
    org = {"whatsapp": ("wa:10101@g.us", "10101@g.us"), "telegram": ("tg:40404", "40404"),
           "discord": ("dc:60606", "60606")}
    tiered = {"whatsapp": "wa:20202@s.whatsapp.net", "telegram": "tg:50505"}
    for ch in ("whatsapp", "telegram", "discord"):
        print(f"{ch}:")
        r = plain_row(off[ch])
        w = World(ch, [r])
        got = await w.deliver(r)
        check(f"{ch}: an unstamped row to a destination on NO route is REFUSED with a status, nothing sent (#45091)",
              got["status"] == "refused" and "door_refused" in got["delivery"] and not w.sends, repr((got, w.sends)))
        r = plain_row(org[ch][0])
        w = World(ch, [r])
        got = await w.deliver(r)
        check(f"{ch}: the same row to a DECLARED ORG ROUTE is delivered and carries the census mark",
              got["status"] == "delivered" and got["delivery"].get("door") == "org-unstamped"
              and (org[ch][1], "org text") in w.sends, repr((got, w.sends)))
        if ch in tiered:
            r = plain_row(tiered[ch])
            w = World(ch, [r])
            got = await w.deliver(r)
            check(f"{ch}: an unstamped row to a TIERED route is refused, nothing sent",
                  got["status"] == "refused" and not w.sends, repr((got, w.sends)))
            route = WA_TIER if ch == "whatsapp" else TG_TIER
            s = stamped_row(ch, route)
            w = World(ch, [s])
            got = await w.deliver(s)
            check(f"{ch}: a STAMPED row reaches its stamp's chat (never its thread's) with the resolved body",
                  got["status"] == "delivered" and w.sends == [(str(route["chat"]), SENT)], repr((got, w.sends)))
            check(f"{ch}: …its receipt carries the marker, names no chat, keeps the release record, holds no body",
                  got["delivery"].get("rendered") == s["body"] and got["delivery"].get("handle") == f"{ch}:release"
                  and got["delivery"].get("door") == "released" and "stamp" in got["delivery"].get("release", {})
                  and SENT not in wire_text(got) and str(route["chat"]) not in wire_text(got), repr(got))
            s = stamped_row(ch, route)
            s["delivery"] = json.dumps({"release": {**json.loads(s["delivery"])["release"], "stamp": "0" * 64}})
            w = World(ch, [s])
            got = await w.deliver(s)
            check(f"{ch}: a forged stamp is REFUSED (terminal), nothing sent",
                  got["status"] == "refused" and not w.sends and SENT not in wire_text(got), repr((got, w.sends)))
            s = stamped_row(ch, route)
            (root / "tier" / "release" / json.loads(s["delivery"])["release"]["pointer"]).unlink()
            w = World(ch, [s])
            got = await w.deliver(s)
            check(f"{ch}: a stamped row whose stored body is GONE is refused (a store error is never a crash)",
                  got["status"] == "refused" and not w.sends, repr((got, w.sends)))
            s = stamped_row(ch, route)
            os.environ.pop(R.MAC_KEY_ENV)
            w = World(ch, [s])
            try:
                got = await w.deliver(s)
            finally:
                os.environ[R.MAC_KEY_ENV] = KEY
            check(f"{ch}: no release key → the stamped row is refused, not a crash, nothing sent",
                  got["status"] == "refused" and not w.sends, repr((got, w.sends)))
        other = "telegram" if ch != "telegram" else "whatsapp"
        s = stamped_row(other, TG_TIER if other == "telegram" else WA_TIER)
        w = World(ch, [s])
        got = await w.deliver(s)
        check(f"{ch}: ANOTHER bridge's release is left untouched (pending, no update, nothing sent)",
              got["status"] == "pending" and not w.pool.sql and not w.sends, repr((got, w.pool.sql, w.sends)))
    print("whatsapp owner fallback (the census arm, a4 #53717):")
    for frm, chat in (("plain", "30303@g.us"), ("nobody", "10101@g.us")):
        for th in (None, "t-abc"):
            r = plain_row(th, frm=frm)
            w = World("whatsapp", [r])
            got = await w.deliver(r)
            check(f"an unthreaded owner row from {frm!r} (thread {th!r}) lands on a DECLARED route and is marked",
                  got["status"] == "delivered" and got["delivery"].get("door") == "org-unstamped"
                  and (chat, "org text") in w.sends, repr((got, w.sends)))
    # discord routes are channels (groups with no live membership read): no audience releases to one
    s = stamped_row("whatsapp", WA_TIER)
    rel = json.loads(s["delivery"])["release"]
    rel = {**rel, "channel": "discord", "route_key": R.route_key(K, "discord", DC_ORG)}
    rel["stamp"] = R.stamp(K, s["id"], rel["route_key"], CAREER, rel["pointer"], rel["body_mac"])
    s["delivery"] = json.dumps({"release": rel})
    w = World("discord", [s])
    got = await w.deliver(s)
    check("discord: a release stamped for a discord channel is refused (a group's audience never releases)",
          got["status"] == "refused" and not w.sends, repr((got, w.sends)))


asyncio.run(bridge_arms())


# ── PAIRING (AST) ─────────────────────────────────────────────────────────────────────────────────────────────────
print("pairing:")
# the functions a TEXT-carrying platform send may sit in. A new one fails here until a reviewer classifies it: inside
# deliver() (door-gated), a helper deliver() calls, the platform primitive itself, or the live_steps path (on_step /
# worker), whose jobs are created only under live_steps_ok()
EGRESS = {"whatsapp": {"deliver", "send_files", "send_poll", "worker"},
          "telegram": {"deliver", "on_step", "tg"},
          "discord": {"deliver", "on_step", "hook_send", "hook_file", "hook_poll", "hook_edit"}}
TG_TEXT = {"sendMessage", "editMessageText", "sendPoll", "sendPhoto", "sendDocument", "sendMediaGroup", "sendAudio",
           "sendVoice", "sendVideo", "copyMessage", "forwardMessage"}


def _text_send(ch, n):
    f = n.func
    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
    consts = [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    if ch == "whatsapp":
        return (name == "wacli" and (any(c in ("send", "edit") for c in consts)
                                     or any(isinstance(a, ast.Starred) for a in n.args))) or \
            (name == "send" and isinstance(f, ast.Attribute) and ast.unparse(f.value) == "PROVIDER")
    if ch == "telegram":
        return (name == "tg" and bool(consts) and consts[0] in TG_TEXT) or (name == "send" and isinstance(
            f, ast.Attribute) and ast.unparse(f.value) == "PROVIDER") or (name == "post" and isinstance(
                f, ast.Attribute) and ast.unparse(f.value) == "http")
    return name in ("send", "edit") and isinstance(f, ast.Attribute) or name == "post" and isinstance(
        f, ast.Attribute) and ast.unparse(f.value) == "hx"


for ch, m in BR.items():
    tree = ast.parse(Path(m.__file__).read_text())
    parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

    def encl(n):
        while n in parent:
            n = parent[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n
        return None
    sites = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _text_send(ch, n)]
    where = {(encl(n).name if encl(n) else "<module>") for n in sites}
    check(f"{ch}: every text-carrying platform send sits in a declared function ({len(sites)} sites)",
          sites and where <= EGRESS[ch], f"undeclared: {sorted(where - EGRESS[ch])}")
    dl = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "deliver")
    calls = {getattr(c.func, "id", None): c.lineno for c in ast.walk(dl) if isinstance(c, ast.Call)}
    first_send = min((n.lineno for n in sites if encl(n) is dl), default=10 ** 9)
    check(f"{ch}: deliver() asks the door (door_open AND door_org_ok) before its first platform send",
          "door_open" in calls and "door_org_ok" in calls and max(calls["door_open"], calls["door_org_ok"]) < first_send,
          repr({k: calls.get(k) for k in ("door_open", "door_org_ok")}))
    makes = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Subscript) and ast.unparse(t.value) == "jobs" for t in n.targets)]

    def guarded(n):
        while n in parent:
            n = parent[n]
            if isinstance(n, ast.If) and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "live_steps_ok"
                                             for c in ast.walk(n.test)):
                return True
        return False
    check(f"{ch}: every live_steps job ({len(makes)}) is created under live_steps_ok()",
          makes and all(guarded(n) for n in makes), [n.lineno for n in makes if not guarded(n)])


# ── SELECT: each bridge's own predicate, on a fixture DB ──────────────────────────────────────────────────────────
def predicate(ch):
    tree = ast.parse(Path(BR[ch].__file__).read_text())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "listen")
    return ast.literal_eval(call.args[1])


try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  select arms: {type(e).__name__}: {e}")
    shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'FAIL' if fails else 'SKIP (partial)'}")
    sys.exit(1 if fails else 77)
try:
    print("select:")
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        ids = {}
        for name, thread, ch in (("wa-rel", "tier-member", "whatsapp"), ("tg-rel", "tier-member", "telegram"),
                                 ("dc-rel", "tier-member", "discord"), ("tg-plain", "tg:40404", None)):
            d = json.dumps({"release": {"channel": ch}}) if ch else None
            ids[name] = c.execute(
                "INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, status, delivery) "
                "VALUES ('member','local','owner','local',%s,'chat','m','pending',%s) RETURNING id",
                (thread, d)).fetchone()[0]
        for ch, want, not_want in (("whatsapp", {"wa-rel"}, set()), ("telegram", {"tg-rel", "tg-plain"}, {"wa-rel"}),
                                   ("discord", {"dc-rel"}, {"wa-rel", "tg-rel"})):
            got = {r[0] for r in c.execute(
                f"SELECT id FROM messages WHERE status='pending' AND to_org='local' AND ({predicate(ch)})")}
            names = {n for n, i in ids.items() if i in got}
            check(f"{ch}: its pending predicate selects its own release(s) {sorted(want)} and not {sorted(not_want)}",
                  want <= names and not (names & not_want), sorted(names))
    print("deliver on the fixture DB (the door's own SQL, executed: sqlguard's (W) sees each WHERE at 0 and ≥1 rows):")

    async def db_arms():
        import asyncpg
        from psycopg.conninfo import conninfo_to_dict
        ci = conninfo_to_dict(fx["dsn"])
        pool = await asyncpg.create_pool(host=ci.get("host"), port=int(ci.get("port") or 5432), user=ci.get("user"),
                                         password=ci.get("password"), database=ci.get("dbname"), min_size=1, max_size=2)
        try:
            with psycopg.connect(fx["dsn"], autocommit=True) as c:
                def ins(thread, frm="seed", body="org text"):
                    return c.execute(
                        "INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, status) "
                        "VALUES (%s,'local','owner','local',%s,'chat',%s,'pending') RETURNING id",
                        (frm, thread, body)).fetchone()[0]

                def state(i):
                    st, d = c.execute("SELECT status, delivery FROM messages WHERE id=%s", (i,)).fetchone()
                    return st, d or {}
                for ch, org_t, off_t in (("whatsapp", "wa:10101@g.us", "wa:70707@s.whatsapp.net"),
                                         ("telegram", "tg:40404", "tg:80808"), ("discord", "dc:60606", "dc:90909")):
                    for what, thread, want in (("declared org route", org_t, "delivered"),
                                               ("destination on no route", off_t, "refused")):
                        i = ins(thread)
                        w = World(ch, [], pool=pool)
                        await BR[ch].deliver(await pool.fetchrow("SELECT * FROM messages WHERE id=$1", i))
                        st, d = state(i)
                        check(f"{ch} (db): an unstamped row to a {what} → {want}", st == want and (
                            d.get("door") == "org-unstamped" if want == "delivered" else "door_refused" in d), (st, d))
                for ch, route in (("whatsapp", WA_TIER), ("telegram", TG_TIER)):
                    with c.cursor() as cur:
                        i = R.send_row(cur, "member", CAREER, "owner", None, "chat", SENT, key=K, store=R.TierStore(),
                                       routes=[(ch, route, root / f"routes-{ch}.json")])
                    w = World(ch, [], pool=pool)
                    await BR[ch].deliver(await pool.fetchrow("SELECT * FROM messages WHERE id=$1", i))
                    st, d = state(i)
                    row_text = c.execute("SELECT m::text FROM messages m WHERE id=%s", (i,)).fetchone()[0]
                    check(f"{ch} (db): send_row's stamped row is delivered to its stamp's chat; the receipt MERGED "
                          f"into the release record; no body and no chat id in the row",
                          st == "delivered" and w.sends == [(str(route["chat"]), SENT)] and "stamp" in d.get("release", {})
                          and d.get("door") == "released" and SENT not in row_text and str(route["chat"]) not in row_text,
                          (st, d, w.sends))
                # a released send that FAILS: the platform's own error text (a CLI's stderr, an API description)
                # may name the chat, so the receipt's error carries part and exception type only (a4 #53846)
                for ch, route in (("whatsapp", WA_TIER), ("telegram", TG_TIER)):
                    with c.cursor() as cur:
                        i = R.send_row(cur, "member", CAREER, "owner", None, "chat", SENT, key=K, store=R.TierStore(),
                                       routes=[(ch, route, root / f"routes-{ch}.json")])

                    def boom(ch=ch):
                        raise RuntimeError(f"{ch} send text: S1C-ERR-SENTINEL {route['chat']} said no")
                    w = World(ch, [], pool=pool, on_send=boom)
                    await BR[ch].deliver(await pool.fetchrow("SELECT * FROM messages WHERE id=$1", i))
                    st, d = state(i)
                    row_text = c.execute("SELECT m::text FROM messages m WHERE id=%s", (i,)).fetchone()[0]
                    check(f"{ch} (db): a FAILED released send is dead, its error the part and type only — no platform "
                          f"text, no chat id",
                          st == "dead" and "RuntimeError" in str(d.get("error")) and "S1C-ERR-SENTINEL" not in row_text
                          and str(route["chat"]) not in row_text and SENT not in row_text, (st, d))
                # the 0-row side of each WHERE: a settled row is never re-refused; a receipt for no row writes nothing
                i = ins("wa:70707@s.whatsapp.net")
                await BR["whatsapp"].deliver(await pool.fetchrow("SELECT * FROM messages WHERE id=$1", i))
                await bridges.common.door_refuse(pool, {"id": i}, "whatsapp", "again")
                check("db: door_refuse on a row that is no longer pending changes nothing (WHERE status='pending')",
                      state(i)[0] == "refused" and state(i)[1].get("door_refused", "").endswith("route of this bridge"),
                      state(i))
                # discord: no release reaches a channel today (a group's audience needs a live membership read), so its
                # released receipt is driven with the door's answer stubbed: the receipt shape must hold all the same
                real_open = BR["discord"].door_open
                for gone in (False, True):
                    with c.cursor() as cur:
                        i = R.send_row(cur, "member", CAREER, "owner", None, "chat", SENT, key=K, store=R.TierStore(),
                                       routes=[("whatsapp", WA_TIER, root / "routes-whatsapp.json")])

                    async def stub(pool_, row_, channel, routes_):
                        return DC_ORG, SENT
                    BR["discord"].door_open = stub
                    try:
                        w = World("discord", [], pool=pool, on_send=(
                            lambda i=i: c.execute("DELETE FROM messages WHERE id=%s", (i,))) if gone else None)
                        await BR["discord"].deliver(await pool.fetchrow("SELECT * FROM messages WHERE id=$1", i))
                    finally:
                        BR["discord"].door_open = real_open
                    got = c.execute("SELECT status, delivery, m::text FROM messages m WHERE id=%s", (i,)).fetchone()
                    check(f"discord (db): a released row's receipt {'writes nothing for a row deleted mid-delivery' if gone else 'names no channel and carries the marker'}",
                          (got is None) if gone else (got[0] == "delivered" and got[1].get("handle") == "discord:release"
                                                      and "60606" not in got[2] and SENT not in got[2]), got)
                # a row DELETED while its delivery is in flight (an operator's cleanup): the receipt matches nothing and
                # writes nothing, through each bridge's own receipt statement
                cases = [(ch, t, None) for ch, t in (("whatsapp", "wa:10101@g.us"), ("telegram", "tg:40404"),
                                                     ("discord", "dc:60606"))]
                cases += [(ch, None, route) for ch, route in (("whatsapp", WA_TIER), ("telegram", TG_TIER))]
                for ch, thread, route in cases:
                    if route:
                        with c.cursor() as cur:
                            i = R.send_row(cur, "member", CAREER, "owner", None, "chat", SENT, key=K,
                                           store=R.TierStore(), routes=[(ch, route, root / f"routes-{ch}.json")])
                    else:
                        i = ins(thread)
                    w = World(ch, [], pool=pool, on_send=lambda i=i: c.execute("DELETE FROM messages WHERE id=%s", (i,)))
                    await BR[ch].deliver(await pool.fetchrow("SELECT * FROM messages WHERE id=$1", i))
                    check(f"{ch} (db): a {'stamped' if route else 'org'} row deleted mid-delivery: sent once, and the "
                          f"receipt writes nothing", len(w.sends) == 1 and c.execute(
                              "SELECT count(*) FROM messages WHERE id=%s", (i,)).fetchone()[0] == 0, w.sends)
        finally:
            await pool.close()
    asyncio.run(db_arms())
finally:
    _fx.__exit__(None, None, None)
    shutil.rmtree(root, ignore_errors=True)
print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
