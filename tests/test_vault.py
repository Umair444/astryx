#!/usr/bin/env python3
"""Oracle: Harness and Keys (docs/superpowers/specs/2026-11-16-harness-and-keys-design.md): the catalog
(src/astryx/core/catalog.py), the keys (src/astryx/core/vault.py), the routes (observatory/api/vault.py) and an agent's
connection (runtime_env). Temp estate, synthetic values only; the routes are called directly; no network (a provider's
check is stubbed).
  F1 fit comes from the tables: Claude Code takes a Claude login and every Anthropic-format key (Anthropic, DeepSeek,
     OpenRouter, a custom Anthropic endpoint); not OpenAI's or Gemini's; Codex takes OpenAI's
  R1 a login gives CLAUDE_CODE_OAUTH_TOKEN; an Anthropic key ANTHROPIC_API_KEY; DeepSeek its catalog endpoint, its token
     and its tier models; a custom endpoint its own URL; the agent's own tier choice wins over the key's
  R3 one login live in the session: every other auth variable the harness reads is set empty
  R2 a key with no value in .env falls back to the org's login, never a half-configured endpoint
  L1 an entry from before the catalog loads as its provider (login -> claude, key -> anthropic or custom)
  A1 not the owner: 403 before anything is read
  A2 add a login: its value lands in .env under the DERIVED key and is in no response; a value of the wrong shape, a
     metered key with no cap, a custom endpoint with no https address, an unknown provider, a new one without a value,
     a key its provider rejects: refused, nothing written
  A3 a second name folding to a held key: 409; a change keeps the old value unless a new one is given (a rotation)
  C1 connections: an agent onto a login, everyone else ('*') onto one; an agent with its own entry keeps it, "its own on
     the org's login" too (never everyone else's key); an empty
     connection removes it; a key that doesn't fit the harness, a harness with no launcher, a metered key (its cap isn't
     enforced yet), an unknown agent: refused
  C4 an API key asks for the owner's billing confirm (needs_billing, its cap named) before an agent is put on it
  C5 spawn stamps the session with the key it runs on (ASTRYX_RUN_ON -> turns.run_on)
  C6 the daily cap at spawn (runtime_env.key_cap): under it starts, at it refuses, an unreadable spend refuses
  C2 login_of reads the agent's own connection, else everyone else's (the energy and the usage reading follow it)
  C3 the launch line runs the connection's model over the charter's
  A4 remove: refused while an agent (or everyone else) runs on it; then removed, its .env key gone
Exit 0 · 1."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "src"))
from astryx import config  # noqa: E402
from astryx.core import catalog as C  # noqa: E402
from astryx.core import cli_adapters  # noqa: E402
from astryx.core import vault as V  # noqa: E402
from astryx.core import runtime_env as RE  # noqa: E402
from observatory.api import vault as API  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


LOGIN = "sk-ant-oat01-" + "L" * 40
AKEY = "sk-ant-api03-" + "K" * 40
DKEY = "sk-" + "d" * 32
GKEY = "gw_" + "G" * 30
AUTH = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
ROSTER = {"db", "lending", "seed"}
CHECKED = {}
REAL_CHECK = C.check


def _check(pid, value, timeout=8, cat=None):   # the provider's answer, without the network: a value ending BAD is rejected
    if not C.providers()[pid].get("check"):
        return REAL_CHECK(pid, value)               # no check declared: the real one answers 'unchecked' without a call
    CHECKED[pid] = "rejected" if value.endswith("BAD") else "ok"
    return CHECKED[pid]


C.check = _check


class Req:
    pass


def call(fn, *a, owner=True):
    API.bind(lambda r: owner, EST, roster=lambda: ROSTER, alive=lambda: set())
    r = asyncio.run(fn(*a, Req()))
    return (200, r) if isinstance(r, dict) else (r.status_code, json.loads(r.body))


H = cli_adapters.load()
claude, codex = H["claude"], H["codex"]
fit = {p: C.fits(claude, p, {"format": "anthropic"}) for p in C.providers()}
arm("F1 Claude Code takes a Claude login and every Anthropic-format key",
    all(fit[p] for p in ("claude", "anthropic", "deepseek", "openrouter", "custom")), fit)
arm("F1 …and not OpenAI's, Gemini's, or a ChatGPT login", not any(fit[p] for p in ("openai", "gemini", "chatgpt", "google")), fit)
arm("F1 Codex takes OpenAI's key and the ChatGPT login", C.fits(codex, "openai") and C.fits(codex, "chatgpt") and not C.fits(codex, "claude"))

with tempfile.TemporaryDirectory() as td:
    EST = Path(td)
    (EST / ".env").write_text("ASTRYX_DSN=postgres://x\n")
    RE.paths.estate = lambda f=None: EST

    st, b = call(API.harness_get, owner=False)
    arm("A1 not the owner: 403", st == 403)
    st, b = call(API.key_put, "Work login", API.Key(provider="claude", value=LOGIN))
    env = config.read_env(EST / ".env")
    arm("A2 a login: its value under the derived key, and in no response", st == 200 and env.get("ASTRYX_CRED_WORK_LOGIN") == LOGIN and LOGIN not in json.dumps(b, default=str), (st, b))
    for bad, why in ((API.Key(provider="claude", value="nope"), "a wrong shape"),
                     (API.Key(provider="anthropic", value=AKEY), "a metered key with no cap"),
                     (API.Key(provider="custom", format="anthropic", cap_tokens_day=9, value=GKEY), "a custom endpoint with no address"),
                     (API.Key(provider="nobody", value=GKEY), "an unknown provider"),
                     (API.Key(provider="deepseek", cap_tokens_day=1000), "a new one without a value"),
                     (API.Key(provider="deepseek", cap_tokens_day=1000, value="sk-" + "x" * 30 + "BAD"), "a key its provider rejects")):
        before = (EST / ".env").read_text()
        st, b = call(API.key_put, "Other", bad)
        arm(f"A2 refused: {why}, nothing written", st in (400, 409) and (EST / ".env").read_text() == before and "Other" not in V.load(EST), (st, b))
    st, b = call(API.key_put, "work-login", API.Key(provider="claude", value=LOGIN))
    arm("A3 a second name folding to a held key: 409", st == 409, (st, b))
    st, b = call(API.key_put, "Work login", API.Key(provider="claude"))
    arm("A3 a change without a value keeps the old one", st == 200 and config.read_env(EST / ".env").get("ASTRYX_CRED_WORK_LOGIN") == LOGIN)
    call(API.key_put, "Gateway", API.Key(provider="custom", format="anthropic", base_url="https://gw.example.com/anthropic",
                                         cap_tokens_day=500000, value=GKEY, models={"opus": "glm-5"}))
    call(API.key_put, "Anthropic API", API.Key(provider="anthropic", cap_tokens_day=100000, value=AKEY))
    call(API.key_put, "DeepSeek", API.Key(provider="deepseek", cap_tokens_day=100000, value=DKEY))
    arm("A2 a key its provider can check was checked", CHECKED.get("anthropic") == "ok" and CHECKED.get("deepseek") == "ok", CHECKED)

    env, vault = config.read_env(EST / ".env"), V.load(EST)
    p = lambda n: {k: v for k, v in V.pairs(n, vault[n], env) if v}   # noqa: E731  the non-empty ones
    blank = lambda n: {k for k, v in V.pairs(n, vault[n], env) if not v}   # noqa: E731
    arm("R1 a login gives CLAUDE_CODE_OAUTH_TOKEN", p("Work login") == {"CLAUDE_CODE_OAUTH_TOKEN": LOGIN}, p("Work login"))
    arm("R1 an Anthropic key gives ANTHROPIC_API_KEY", p("Anthropic API") == {"ANTHROPIC_API_KEY": AKEY}, p("Anthropic API"))
    ds = p("DeepSeek")
    arm("R1 DeepSeek: its catalog endpoint, its token, its tier models",
        ds.get("ANTHROPIC_BASE_URL") == "https://api.deepseek.com/anthropic" and ds.get("ANTHROPIC_AUTH_TOKEN") == DKEY
        and ds.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "deepseek-chat", ds)
    arm("R1 a custom endpoint: its own URL, its token, its models", p("Gateway") == {"ANTHROPIC_BASE_URL": "https://gw.example.com/anthropic", "ANTHROPIC_AUTH_TOKEN": GKEY, "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5"}, p("Gateway"))
    for n in ("Work login", "Anthropic API", "Gateway", "DeepSeek"):
        auth = {k for k in AUTH if k in p(n) and k != "ANTHROPIC_BASE_URL"}
        arm(f"R3 {n}: exactly one way to authenticate is non-empty, every other is set empty (medic 12468)",
            len(auth) == 1 and set(AUTH) - set(p(n)) <= blank(n), (auth, blank(n)))
    frag = json.loads("{" + RE._pairs("db", {"credential": "Gateway", "models": {"opus": "my-opus"}}, env)[1:] + "}")
    arm("R1 the agent's own tier choice wins over the key's", frag.get("ANTHROPIC_DEFAULT_OPUS_MODEL") == "my-opus" and frag.get("ANTHROPIC_AUTH_TOKEN") == GKEY, frag)
    env2 = {k: v for k, v in env.items() if k != "ASTRYX_CRED_GATEWAY"}
    out = RE._pairs("db", {"credential": "Gateway"}, env2)
    arm("R2 a key with no value falls back to the org's login: no endpoint, no empty token", "ANTHROPIC_BASE_URL" not in out and "AUTH_TOKEN" not in out, out)

    legacy = {"credentials": {"Old login": {"kind": "login", "base_url": "", "models": {}},
                              "Old key": {"kind": "key", "base_url": "", "models": {}, "cap_tokens_day": 5},
                              "Old gw": {"kind": "key", "base_url": "https://gw.example.com", "models": {}, "cap_tokens_day": 5}}}
    with tempfile.TemporaryDirectory() as td2:
        (Path(td2) / "credentials.json").write_text(json.dumps(legacy))
        old = V.load(Path(td2))
        arm("L1 a pre-catalog entry loads as its provider", {n: (e["provider"], e["kind"]) for n, e in old.items()} ==
            {"Old login": ("claude", "login"), "Old key": ("anthropic", "key"), "Old gw": ("custom", "key")}, old)

    st, b = call(API.connection_put, "db", API.Connection(credential="Work login"))
    arm("C1 an agent onto a login", st == 200 and json.loads((EST / "runtime.json").read_text())["db"] == {"credential": "Work login"}, (st, b))
    st, b = call(API.connection_put, "*", API.Connection(credential="Work login", model="sonnet"))
    view = {a["name"]: a for a in b["agents"]}
    arm("C1 everyone else onto a login; an agent with its own keeps it", st == 200 and view["lending"]["connection"] == {"credential": "Work login", "model": "sonnet"}
        and not view["lending"]["own"] and view["db"]["own"] and view["db"]["connection"] == {"credential": "Work login"}, (st, view))
    st, b = call(API.connection_put, "seed", API.Connection(harness="claude"))
    arm("C1 its own, on the org's login: kept as its own, never everyone else's key", st == 200
        and V.connection(json.loads((EST / "runtime.json").read_text()), "seed") == {"harness": "claude"}
        and V.login_of(EST, "seed") == (None, None), (st, V.login_of(EST, "seed")))
    st, b = call(API.connection_put, "lending", API.Connection(credential="DeepSeek"))
    arm("C4 an API key asks for the owner's billing confirm first, naming its cap; nothing written",
        st == 409 and b.get("needs_billing") and "100,000" in b["error"] and "lending" not in json.loads((EST / "runtime.json").read_text()), (st, b))
    st, b = call(API.connection_put, "lending", API.Connection(credential="DeepSeek", confirm_billing=True))
    arm("C4 …confirmed: connected", st == 200 and json.loads((EST / "runtime.json").read_text())["lending"] == {"credential": "DeepSeek"}, (st, b))
    st, b = call(API.connection_put, "lending", API.Connection(credential="DeepSeek", model="deepseek-reasoner"))
    arm("C4 …a change on the same key asks again for nothing", st == 200, (st, b))
    frag = json.loads("{" + RE._pairs("lending", RE.connection("lending"), config.read_env(EST / ".env"))[1:] + "}")
    arm("C5 the session is stamped with the key it runs on (ASTRYX_RUN_ON: its turns count against it)",
        frag.get("ASTRYX_RUN_ON") == "DeepSeek" and frag.get("ANTHROPIC_AUTH_TOKEN") == DKEY, frag)
    import psycopg
    from astryx.econ import energy as En
    real_connect, real_spent = psycopg.connect, En.spent

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    psycopg.connect = lambda *a, **k: _C()
    try:
        En.spent = lambda c, key, now=None: 99_999.0
        arm("C6 under its cap: the agent may start", RE.key_cap("lending") is None)
        En.spent = lambda c, key, now=None: 100_000.0
        why = RE.key_cap("lending") or ""
        arm("C6 at its cap: it isn't started, and the gate says so", "daily cap" in why and "midnight" in why, why)
        def boom(c, key, now=None): raise OSError("db down")
        En.spent = boom
        arm("C6 a spend that can't be read refuses (unknown is never under the cap)", "can't be read" in (RE.key_cap("lending") or ""))
        arm("C6 an agent on a login has no cap", RE.key_cap("db") is None)
    finally:
        psycopg.connect, En.spent = real_connect, real_spent
    call(API.connection_put, "lending", API.Connection())
    for agent, c, why in (("db", API.Connection(harness="codex", credential="Work login"), "a harness with no launcher"),
                          ("ghost", API.Connection(credential="Work login"), "an unknown agent"),
                          ("db", API.Connection(credential="Nope"), "a key that isn't in the vault")):
        st, b = call(API.connection_put, agent, c)
        arm(f"C1 refused: {why}", st in (400, 404, 409), (st, b))
    V.save(EST, {**V.load(EST), "OpenAI": V.entry("OpenAI", "openai", cap=5)})
    st, b = call(API.connection_put, "db", API.Connection(credential="OpenAI"))
    arm("C1 refused: a key that doesn't fit the harness", st == 409 and "can't use" in b["error"], (st, b))
    arm("C2 login_of: the agent's own connection", V.login_of(EST, "db") == ("Work login", LOGIN))
    arm("C2 login_of: everyone else's when it has none", V.login_of(EST, "lending") == ("Work login", LOGIN))
    st, b = call(API.connection_put, "db", API.Connection())
    arm("C1 an empty connection removes the agent's own", st == 200 and "db" not in json.loads((EST / "runtime.json").read_text()), (st, b))
    arm("C3 the launch line runs the connection's model", RE.connection("lending").get("model") == "sonnet")

    st, b = call(API.key_delete, "Work login")
    arm("A4 remove refused while everyone else runs on it, naming them", st == 409 and "everyone else" in b["error"], (st, b))
    call(API.connection_put, "*", API.Connection())
    st, b = call(API.key_delete, "Gateway")
    arm("A4 then removed, its .env key gone", st == 200 and "ASTRYX_CRED_GATEWAY" not in config.read_env(EST / ".env") and "Gateway" not in V.load(EST), (st, b))
    arm("A2 the vault file is 0600 and holds no value", (V.path(EST).stat().st_mode & 0o777) == 0o600 and LOGIN not in V.path(EST).read_text())

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: keys name what the org holds, .env holds their values, a connection puts an agent on one")
sys.exit(1 if fails else 0)
