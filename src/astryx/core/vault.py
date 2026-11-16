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


def env_key(name: str, env: dict, vault: dict | None = None) -> str:
    """The .env key for credential `name`. `env`: the org's .env as read; `vault`: {name: anything} of what the vault
    holds. Allowed only when the key is unused, or used by THIS entry (the same name: a rotation). Another name that
    folds to the same key ("Prod Key", "prod-key") is refused, never allowed to overwrite the first's value (medic
    12463); so is a key in .env that the vault doesn't own."""
    key = PREFIX + slug(name)
    held = {PREFIX + slug(n): n for n in (vault or {})}
    if key in held and held[key] != name:
        raise Refused(f"'{name}' would share {key} with '{held[key]}': choose another name")
    if key in env and key not in held:
        raise Refused(f"{key} is already in .env and isn't one of the vault's: choose another name")
    return key
