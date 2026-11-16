"""astryx · vault — the org's named credentials (homes/seed/agents-credentials/DESIGN.md; medic 12364).

This first piece is the NAME a credential's value lives under in .env. The server derives it from the credential's
name and never takes it from a client: a browser (or a stolen owner session) that could pick the key could overwrite
the org's own config (ASTRYX_DSN, WA_WEBHOOK_SECRET, CLAUDE_CODE_OAUTH_TOKEN …). So every vault value lives under
ASTRYX_CRED_<SLUG>, and a name whose key is already held by something that isn't the vault is refused.
Values are written by config.set_env (the one .env writer: locked, fsynced, atomic).
"""
from __future__ import annotations

import re

PREFIX = "ASTRYX_CRED_"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,47}")


class Refused(ValueError):
    pass


def slug(name: str) -> str:
    """A credential's name as a key part: letters and digits upper-cased, every run of anything else one '_'."""
    if not isinstance(name, str) or not NAME.fullmatch(name.strip()):
        raise Refused("a credential's name is 1 to 48 letters, digits, spaces, dots, dashes or underscores")
    return re.sub(r"[^A-Z0-9]+", "_", name.strip().upper()).strip("_")


def env_key(name: str, env: dict, vault_names: set[str] = frozenset()) -> str:
    """The .env key for credential `name`. `env`: the org's .env as read; `vault_names`: the names the vault already
    holds (their keys are the vault's own). A key held in .env by anything else is refused (409 at the route)."""
    key = PREFIX + slug(name)
    if key in env and slug(name) not in {slug(n) for n in vault_names}:
        raise Refused(f"{key} is already in .env and isn't one of the vault's: choose another name")
    return key
