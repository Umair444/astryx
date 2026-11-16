"""astryx · vault — the org's KEYS (Harness and Keys, owner 11-16; docs/superpowers/specs/2026-11-16-harness-and-keys-design.md;
homes/seed/agents-credentials/DESIGN.md, medic 12364).

A key is a provider (astryx.core.catalog: a Claude login, an Anthropic, DeepSeek or OpenRouter API key …) plus a
secret, under a name the owner picks. This module holds the NAMES; the secret lives only in .env.

The NAME a key's value lives under in .env is derived from the key's name, never taken from a client: a browser (or a
stolen owner session) that could pick it could overwrite the org's own config (ASTRYX_DSN, WA_WEBHOOK_SECRET,
CLAUDE_CODE_OAUTH_TOKEN …). So every value lives under ASTRYX_CRED_<SLUG>, and a name whose key is already held by
something that isn't the vault is refused. Values are written by config.set_env (the one .env writer: locked,
fsynced, atomic).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from astryx.core import catalog

PREFIX = "ASTRYX_CRED_"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,47}")
TIERS = ("opus", "sonnet", "haiku")


class Refused(ValueError):
    pass


def slug(name: str) -> str:
    """A key's name as an env key part: letters and digits upper-cased, every run of anything else one '_'."""
    if not isinstance(name, str) or not NAME.fullmatch(name.strip()):
        raise Refused("a key's name is 1 to 48 letters, digits, spaces, dots, dashes or underscores")
    return re.sub(r"[^A-Z0-9]+", "_", name.strip().upper()).strip("_")


def env_key(name: str, env: dict, vault: dict | None = None) -> str:
    """The .env key for key `name`. `env`: the org's .env as read; `vault`: {name: anything} of what the vault holds.
    Allowed only when the env key is unused, or used by THIS entry (the same name: a rotation). Another name that
    folds to the same env key ("Prod Key", "prod-key") is refused, never allowed to overwrite the first's value
    (medic 12463); so is an env key in .env that the vault doesn't own."""
    key = PREFIX + slug(name)
    held = {PREFIX + slug(n): n for n in (vault or {})}
    if key in held and held[key] != name:
        raise Refused(f"'{name}' would share {key} with '{held[key]}': choose another name")
    if key in env and key not in held:
        raise Refused(f"{key} is already in .env and isn't one of the vault's: choose another name")
    return key


# ── the vault itself ──────────────────────────────────────────────────────────────────────────────────────────────────
# credentials.json (gitignored, beside runtime.json): {"credentials": {name: entry}}. An entry:
#   provider        a row of providers.json
#   base_url, format   a custom endpoint's own (the catalog's endpoint otherwise)
#   models          {tier: model}: what the harness's tier aliases map to on this key (the provider's by default)
#   cap_tokens_day  a metered key's daily cap (medic 12364 R4): money leaves the org per token (local.md Economy)
# A loaded entry also carries `kind` (login | key: its provider's auth), the word its readers branch on.
# An agent's runtime.json entry names its key ({"credential": name}); astryx.core.runtime_env turns it into that
# agent's environment at spawn.

def path(estate: Path) -> Path:
    return Path(estate) / "credentials.json"


def _legacy(e: dict) -> dict:
    """An entry from before the catalog (11-16): {kind: login} was a Claude login; {kind: key} an Anthropic key, or a
    custom Anthropic-format endpoint when it had a base_url."""
    if "provider" in e or e.get("kind") not in ("login", "key"):
        return e
    pid = "claude" if e["kind"] == "login" else "custom" if e.get("base_url") else "anthropic"
    return {**{k: v for k, v in e.items() if k != "kind"}, "provider": pid, **({"format": "anthropic"} if pid == "custom" else {})}


def load(estate: Path) -> dict:
    """{name: entry}; an absent or unreadable file is an empty vault (never a crash at spawn). An entry whose provider
    the catalog no longer has is dropped (an agent on it falls back to the org's login, loudly, at spawn)."""
    try:
        d = json.loads(path(estate).read_text())
        c = d.get("credentials") if isinstance(d, dict) else None
    except (OSError, ValueError):
        return {}
    cat, out = catalog.providers(), {}
    for n, e in (c or {}).items():
        e = _legacy(e) if isinstance(e, dict) else {}
        if e.get("provider") in cat:
            out[n] = {**e, "kind": cat[e["provider"]]["auth"]}
    return out


