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
No file, or no entry for the agent -> emits NOTHING -> the agent falls through to the org's
ambient default (the user-level login/settings). That is the "default = settings.json" rule.

SECRETS NEVER LEAVE .env. The token itself is looked up from .env by the `token_env` name and
written only into the per-home settings.json (homes/ is gitignored). runtime.json holds the
NAME of the key, never the value. This file never prints the token to stdout logs.

FAIL-SAFE. If base_url is set but its token can't be resolved from .env (missing key / empty),
we emit NOTHING and warn on stderr — a half-configured agent (custom endpoint, no auth) is
worse than one that falls back to the working default. Configure fully or not at all.

Output: a JSON fragment beginning with a comma, ready to splice into an existing object:
  , "ANTHROPIC_BASE_URL": "...", "ANTHROPIC_AUTH_TOKEN": "...", ...
(empty string when there is nothing to inject). Mirrors spawn.sh's $TENV pattern.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE, no export/quote gymnastics — matches spawn.sh's cut)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v
    return env


def fragment(agent: str) -> str:
    cfg_path = REPO / "runtime.json"
    if not cfg_path.exists():
        return ""
    try:
        cfg = json.loads(cfg_path.read_text())
    except (ValueError, OSError) as e:  # malformed store must never break a spawn
        print(f"runtime_env: cannot read runtime.json ({e}) — falling back to default", file=sys.stderr)
        return ""
    entry = cfg.get(agent)
    if not isinstance(entry, dict):
        return ""

    pairs: list[tuple[str, str]] = []
    base_url = entry.get("base_url")
    if base_url:
        # A custom endpoint REQUIRES a resolvable token — otherwise fall back entirely.
        token_env = entry.get("token_env")
        token = _load_env(REPO / ".env").get(token_env, "") if token_env else ""
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
    sys.stdout.write(fragment(agent))
