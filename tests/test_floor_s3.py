#!/usr/bin/env python3
"""Oracle: plan-11860 S3, connecting a channel from the floor (a4 #61976 E5 E6 E7 E8). In-process, hermetic: the
.env is a fixture file (main.ENV_FILE), the channel APIs answer through an httpx.MockTransport (main._PROBE_TRANSPORT),
the bridge and wacli are stubbed at their seams (main._bridge, main._wa_link). Nothing reaches a real channel.
  - GATE: every channel route is 403 without the owner key.
  - E5: the .env key comes from the server's table (a body can't name one; whatsapp has no token route); a malformed
    token or one carrying a newline is refused before any call; the value is written by config.set_env, once; a set
    key is replaced only with replace=true (409 needs_confirm otherwise, file untouched).
  - E6: for each failure the channel can give (invalid, unreachable, rate-limited) and for success, neither the token
    nor its last 6 characters appears in the response body, in ANY captured log line (httpx's request log, which
    renders the token-bearing URL, included), or in ANY row of the fixture's messages or steps (the wire /api/events
    streams; checked live with the app's lifespan running, and the instrument is shown to fire on a planted tail);
    logredact scrubs a bot token and a webhook URL; and no channel handler names the pool.
  - E7: CONNECTED only from the bridge's own /health (and discord's connected flag); a bridge that started before the
    token was written, or isn't running, is ACTIVATION NEEDED with the exact command.
  - E8: pairing refuses a LINKED phone and an UNKNOWN link state (409, nothing started); both wacli argvs are constants.
"""
import ast
import importlib.util
import io
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_floor_s3', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'httpx'), env=False)   # fixture_db only (sqlsite.sh)
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

