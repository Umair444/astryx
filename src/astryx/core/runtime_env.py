#!/usr/bin/env python3
"""ASTRYX nucleus·runtime_env — per-agent provider/auth override for spawn.

WHY THIS EXISTS. Every resident is its own `claude` process; different agents may run on
different providers (Anthropic direct, a Huawei/GLM endpoint, an OpenAI-compatible gateway)
with different keys and model maps. The clean seam is NOT to edit the one shared user-level
settings.json (that forces every agent onto one provider) and NOT to export process env
before launch — Claude Code's settings.json `env` block OVERRIDES process env, and our
per-home settings.json already carries an env block, so a shell export would be silently
ignored. The only correct seam is the per-home settings.json `env` block itself, which
spawn.sh already regenerates each spawn. This helper emits the extra env keys to splice in.

CONFIG lives in `runtime.json` at the repo root (GITIGNORED — the observatory writes it):
  {
    "seed": {
      "base_url": "https://api-.../anthropic",     # -> ANTHROPIC_BASE_URL
      "token_env": "PROVIDER_HUAWEI_TOKEN",         # name of the .env key holding the secret
      "models": {"opus": "glm-5.2",                 # -> ANTHROPIC_DEFAULT_OPUS_MODEL
                 "sonnet": "qwen3-32b",             # -> ANTHROPIC_DEFAULT_SONNET_MODEL
                 "haiku": "deepseek-v3.1-terminus"},# -> ANTHROPIC_DEFAULT_HAIKU_MODEL
      "effort": "high"                              # -> CLAUDE_CODE_EFFORT_LEVEL
    }
  }
No file, or no entry for the agent -> emits only the org's login, if its .env holds one (below), else NOTHING ->
the agent falls through to the ambient default (the user-level login/settings): "default = settings.json".

SECRETS NEVER LEAVE .env. The token itself is looked up from .env by the `token_env` name and
written only into the per-home settings.json (homes/ is gitignored). runtime.json holds the
NAME of the key, never the value. This file never prints the token to stdout logs.

FAIL-SAFE. If base_url is set but its token can't be resolved from .env (missing key / empty),
we emit NOTHING and warn on stderr — a half-configured agent (custom endpoint, no auth) is
worse than one that falls back to the working default. Configure fully or not at all.

THE ORG'S LOGIN (plan-10224 ORGAUTH, owner 10-21: "each org will work on its own claude login"). Beneath the
per-agent entry sits an ORG-level credential: the org's HOME .env (paths.estate: the HOME in a cog, never the
checkout's; read by config.read_env, never the process env) names which CLI the org runs (`ASTRYX_ORG_CLI=`,
default claude) and CLIS lists the .env keys that CLI reads, by billing class: a subscription login (the OAuth
token) is automatic; a metered API key only when the .env opts in, `ASTRYX_ORG_LOGIN=<that key>`. An agent whose entry
sets no base_url of its own gets the org's key spliced into ITS settings.json env; an entry with a base_url wins
and gets none. No key: nothing is added (the ambient login, as before). A CLI with no launcher here yet refuses
(exit 3, spawn.sh stops) rather than running claude under another CLI's name. ASTRYX_CLI (process env) is a
different seam, kept apart by name: spawn.sh's binary (a wrapper, a test stub).

Output: a JSON fragment beginning with a comma, ready to splice into an existing object:
  , "ANTHROPIC_BASE_URL": "...", "ANTHROPIC_AUTH_TOKEN": "...", ...
(empty string when there is nothing to inject). Mirrors spawn.sh's $TENV pattern.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402

import json
import sys

REPO = repo_root(__file__)


# The credential keys each CLI reads, by BILLING class. A subscription login is automatic (first present wins); a
# metered key bills per token, so it is used ONLY when the org's .env opts in by naming it (ASTRYX_ORG_LOGIN=<key>):
# local.md makes external spend above zero an owner-signed act, and a key present for another reason must never move
# agents onto metered billing silently (a2 #61902 A-1, seed #61907). Both are DERIVED from the CLI adapter table
# (src/astryx/data/cli_adapters.json, plan-11859 U5): a new CLI is a row there, and until its row is a launcher,
# LAUNCHERS refuses it (gemini, codex: their keys are declared, their launchers aren't built).
from astryx.core import cli_adapters as _adapters  # noqa: E402
_ROWS = _adapters.load()
CLIS = _adapters.credentials(_ROWS)
LAUNCHERS = _adapters.launchers(_ROWS)
OPT_IN = "ASTRYX_ORG_LOGIN"
BILLING_WORDS = {"subscription": "subscription (org token)", "metered": "metered API billing (opted in)",
                 "ambient": "ambient login"}


class UnsupportedCLI(RuntimeError):
    pass


def org_login(env: dict | None = None) -> dict:
    """The org's login, NAMES only: {"cli": <ASTRYX_ORG_CLI or claude>, "key": <the .env key spliced, or None>,
    "billing": "subscription" | "metered" | "ambient", "supported": <spawn.sh can launch it>, "note": <why a key that
    is set was NOT used, or None>}. A metered key is used only when OPT_IN names it; else a subscription key; else the
    ambient login. Never a value."""
    env = config.read_env(paths.estate(__file__) / ".env") if env is None else env
    cli = env.get("ASTRYX_ORG_CLI") or "claude"
    row = CLIS.get(cli, {})
    metered, subscription = row.get("metered", ()), row.get("subscription", ())
    opt = env.get(OPT_IN) or ""
    notes = []
    if opt and opt in metered and env.get(opt):
        key, billing = opt, "metered"
    else:
        if opt:
            notes.append(f"{OPT_IN}={opt} names " + ("no key that is set" if opt in metered else
                                                      f"no metered key {cli} reads") + ": not opted in")
        key = next((k for k in subscription if env.get(k)), None)
        billing = "subscription" if key else "ambient"
        notes += [f"{k} is set but not opted in ({OPT_IN}={k}): ignored, so no metered billing" for k in metered
                  if env.get(k)]
    return {"cli": cli, "key": key, "billing": billing, "supported": cli in LAUNCHERS,
            "note": "; ".join(notes) or None}


def fragment(agent: str) -> str:
    env = config.read_env(paths.estate(__file__) / ".env")
    login = org_login(env)
    if not login["supported"]:
        raise UnsupportedCLI(f"cli {login['cli']} not yet supported (this org's .env ASTRYX_ORG_CLI): spawn.sh launches "
                             f"only {', '.join(sorted(LAUNCHERS))}")
    cfg_path = paths.estate(__file__) / "runtime.json"
    if not cfg_path.exists():
        return _pairs(agent, {}, env)
    try:
        cfg = json.loads(cfg_path.read_text())
    except (ValueError, OSError) as e:  # malformed store must never break a spawn
        print(f"runtime_env: cannot read runtime.json ({e}) — falling back to default", file=sys.stderr)
        return _pairs(agent, {}, env)
    entry = cfg.get(agent)
    if not isinstance(entry, dict):
        entry = {}
    return _pairs(agent, entry, env)


def _pairs(agent: str, entry: dict, env: dict) -> str:
    pairs: list[tuple[str, str]] = []
    base_url = entry.get("base_url")
    if not base_url:
        login = org_login(env)                   # beneath the entry: the org's own credential, by NAME from its .env
        if login["note"]:
            print(f"runtime_env: agent '{agent}': {login['note']}", file=sys.stderr)
        if login["key"]:
            pairs.append((login["key"], env[login["key"]]))
    if base_url:
        # A custom endpoint REQUIRES a resolvable token — otherwise fall back entirely.
        token_env = entry.get("token_env")
        token = env.get(token_env, "") if token_env else ""
        if not token:
            print(
                f"runtime_env: agent '{agent}' sets base_url but token_env "
                f"'{token_env}' is missing/empty in .env — falling back to default (no override)",
                file=sys.stderr,
            )
            return ""
        pairs.append(("ANTHROPIC_BASE_URL", base_url))
        pairs.append(("ANTHROPIC_AUTH_TOKEN", token))

    models = entry.get("models") or {}
    for tier, key in (("opus", "ANTHROPIC_DEFAULT_OPUS_MODEL"),
                      ("sonnet", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
                      ("haiku", "ANTHROPIC_DEFAULT_HAIKU_MODEL")):
        if models.get(tier):
            pairs.append((key, str(models[tier])))

    if entry.get("effort"):
        pairs.append(("CLAUDE_CODE_EFFORT_LEVEL", str(entry["effort"])))

    if not pairs:
        return ""
    # json.dumps escapes each value/key safely; lead with a comma to splice into an open object.
    return "".join(f", {json.dumps(k)}: {json.dumps(v)}" for k, v in pairs)


if __name__ == "__main__":
    agent = sys.argv[1] if len(sys.argv) > 1 else ""
    if not agent:
        print("usage: runtime_env.py <agent>", file=sys.stderr)
        sys.exit(2)
    if agent == "--org":                         # the org's login, NAMES only (observatory, an operator)
        print(json.dumps(org_login()))
        sys.exit(0)
    if agent == "--launch":                      # spawn.sh: the line it types, for THIS org's CLI (U5); 3 no launcher
        import argparse
        ap = argparse.ArgumentParser(prog="runtime_env.py --launch")
        for a in ("--cli", "--model", "--perm", "--mcp"):
            ap.add_argument(a, required=True)
        ap.add_argument("--resume")
        a = ap.parse_args(sys.argv[2:])
        cli = org_login()["cli"]
        try:
            print(_adapters.line(_adapters.launch(cli, binary=a.cli, model=a.model, perm=a.perm, mcp=a.mcp,
                                                  resume=a.resume, rows=_ROWS)))
        except _adapters.AdapterError as e:
            print(f"runtime_env: {e}", file=sys.stderr)
            sys.exit(3)
        sys.exit(0)
    if agent == "--org-words":                   # init.sh doctor: the billing in words; exit 0 · 1 metered · 3 no launcher
        d = org_login()
        print(f"{d['cli']} agents run on: {BILLING_WORDS[d['billing']]}" + (f" via {d['key']}" if d["key"] else ""))
        if d["note"]:
            print(f"note: {d['note']}")
        sys.exit(3 if not d["supported"] else 1 if d["billing"] == "metered" else 0)
    try:
        sys.stdout.write(fragment(agent))
    except UnsupportedCLI as e:
        print(f"runtime_env: {e}", file=sys.stderr)
        sys.exit(3)