def save(estate: Path, entries: dict) -> None:
    """Atomic, 0600 (it names keys, never values). `kind` is derived on load, never stored."""
    import tempfile
    p = path(estate)
    fd, tmp = tempfile.mkstemp(prefix=".credentials.", dir=p.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"credentials": {n: {k: v for k, v in e.items() if k != "kind"} for n, e in entries.items()}},
                      f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def entry(name: str, provider: str, base_url: str = "", fmt: str = "", models: dict | None = None,
          cap: int | None = None) -> dict:
    """A checked entry (Refused names what's wrong). A custom endpoint needs its https address and its format; a
    metered key needs a daily cap."""
    slug(name)
    cat = catalog.providers()
    p = cat.get(provider)
    if p is None:
        raise Refused("pick a provider from the list")
    out: dict = {"provider": provider}
    if p.get("custom"):
        base_url = (base_url or "").strip().rstrip("/")
        if not catalog.URL.fullmatch(base_url):
            raise Refused("a custom endpoint is an https:// address")
        if fmt not in (p.get("speaks") or {}):
            raise Refused(f"a custom endpoint speaks one of: {', '.join(p['speaks'])}")
        out.update(base_url=base_url, format=fmt)
    m = {t: str(v).strip() for t, v in (models or {}).items() if t in TIERS and str(v or "").strip()}
    if any(not catalog.MODEL.fullmatch(v) for v in m.values()):
        raise Refused("a model name is letters, digits and . _ : / @ -")
    if m:
        out["models"] = m
    if p["billing"] == "metered":
        if not (isinstance(cap, int) and 0 < cap <= 10**10):
            raise Refused("an API key spends money: give it a daily cap in tokens")
        out["cap_tokens_day"] = cap
    return {**out, "kind": p["auth"]}


def value_ok(e: dict, value: str) -> bool:
    """The WHOLE value has its provider's shape (a pasted line break is no part of it)."""
    return catalog.shape_ok(e["provider"], value)


def pairs(name: str, e: dict, env: dict, harness: dict | None = None, effort: str = "") -> list[tuple[str, str]] | None:
    """The environment an agent on key `name` gets on `harness` (Claude Code by default), or None when its value isn't
    in .env (the caller falls back to the org's default, loudly). Refused when the key doesn't fit the harness."""
    v = env.get(PREFIX + slug(name), "")
    if not v:
        return None
    return catalog.env(harness or catalog.harnesses()["claude"], e["provider"], e, v, effort=effort)


def used_by(runtime: dict) -> dict[str, list[str]]:
    """{key: [agents]} from runtime.json's entries ('*' is everyone else)."""
    out: dict[str, list[str]] = {}
    for agent, ent in (runtime or {}).items():
        if isinstance(ent, dict) and ent.get("credential"):
            out.setdefault(ent["credential"], []).append(agent)
    return {k: sorted(v) for k, v in out.items()}


def connection(runtime: dict, agent: str) -> dict:
    """An agent's connection from runtime.json: its own entry, else everyone else's ('*'), else {} (the org's login).
    Its own entry is the whole of it: a key or model it leaves out is the org's, never the default connection's."""
    rt = runtime if isinstance(runtime, dict) else {}
    ent = rt[agent] if agent in rt else rt.get("*")
    return ent if isinstance(ent, dict) else {}


def logins(estate: Path, env: dict | None = None) -> list[tuple[str, str | None]]:
    """[(name, token)] of every vault LOGIN, its token None while it has no value."""
    ents = {n: e for n, e in load(estate).items() if e["kind"] == "login"}
    if ents and env is None:
        from astryx import config
        env = config.read_env(Path(estate) / ".env")
    return [(n, (env or {}).get(PREFIX + slug(n)) or None) for n in sorted(ents)]


def login_of(estate: Path, agent: str, env: dict | None = None) -> tuple[str | None, str | None]:
    """(name, token) of the vault LOGIN `agent` runs on (runtime.json, its own entry or everyone else's '*' -> the
    vault -> .env), or (None, None): the org's own login. The one place this question is answered: the Stop hook
    measures that login's limits with its token, the prompt line and the mind read how that login feels by its name."""
    try:
        rt = json.loads((Path(estate) / "runtime.json").read_text())
    except (OSError, ValueError):
        return None, None
    name = connection(rt, agent).get("credential")
    for n, token in logins(estate, env) if name else ():
        if n == name:
            return n, token
    return None, None