fails = 0
O = {"x-obs-key": "test-owner-key"}
TG = "123456789:AAH4kq9-ZZsecretTOKENvalue_abcdefghijkl"
DC = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GabCdE.SecretDiscordTokenValue_abcdefghijkl"


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(tmp: Path, url: str):
    import psycopg
    import httpx
    spec = importlib.util.spec_from_file_location("main", REPO / "observatory" / "api" / "main.py")
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.testclient import TestClient
    from astryx.security import logredact

    env = tmp / ".env"
    env.write_text("ASTRYX_ORG=fixture.example\n")
    obs.ENV_FILE = env
    logs = io.StringIO()
    h = logging.StreamHandler(logs)
    h.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.DEBUG)
    for n in ("httpx", "httpcore", "astryx.channels"):
        logging.getLogger(n).setLevel(logging.DEBUG)

    mode = {"v": "ok"}

    def upstream(req: httpx.Request):
        if mode["v"] == "unreachable":
            raise httpx.ConnectError(f"cannot reach {req.url}", request=req)
        if mode["v"] == "rate-limited":
            return httpx.Response(429, json={"ok": False, "retry_after": 3})
        if mode["v"] == "invalid":
            return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
        if "telegram" in str(req.url):
            return httpx.Response(200, json={"ok": True, "result": {"id": 42, "username": "astryx_bot"}})
        return httpx.Response(200, json={"id": "987654321012345678", "username": "astryx"})
    obs._PROBE_TRANSPORT = httpx.MockTransport(upstream)
    obs._bridge = lambda ch: {"unit": f"astryx-{ch}.service", "active": True, "started": time.time() - 3600,
                              "health": {"ok": True, "connected": True}}
    cl = TestClient(obs.app)
    cl.__enter__()                      # the lifespan runs: the pool, the LISTEN task, the wire as /api/events reads it

    def wire_clean(tok):
        # E6's third sink, DYNAMIC (a4 #62022 R2): every row of the wire's two tables, whole, as text
        with psycopg.connect(url, autocommit=True) as c:
            rows = [r[0] for r in c.execute("SELECT row_to_json(m)::text FROM messages m UNION ALL "
                                            "SELECT row_to_json(s)::text FROM steps s").fetchall()]
        return not [r for r in rows if tok in r or tok[-6:] in r]

    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO steps (agent, kind, content) VALUES ('probe', 'milestone', %s)", ("tail " + "zz9" + TG[-6:],))
    arm("E6: the wire instrument fires on a planted tail (a control)", not wire_clean(TG))
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DELETE FROM steps WHERE agent = 'probe'")

    for m, p in (("GET", "/api/channels"), ("POST", "/api/channels/telegram/token"),
                 ("GET", "/api/channels/whatsapp/link"), ("POST", "/api/channels/whatsapp/pair")):
        arm(f"GATE: {m} {p} without the key is 403", cl.request(m, p, json={"token": TG}).status_code == 403)

    def clean(text, tok):
        return tok not in text and tok[-6:] not in text

    # E5: the key is the server's
    r = cl.post("/api/channels/whatsapp/token", json={"token": TG}, headers=O)
    arm("E5: whatsapp has no token route (404), nothing written", r.status_code == 404 and "WA_" not in env.read_text())
    r = cl.post("/api/channels/telegram/token", json={"token": "123:short", "key": "WA_CLI"}, headers=O)
    arm("E5: a malformed token is refused before any call, nothing written", r.status_code == 400 and "TG_BOT_TOKEN" not in env.read_text())
    r = cl.post("/api/channels/telegram/token", json={"token": TG + "\nWA_CLI=evil"}, headers=O)
    arm("E5: a token carrying a newline (the planted-key bypass) is refused", r.status_code == 400 and "WA_CLI" not in env.read_text())

    # E6: every failure mode, then success
    for outcome, code in (("invalid", 400), ("unreachable", 503), ("rate-limited", 503)):
        mode["v"] = outcome
        before = logs.tell()
        r = cl.post("/api/channels/telegram/token", json={"token": TG}, headers=O)
        arm(f"E6: {outcome}: {code}, its own words, nothing written", r.status_code == code and r.json().get("outcome") == outcome
            and "TG_BOT_TOKEN" not in env.read_text(), (r.status_code, r.text))
        arm(f"E6: {outcome}: no token (nor its tail) in the body or the logs",
            clean(r.text, TG) and clean(logs.getvalue()[before:], TG), logs.getvalue()[before:][-400:])
        arm(f"E6: {outcome}: no token (nor its tail) in any row of messages or steps", wire_clean(TG))
    mode["v"] = "ok"
    r = cl.post("/api/channels/telegram/token", json={"token": TG, "key": "WA_CLI"}, headers=O)
    j = r.json()
    arm("E5: a good token is written once, under the table's key (a body key is ignored)",
        r.status_code == 200 and env.read_text().count(f"TG_BOT_TOKEN={TG}\n") == 1 and "WA_CLI" not in env.read_text(), r.text)
    arm("E7: the answer is WRITTEN, names the account and the activation command",
        j.get("state") == "written" and j.get("account") == "@astryx_bot" and "systemctl restart astryx-telegram" in (j.get("activate") or ""), j)
    arm("E6: success: no token in the body or the logs", clean(r.text, TG) and clean(logs.getvalue(), TG), logs.getvalue()[-400:])
    arm("E6: success: no token (nor its tail) in any row of messages or steps", wire_clean(TG))
    arm("E6: httpx's own request log was emitted and scrubbed (the instrument saw it)",
        "api.telegram.org/bot123456789:<redacted>" in logs.getvalue(), logs.getvalue()[-400:])

    TG2 = "123456789:BBH4kq9-YYsecretOTHERvalue_mnopqrstuvwx"
    r = cl.post("/api/channels/telegram/token", json={"token": TG2}, headers=O)
    arm("E5: replacing a set key needs confirm (409 needs_confirm), file untouched",
        r.status_code == 409 and r.json().get("needs_confirm") is True and TG in env.read_text() and TG2 not in env.read_text(), r.text)
    r = cl.post("/api/channels/telegram/token", json={"token": TG2, "replace": True}, headers=O)
    arm("E5: with replace=true it is replaced, the key held once", r.status_code == 200
        and env.read_text().count("TG_BOT_TOKEN=") == 1 and TG2 in env.read_text() and TG not in env.read_text(), env.read_text().count("TG_"))

    r = cl.post("/api/channels/discord/token", json={"token": DC}, headers=O)
    arm("E5: a discord token is written under DISCORD_BOT_TOKEN, with an invite link and no token in the body",
        r.status_code == 200 and f"DISCORD_BOT_TOKEN={DC}" in env.read_text() and "client_id=987654321012345678" in (r.json().get("invite") or "")
        and clean(r.text, DC), r.text)

    # E7: state from the effect's owner
    obs._wa_link = lambda: {"state": "linked", "account": "…0042"}
    obs._account_cache.clear()
    j = {x["channel"]: x for x in cl.get("/api/channels", headers=O).json()}
    arm("E7: a bridge that started BEFORE the token was written is ACTIVATION NEEDED, with the exact command",
        j["telegram"]["state"] == "activation-needed" and j["telegram"]["activate"] == "sudo systemctl restart astryx-telegram.service", j["telegram"])
    obs._bridge = lambda ch: {"unit": f"astryx-{ch}.service", "active": True, "started": time.time() + 5,
                              "health": {"ok": True, "connected": ch != "discord"}}
    j = {x["channel"]: x for x in cl.get("/api/channels", headers=O).json()}
    arm("E7: started after the write and its /health answers: CONNECTED, the account named",
        j["telegram"]["state"] == "connected" and j["telegram"]["account"] == "@astryx_bot", j["telegram"])
    arm("E7: discord's /health says not connected: WRITTEN, never CONNECTED", j["discord"]["state"] == "written", j["discord"])
    arm("E7: whatsapp linked and its bridge healthy: CONNECTED, the number masked", j["whatsapp"]["state"] == "connected"
        and j["whatsapp"]["account"] == "…0042", j["whatsapp"])
    body = json.dumps(j)
    arm("E6: the status answer carries no token", clean(body, TG2) and clean(body, DC))
    obs._bridge = lambda ch: {"unit": f"astryx-{ch}.service", "active": False, "started": 0.0, "health": None}
    j = {x["channel"]: x for x in cl.get("/api/channels", headers=O).json()}
    arm("E7: a bridge never started: ACTIVATION NEEDED, the deploy-and-enable command",
        j["telegram"]["state"] == "activation-needed" and "enable --now astryx-telegram.service" in j["telegram"]["activate"], j["telegram"])

    arm("E6: after the replace, the discord connect and the status reads: neither token in messages or steps",
        wire_clean(TG2) and wire_clean(DC))

    # E8
    r = cl.post("/api/channels/whatsapp/pair", headers=O)
    arm("E8: a LINKED phone is never replaced from here (409, nothing started)", r.status_code == 409 and r.json()["state"] == "linked", r.text)
    obs._wa_link = lambda: {"state": "unknown", "account": None}
    r = cl.post("/api/channels/whatsapp/pair", headers=O)
    arm("E8: an UNKNOWN link state refuses (409)", r.status_code == 409 and r.json()["state"] == "unknown", r.text)
    src = (REPO / "observatory" / "api" / "main.py").read_text()
    tree = ast.parse(src)
    consts = {n.targets[0].id: n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and len(n.targets) == 1
              and getattr(n.targets[0], "id", None) in ("WA_LINK_ARGV", "WA_PAIR_ARGV")}
    arm("E8: both wacli argvs are tuples of string constants",
        len(consts) == 2 and all(isinstance(v, ast.Tuple) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in v.elts)
                                 for v in consts.values()), list(consts))

    # E6: logredact, and the wire never sees a token
    arm("E6: logredact scrubs a bot token URL and a discord webhook URL",
        logredact.scrub(f"https://api.telegram.org/bot{TG}/getMe").endswith("bot123456789:<redacted>/getMe")
        and "SECRET" not in logredact.scrub("https://discord.com/api/webhooks/1/SECRETabc-DEF"))
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                and n.name in ("channels_status", "channel_token", "whatsapp_link", "whatsapp_pair", "_channel_probe", "_account")]
    touch = [n.name for n in handlers if "pool" in {getattr(x, "id", None) for x in ast.walk(n)}]
    arm("E6: no channel handler touches the database (no token can reach the wire or /api/events)",
        len(handlers) == 6 and not touch, (len(handlers), touch))


if __name__ == "__main__":
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = "test-owner-key"
            os.environ["ASTRYX_ORG"] = "fixture.example"
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            main(Path(td), fx["url"])
    except FixtureUnavailable as e:                     # no admin DSN reachable: 77 on a committed-only tree, 1 live
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_floor_s3", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: floor S3 ({fails} failing)")
    sys.exit(1 if fails else 0)
