#!/usr/bin/env python3
"""Oracle: each org of a cog runs its agents on ITS OWN login (plan-10224 ORGAUTH, owner 10-21; seed #61870, #61871,
#61876). src/astryx/core/runtime_env.py splices the org's credential (its HOME .env's CLAUDE_CODE_OAUTH_TOKEN |
ANTHROPIC_API_KEY, by the CLIS row of its ASTRYX_ORG_CLI) beneath the per-agent runtime.json entry.

Fixture: a registry of two orgs (fxa, fxb), each HOME with its own .env holding DUMMY tokens only. Every arm asserts on
key NAMES and on WHICH org's dummy landed; no value is ever printed (a detail names keys, or says "A's"/"B's").
  O1 org token used: an agent with no entry gets its org's CLAUDE_CODE_OAUTH_TOKEN; ANTHROPIC_API_KEY when it is the
     only one; the OAuth token first when both are set
  O2 the agent entry wins: an entry with its own base_url gets its ANTHROPIC_AUTH_TOKEN and NO org key; an entry with
     only a model map or an effort gets the org key beside them
  O3 no token, unchanged: an org whose .env holds no login key renders the fragment the pre-ORGAUTH code did, byte for
     byte (no file, an effort-only entry, a base_url entry)
  O4 cross-org: fxb's agent never gets fxa's credential, and with both set each gets its own
  O5 the parent env: fxa's credential in the PARENT process env, fxb rendered: fxb's fragment holds none of it, and
     fxb's pane environment (orgenv.py exec, what spawn's tmux pane runs) carries neither name
  O6 never a value out of band: `--org` prints NAMES only; stderr never holds a dummy
  O7 a CLI with no launcher (ASTRYX_ORG_CLI=gemini): exit 3, "cli gemini not yet supported", nothing on stdout
Seams: ORGAUTH_SRC (a mutant runtime_env.py, tests/mutants_org_auth.py). Exit 0 · 1 · 77 (no psycopg: O5's pane
arm can't run).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("ORGAUTH_SRC") or REPO / "src" / "astryx" / "core" / "runtime_env.py")
DUMMY = {"a": "fx-dummy-oauth-a-0001", "b": "fx-dummy-oauth-b-0002", "ka": "fx-dummy-apikey-a-0003",
         "entry": "fx-dummy-entry-a-0004"}
LOGIN_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
fails = []
skipped = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def whose(text: str) -> list[str]:
    """Which dummies appear in `text`, by label, never by value."""
    return sorted(k for k, v in DUMMY.items() if v in text)


def parse(frag: str) -> dict | None:
    try:
        return json.loads("{" + frag.lstrip(", ") + "}") if frag else {}
    except ValueError:
        return None


with tempfile.TemporaryDirectory() as td:
    t = Path(td).resolve()
    H = {o: t / f"home-{o}" for o in ("a", "b")}
    for h in H.values():
        h.mkdir()
    reg = t / "cog.json"
    reg.write_text(json.dumps({"orgs": {f"fx{o}": {"home": str(h), "db": f"fxauth_{o}"} for o, h in H.items()}}))

    def dotenv(o, *lines):
        (H[o] / ".env").write_text(f"ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/fxauth_{o}\nASTRYX_ORG={o}.fixture.test\n"
                                   + "".join(f"{ln}\n" for ln in lines))

    def runtime(o, cfg):
        f = H[o] / "runtime.json"
        f.unlink(missing_ok=True)
        if cfg is not None:
            f.write_text(json.dumps(cfg))

    def run(o, agent="zzauth", parent=None):
        # own-env: the child's registry and HOME are named here; ASTRYX_* and every login key are dropped first
        env = {k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_") and k not in LOGIN_KEYS
               and not k.startswith("CLAUDE_CODE_")}
        env.update(parent or {})
        env.update(ASTRYX_COG_REGISTRY=str(reg), ASTRYX_HOME=str(H[o]), PYTHONPATH=str(REPO / "src"))
        r = subprocess.run([sys.executable, str(SRC), agent], capture_output=True, text=True, env=env, timeout=60)
        return r.returncode, r.stdout, r.stderr

    print("O1 THE ORG'S TOKEN, FOR AN AGENT WITH NO ENTRY")
    dotenv("a", f"CLAUDE_CODE_OAUTH_TOKEN={DUMMY['a']}")
    dotenv("b")
    runtime("a", None)
    rc, out, err = run("a")
    got = parse(out)
    check("no runtime.json: fxa's agent gets CLAUDE_CODE_OAUTH_TOKEN, fxa's own", rc == 0 and got is not None
          and got.get("CLAUDE_CODE_OAUTH_TOKEN") == DUMMY["a"] and set(got) == {"CLAUDE_CODE_OAUTH_TOKEN"},
          f"rc {rc} keys {sorted(got or {})} whose {whose(out)}")
    runtime("a", {"other": {"effort": "low"}})
    rc, out, err = run("a")
    got = parse(out)
    check("a runtime.json with no entry for it: the same", rc == 0 and got is not None
          and got.get("CLAUDE_CODE_OAUTH_TOKEN") == DUMMY["a"], f"rc {rc} keys {sorted(got or {})}")
    dotenv("a", f"ANTHROPIC_API_KEY={DUMMY['ka']}")
    rc, out, err = run("a")
    got = parse(out)
    check("only ANTHROPIC_API_KEY in the .env: that key", rc == 0 and got is not None
          and got.get("ANTHROPIC_API_KEY") == DUMMY["ka"] and "CLAUDE_CODE_OAUTH_TOKEN" not in got,
          f"rc {rc} keys {sorted(got or {})}")
    dotenv("a", f"ANTHROPIC_API_KEY={DUMMY['ka']}", f"CLAUDE_CODE_OAUTH_TOKEN={DUMMY['a']}")
    rc, out, err = run("a")
    got = parse(out)
    check("both set: the OAuth token (CLIS order), and only it", rc == 0 and got is not None
          and got.get("CLAUDE_CODE_OAUTH_TOKEN") == DUMMY["a"] and "ANTHROPIC_API_KEY" not in got,
          f"rc {rc} keys {sorted(got or {})}")

    print("\nO2 THE AGENT ENTRY WINS")
    dotenv("a", f"CLAUDE_CODE_OAUTH_TOKEN={DUMMY['a']}", f"FX_ENTRY_TOKEN={DUMMY['entry']}")
    runtime("a", {"zzauth": {"base_url": "https://example.invalid/anthropic", "token_env": "FX_ENTRY_TOKEN"}})
    rc, out, err = run("a")
    got = parse(out)
    check("an entry with its own base_url: its ANTHROPIC_AUTH_TOKEN, and NO org key", rc == 0 and got is not None
          and got.get("ANTHROPIC_AUTH_TOKEN") == DUMMY["entry"] and not set(LOGIN_KEYS) & set(got)
          and whose(out) == ["entry"], f"rc {rc} keys {sorted(got or {})} whose {whose(out)}")
    runtime("a", {"zzauth": {"effort": "high", "models": {"opus": "fx-model"}}})
    rc, out, err = run("a")
    got = parse(out)
    check("an entry with only effort and a model map: the org key beside them", rc == 0 and got is not None
          and got.get("CLAUDE_CODE_OAUTH_TOKEN") == DUMMY["a"] and got.get("CLAUDE_CODE_EFFORT_LEVEL") == "high"
          and got.get("ANTHROPIC_DEFAULT_OPUS_MODEL") == "fx-model", f"rc {rc} keys {sorted(got or {})}")

    print("\nO3 NO TOKEN: THE FRAGMENT THE PRE-ORGAUTH CODE RENDERED, BYTE FOR BYTE")
    dotenv("b", f"FX_ENTRY_TOKEN={DUMMY['entry']}")
    for label, cfg, want in (
            ("no runtime.json", None, ""),
            ("an effort-only entry", {"zzauth": {"effort": "high"}}, ', "CLAUDE_CODE_EFFORT_LEVEL": "high"'),
            ("a base_url entry", {"zzauth": {"base_url": "https://example.invalid/x", "token_env": "FX_ENTRY_TOKEN"}},
             f', "ANTHROPIC_BASE_URL": "https://example.invalid/x", "ANTHROPIC_AUTH_TOKEN": "{DUMMY["entry"]}"')):
        runtime("b", cfg)
        rc, out, err = run("b")
        check(f"{label}: identical", rc == 0 and out == want, f"rc {rc} keys {sorted(parse(out) or {})}")
    runtime("b", None)

    print("\nO4 CROSS-ORG")
    dotenv("a", f"CLAUDE_CODE_OAUTH_TOKEN={DUMMY['a']}")
    dotenv("b")
    rc, out, err = run("b")
    check("fxa holds a token, fxb none: fxb's agent gets no login key and none of fxa's", rc == 0 and out == ""
          and whose(out + err) == [], f"rc {rc} whose {whose(out + err)}")
    dotenv("b", f"CLAUDE_CODE_OAUTH_TOKEN={DUMMY['b']}")
    rc_a, out_a, _ = run("a")
    rc_b, out_b, _ = run("b")
    check("both hold one: each org's agent gets its OWN", rc_a == rc_b == 0 and whose(out_a) == ["a"]
          and whose(out_b) == ["b"], f"a {whose(out_a)} b {whose(out_b)}")

    print("\nO5 THE PARENT ENV CARRIES fxa's CREDENTIAL; fxb IS RENDERED")
    dotenv("b")
    parent = {"CLAUDE_CODE_OAUTH_TOKEN": DUMMY["a"], "ANTHROPIC_API_KEY": DUMMY["ka"]}
    rc, out, err = run("b", parent=parent)
    check("fxb's fragment holds none of it (the .env FILE is read, never the process env)", rc == 0 and out == ""
          and whose(out + err) == [], f"rc {rc} whose {whose(out + err)}")
    penv = {k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_") and k not in LOGIN_KEYS}
    penv.update(parent, ASTRYX_COG_REGISTRY=str(reg), ASTRYX_HOME=str(H["b"]))
    r = subprocess.run([sys.executable, str(REPO / "src" / "astryx" / "orgenv.py"), "exec", "--home", str(H["b"]),
                        "--agent", "zzauth", "--", sys.executable, "-c", "import os; print('\\n'.join(sorted(os.environ)))"],
                       capture_output=True, text=True, env=penv, timeout=60)
    names = set(r.stdout.split())
    if importlib.util.find_spec("psycopg") is None:          # orgenv checks the DSN with psycopg's conninfo parser
        print("  SKIP  fxb's pane environment (orgenv exec): no psycopg in this interpreter — NOT RUN, never a pass")
        skipped.append("O5 pane")
    else:
            check("fxb's pane environment (orgenv exec) carries neither name, nor any of fxa's values",
              r.returncode == 0 and "ASTRYX_HOME" in names and not set(LOGIN_KEYS) & names and whose(r.stdout) == [],
              f"rc {r.returncode} leaked {sorted(set(LOGIN_KEYS) & names)} {r.stderr.strip()[-200:]}")

    print("\nO6 NEVER A VALUE OUT OF BAND")
    dotenv("a", f"CLAUDE_CODE_OAUTH_TOKEN={DUMMY['a']}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_") and k not in LOGIN_KEYS}
    env.update(ASTRYX_COG_REGISTRY=str(reg), ASTRYX_HOME=str(H["a"]), PYTHONPATH=str(REPO / "src"))
    r = subprocess.run([sys.executable, str(SRC), "--org"], capture_output=True, text=True, env=env, timeout=60)
    try:
        org = json.loads(r.stdout)
    except ValueError:
        org = None
    check("`--org` names the CLI and the key, never its value", r.returncode == 0 and org == {
        "cli": "claude", "key": "CLAUDE_CODE_OAUTH_TOKEN", "supported": True} and whose(r.stdout + r.stderr) == [],
        f"rc {r.returncode} {sorted(org) if isinstance(org, dict) else org!r} whose {whose(r.stdout + r.stderr)}")
    dotenv("b")
    r = subprocess.run([sys.executable, str(SRC), "--org"], capture_output=True, text=True,
                       env={**env, "ASTRYX_HOME": str(H["b"])}, timeout=60)
    check("no key: `--org` says the ambient login (key null)", r.returncode == 0
          and r.stdout.strip() == json.dumps({"cli": "claude", "key": None, "supported": True}), r.stdout[-200:])
    rc, out, err = run("a")
    check("a spawn's fragment: stderr holds no value", rc == 0 and whose(err) == [], f"whose {whose(err)}")

    print("\nO7 A CLI WITH NO LAUNCHER")
    dotenv("a", "ASTRYX_ORG_CLI=gemini", f"CLAUDE_CODE_OAUTH_TOKEN={DUMMY['a']}")
    rc, out, err = run("a")
    check("ASTRYX_ORG_CLI=gemini: exit 3, `cli gemini not yet supported`, nothing on stdout",
          rc == 3 and out == "" and "cli gemini not yet supported" in err and whose(err) == [], f"rc {rc} {err[-200:]}")
    dotenv("a", "ASTRYX_ORG_CLI=claude", f"CLAUDE_CODE_OAUTH_TOKEN={DUMMY['a']}")
    rc, out, err = run("a")
    check("control: ASTRYX_ORG_CLI=claude is the default's row", rc == 0 and whose(out) == ["a"], f"rc {rc} {err[-200:]}")

print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
      f"NOT A PASS (77): {len(skipped)} arm(s) not run: " + "; ".join(skipped) if skipped else
      "ALL PASS: each org of a cog runs its agents on its own login, by key name, never another org's")
sys.exit(1 if fails else 77 if skipped else 0)
