#!/usr/bin/env python3
"""Oracle: plan-11859 U4, the owner sets this org's agent login from the observatory (GET/POST /api/org/login), the
org-level half of ORGAUTH (goal 10224). The API in process (TestClient) on a throwaway fixture database, its ENV_FILE
pointed at a temp .env this oracle reads back with ITS OWN line parser (never config.read_env, the subject's reader).
Dummy tokens only, fake in shape; every response is searched for them, and a failure detail prints labels, never them.

  L1 owner only: GET and POST without the key are 403, and the .env is byte-for-byte unchanged
  L2 shape: a subscription token that isn't one, an API key that isn't one, a token for the wrong class, a good token
     with anything after it (a quote, a shell expansion, a second `=`; a2 #62549 F-1): 400, nothing written. A token pasted with a terminal's line break in it is the token (written whole, no break)
  L3 subscription: CLAUDE_CODE_OAUTH_TOKEN written, and an earlier opt-in WITHDRAWN (a stale ASTRYX_ORG_LOGIN beside a
     present API key would flip the org to metered later); the answer says subscription and names the key
  L4 replace: a second token with no replace is 409 needs_confirm and the first stays; with replace, the second
  L5 metered: without confirm_billing, 409 needs_billing and NOTHING written (no key, no opt-in); with it, the key AND
     ASTRYX_ORG_LOGIN=ANTHROPIC_API_KEY, and the answer says metered
  L6 ambient: every occurrence of the three keys removed (duplicates included); every other line kept, in order
  L7 an org whose CLI has no launcher (ASTRYX_ORG_CLI=gemini): 409, nothing written
  L8 no response, answer or error, ever carries a token value
  L9 config.unset_env: removes every occurrence, leaves every other byte, keeps mode 600, and says False (writing
     nothing) when the key is absent
Seam: OBS_MAIN_SRC (a mutant main.py), CONFIG_SRC (a mutant config.py). Exit 0 · 1 · 77.
"""
import importlib.util
import os
import stat
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = Path(os.environ.get("OBS_MAIN_SRC") or REPO / "observatory" / "api" / "main.py")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_org_login', REPO, deps=('psycopg', 'asyncpg', 'fastapi'), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

O = {"x-obs-key": "fx-dummy-owner-key-u4"}
TOK = {"sub1": "sk-ant-oat01-" + "fxdummysubscriptiontoken0001",
       "sub2": "sk-ant-oat01-" + "fxdummysubscriptiontoken0002",
       "api1": "sk-ant-api03-" + "fxdummymeteredapikey00000001",
       "old":  "sk-ant-api03-" + "fxdummyolderapikeyvalue00009"}
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            d = str(detail)
            for label, v in (*TOK.items(), ("owner key", O["x-obs-key"])):
                d = d.replace(v, f"<{label}>")
            print(f"        {d}")


def lines(p: Path) -> list[tuple[str, str]]:
    """THIS oracle's reading of a .env: (key, value) per KEY=value line, in order, duplicates kept."""
    out = []
    for ln in p.read_text().splitlines() if p.exists() else []:
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, v = ln.split("=", 1)
            out.append((k.strip(), v))
    return out


def vals(p: Path, key: str) -> list[str]:
    return [v for k, v in lines(p) if k == key]


def load_config():
    src = os.environ.get("CONFIG_SRC")
    if not src:
        from astryx import config
        return config
    m = types.ModuleType("astryx.config")
    m.__file__ = str(REPO / "src/astryx/config.py")
    m.__package__ = "astryx"
    sys.modules["astryx.config"] = m
    import astryx
    astryx.config = m
    exec(compile(Path(src).read_text(), m.__file__, "exec"), m.__dict__)
    return m


