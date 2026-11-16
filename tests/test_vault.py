#!/usr/bin/env python3
"""Oracle: the vault (src/astryx/core/vault.py), its routes (observatory/api/vault.py) and an agent's connection to a
credential (runtime_env). Temp estate, synthetic values only; the routes are called directly.
  R1 a login gives the agent CLAUDE_CODE_OAUTH_TOKEN; an Anthropic key ANTHROPIC_API_KEY; a key with an endpoint the
     base URL and ANTHROPIC_AUTH_TOKEN; the credential's models, and the agent's own model choice over them
  R2 a credential with no value in .env falls back to the org's login, never a half-configured endpoint
  A1 not the owner: 403 before anything is read
  A2 add a login: its value lands in .env under the DERIVED key and is in no response; a value of the wrong shape, a
     key with no daily cap, a login with an endpoint, a new one without a value: refused, nothing written
  A3 a second name folding to a held key: 409; a change keeps the old value unless a new one is given (a rotation)
  A4 remove: refused while an agent uses it; then removed, its .env key gone
Exit 0 · 1."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "src"))
from astryx import config  # noqa: E402
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
GKEY = "gw_" + "G" * 30


class Req:
    pass


def call(fn, *a, owner=True):
    API.bind(lambda r: owner, EST)
    r = asyncio.run(fn(*a, Req()))
    return (200, r) if isinstance(r, dict) else (r.status_code, json.loads(r.body))


with tempfile.TemporaryDirectory() as td:
    EST = Path(td)
    (EST / ".env").write_text("ASTRYX_DSN=postgres://x\n")
    st, b = call(API.vault_get, owner=False)
    arm("A1 not the owner: 403", st == 403)
    st, b = call(API.vault_put, "Work login", API.Cred(kind="login", value=LOGIN))
    env = config.read_env(EST / ".env")
    arm("A2 a login: its value under the derived key, and in no response", st == 200 and env.get("ASTRYX_CRED_WORK_LOGIN") == LOGIN and LOGIN not in json.dumps(b), (st, b))
    for bad, why in ((API.Cred(kind="login", value="nope"), "a wrong shape"), (API.Cred(kind="key", value=AKEY), "a key with no cap"),
                     (API.Cred(kind="login", base_url="https://x.example", value=LOGIN), "a login with an endpoint"),
                     (API.Cred(kind="key", cap_tokens_day=1000), "a new one without a value")):
        before = (EST / ".env").read_text()
        st, b = call(API.vault_put, "Other", bad)
        arm(f"A2 refused: {why}, nothing written", st in (400, 409) and (EST / ".env").read_text() == before and "Other" not in V.load(EST), (st, b))
    st, b = call(API.vault_put, "work-login", API.Cred(kind="login", value=LOGIN))
    arm("A3 a second name folding to a held key: 409", st == 409, (st, b))
    st, b = call(API.vault_put, "Work login", API.Cred(kind="login"))
    arm("A3 a change without a value keeps the old one", st == 200 and config.read_env(EST / ".env").get("ASTRYX_CRED_WORK_LOGIN") == LOGIN)
    call(API.vault_put, "Gateway", API.Cred(kind="key", base_url="https://gw.example.com/anthropic", cap_tokens_day=500000, value=GKEY, models={"opus": "glm-5"}))
    call(API.vault_put, "Anthropic API", API.Cred(kind="key", cap_tokens_day=100000, value=AKEY))
    env = config.read_env(EST / ".env")
    vault = V.load(EST)
    p = lambda n: dict(V.pairs(n, vault[n], env))   # noqa: E731
    arm("R1 a login gives CLAUDE_CODE_OAUTH_TOKEN", p("Work login") == {"CLAUDE_CODE_OAUTH_TOKEN": LOGIN})
    arm("R1 an Anthropic key gives ANTHROPIC_API_KEY", p("Anthropic API") == {"ANTHROPIC_API_KEY": AKEY})
    arm("R1 a key with an endpoint gives its URL, ANTHROPIC_AUTH_TOKEN and its models", p("Gateway") == {"ANTHROPIC_BASE_URL": "https://gw.example.com/anthropic", "ANTHROPIC_AUTH_TOKEN": GKEY, "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5"}, p("Gateway"))
    RE.paths.estate = lambda f=None: EST
    frag = json.loads("{" + RE._pairs("db", {"credential": "Gateway", "models": {"opus": "my-opus"}}, env)[1:] + "}")
    arm("R1 the agent's own model choice wins over the credential's", frag.get("ANTHROPIC_DEFAULT_OPUS_MODEL") == "my-opus" and frag.get("ANTHROPIC_AUTH_TOKEN") == GKEY, frag)
    env2 = {k: v for k, v in env.items() if k != "ASTRYX_CRED_GATEWAY"}
    out = RE._pairs("db", {"credential": "Gateway"}, env2)
    arm("R2 a credential with no value falls back to the org's login: no endpoint, no empty token", "ANTHROPIC_BASE_URL" not in out and "AUTH_TOKEN" not in out, out)
    (EST / "runtime.json").write_text(json.dumps({"db": {"credential": "Gateway"}}))
    st, b = call(API.vault_delete, "Gateway")
    arm("A4 remove refused while an agent uses it, naming it", st == 409 and "db" in b["error"], (st, b))
    (EST / "runtime.json").write_text("{}")
    st, b = call(API.vault_delete, "Gateway")
    arm("A4 then removed, its .env key gone", st == 200 and "ASTRYX_CRED_GATEWAY" not in config.read_env(EST / ".env") and "Gateway" not in V.load(EST), (st, b))
    arm("A2 the vault file is 0600 and holds no value", (V.path(EST).stat().st_mode & 0o777) == 0o600 and LOGIN not in V.path(EST).read_text())

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the vault names credentials, .env holds their values")
sys.exit(1 if fails else 0)