def main(tmp: Path):
    config = load_config()
    sys.path.insert(0, str(REPO / "observatory" / "api"))
    subject = SUBJECT
    if os.environ.get("OBS_MAIN_SRC"):
        subject = tmp / "subject" / "observatory" / "api" / "main.py"
        subject.parent.mkdir(parents=True)
        subject.write_text(SUBJECT.read_text())
    spec = importlib.util.spec_from_file_location("main", subject)
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    env = tmp / "org.env"
    obs.ENV_FILE = env
    base = "ASTRYX_ORG=fixture.example\nOBS_KEY=fx-dummy-owner-key-u4\n"
    from fastapi.testclient import TestClient
    seen = []

    def post(body, headers=O):
        r = obs_cl.post("/api/org/login", json=body, headers=headers)
        seen.append(r.text)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}

    with TestClient(obs.app) as obs_cl:
        print("L1 OWNER ONLY")
        env.write_text(base)
        before = env.read_bytes()
        g = obs_cl.get("/api/org/login")
        st, _ = post({"choice": "subscription", "token": TOK["sub1"]}, headers={})
        check("GET and POST without the key: 403, the .env byte-for-byte unchanged",
              g.status_code == 403 and st == 403 and env.read_bytes() == before, f"{g.status_code} {st}")

        print("\nL2 SHAPE")
        for name, body in (("not a token", {"choice": "subscription", "token": "hello"}),
                           ("an API key as the subscription", {"choice": "subscription", "token": TOK["api1"]}),
                           ("a subscription token as the API key", {"choice": "metered", "token": TOK["sub1"],
                                                                    "confirm_billing": True}),
                           ("an unknown choice", {"choice": "free", "token": TOK["sub1"]}),
                           ("a good token with a quote after it", {"choice": "subscription", "token": TOK["sub1"] + '"x'}),
                           ("a good token with a shell expansion after it", {"choice": "subscription",
                                                                             "token": TOK["sub1"] + "$(id)"}),
                           ("a good key with a second assignment after it", {"choice": "metered", "confirm_billing": True,
                                                                             "token": TOK["api1"] + "=X"})):
            st, _ = post(body)
            check(f"{name}: 400, nothing written", st == 400 and env.read_bytes() == before, f"{st}")
        wrapped = TOK["sub1"][:20] + "\n" + TOK["sub1"][20:]
        st, j = post({"choice": "subscription", "token": wrapped})
        check("a token pasted with a line break in it is the token: written whole, no break",
              st == 200 and vals(env, "CLAUDE_CODE_OAUTH_TOKEN") == [TOK["sub1"]], f"{st} {j}")

        print("\nL3 SUBSCRIPTION WITHDRAWS AN OPT-IN")
        env.write_text(base + f"ANTHROPIC_API_KEY={TOK['old']}\nASTRYX_ORG_LOGIN=ANTHROPIC_API_KEY\n")
        st, j = post({"choice": "subscription", "token": TOK["sub1"]})
        login = j.get("login", {})
        check("CLAUDE_CODE_OAUTH_TOKEN written; ASTRYX_ORG_LOGIN removed",
              st == 200 and vals(env, "CLAUDE_CODE_OAUTH_TOKEN") == [TOK["sub1"]] and not vals(env, "ASTRYX_ORG_LOGIN"),
              f"{st} {lines(env)}")
        check("the answer: billing subscription, the key by NAME, and when it applies",
              login.get("billing") == "subscription" and login.get("key") == "CLAUDE_CODE_OAUTH_TOKEN"
              and "next spawn" in j.get("applies", ""), str(j))

        print("\nL4 REPLACE")
        st, j = post({"choice": "subscription", "token": TOK["sub2"]})
        check("a second token, no replace: 409 needs_confirm, the first stays",
              st == 409 and j.get("needs_confirm") and vals(env, "CLAUDE_CODE_OAUTH_TOKEN") == [TOK["sub1"]], f"{st}")
        st, j = post({"choice": "subscription", "token": TOK["sub2"], "replace": True})
        check("with replace: the second, once", st == 200 and vals(env, "CLAUDE_CODE_OAUTH_TOKEN") == [TOK["sub2"]],
              f"{st}")

        print("\nL5 METERED NEEDS THE BILLING CONFIRMED")
        env.write_text(base)
        st, j = post({"choice": "metered", "token": TOK["api1"]})
        check("no confirm_billing: 409 needs_billing, NOTHING written (no key, no opt-in)",
              st == 409 and j.get("needs_billing") and env.read_text() == base, f"{st} {lines(env)}")
        st, j = post({"choice": "metered", "token": TOK["api1"], "confirm_billing": True})
        check("confirmed: the key AND ASTRYX_ORG_LOGIN=ANTHROPIC_API_KEY; the answer says metered",
              st == 200 and vals(env, "ANTHROPIC_API_KEY") == [TOK["api1"]]
              and vals(env, "ASTRYX_ORG_LOGIN") == ["ANTHROPIC_API_KEY"]
              and j.get("login", {}).get("billing") == "metered", f"{st} {j}")

        print("\nL6 AMBIENT")
        env.write_text(base + f"CLAUDE_CODE_OAUTH_TOKEN={TOK['sub1']}\nKEEP_ME=1\nANTHROPIC_API_KEY={TOK['api1']}\n"
                       f"ASTRYX_ORG_LOGIN=ANTHROPIC_API_KEY\nCLAUDE_CODE_OAUTH_TOKEN={TOK['sub2']}\n")
        st, j = post({"choice": "ambient"})
        check("every occurrence of the three keys removed; every other line kept, in order",
              st == 200 and lines(env) == [("ASTRYX_ORG", "fixture.example"), ("OBS_KEY", "fx-dummy-owner-key-u4"),
                                           ("KEEP_ME", "1")] and j.get("login", {}).get("billing") == "ambient",
              f"{st} {lines(env)}")
        g = obs_cl.get("/api/org/login", headers=O)
        seen.append(g.text)
        check("GET (owner): the ambient login, by name", g.status_code == 200 and g.json().get("billing") == "ambient",
              g.text[:120])

        print("\nL7 A CLI WITH NO LAUNCHER")
        env.write_text(base + "ASTRYX_ORG_CLI=gemini\n")
        before = env.read_bytes()
        st, _ = post({"choice": "subscription", "token": TOK["sub1"]})
        check("ASTRYX_ORG_CLI=gemini: 409, nothing written", st == 409 and env.read_bytes() == before, f"{st}")

        print("\nL8 NO VALUE IN ANY ANSWER")
        leaked = [label for label, v in TOK.items() if any(v in t for t in seen)]
        check(f"none of {len(seen)} responses carries a token value", not leaked, str(leaked))

    print("\nL9 config.unset_env")
    f = tmp / "unset.env"
    f.write_text("A=1\nGONE=x\nB=2\nGONE=y\n# GONE=comment\n")
    os.chmod(f, 0o644)
    r = config.unset_env("GONE", f)
    check("every occurrence removed, every other byte kept, mode 600, True",
          r is True and f.read_text() == "A=1\nB=2\n# GONE=comment\n" and stat.S_IMODE(f.stat().st_mode) == 0o600,
          repr(f.read_text()))
    before = f.read_bytes()
    check("an absent key: False, nothing written", config.unset_env("NEVER", f) is False and f.read_bytes() == before)
    check("set_env after the refactor: one line per key, replaced in place",
          (config.set_env("A", "3", f), f.read_text())[1] == "A=3\nB=2\n# GONE=comment\n", repr(f.read_text()))


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    with tempfile.TemporaryDirectory() as td:
        os.environ["ASTRYX_COG_REGISTRY"] = str(Path(td) / "absent.json")   # one org, never the host's registry
        try:
            with fixture_db() as fx:
                os.environ["ASTRYX_DSN"] = fx["url"]
                os.environ["OBS_KEY"] = "fx-dummy-owner-key-u4"
                os.environ["ASTRYX_ORG"] = "fixture.example"
                os.environ["ASTRYX_GATEWAY_PORT"] = "9"
                main(Path(td))
        except FixtureUnavailable as e:
            unavailable("test_org_login", REPO, e)
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the owner sets this org's agent login; a metered "
          "key only with the billing confirmed; never a value back")
    sys.exit(1 if fails else 0)
