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


# ── the vault itself ──────────────────────────────────────────────────────────────────────────────────────────────────
# credentials.json (gitignored, beside runtime.json): {"credentials": {name: entry}}. An entry NAMES a credential and
# says how an agent uses it; its value is only ever in .env under env_key(name). Two kinds:
#   login  a Claude subscription, signed in with `claude setup-token`: the agent runs on that account (its own limits)
#   key    an API key: Anthropic's own (no base_url), or any endpoint that speaks Anthropic's API (base_url: a gateway,
#          a proxy, another provider); METERED: connecting an agent to one is the owner's signed spend (local.md), so
#          a key carries a daily token cap (medic 12364 R4)
# An agent's runtime.json entry names its credential ({"credential": name}); astryx.core.runtime_env turns it into
# that agent's environment at spawn.
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

KINDS = ("login", "key")
SHAPE = {"login": re.compile(r"sk-ant-oat\d{2}-[A-Za-z0-9_-]{20,}"),
         "anthropic-key": re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9_-]{20,}"),
         "key": re.compile(r"[A-Za-z0-9._~+/=:-]{16,512}")}        # another provider's key: one printable token
URL = re.compile(r"https://[A-Za-z0-9.-]+(?::\d{1,5})?(?:/[A-Za-z0-9._~/-]*)?")
TIERS = ("opus", "sonnet", "haiku")
AUTH = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")   # every auth input


def path(estate: Path) -> Path:
    return Path(estate) / "credentials.json"


def load(estate: Path) -> dict:
    """{name: entry}; an absent or unreadable file is an empty vault (never a crash at spawn)."""
    try:
        d = json.loads(path(estate).read_text())
        c = d.get("credentials") if isinstance(d, dict) else None
        return {k: v for k, v in (c or {}).items() if isinstance(v, dict) and v.get("kind") in KINDS}
    except (OSError, ValueError):
        return {}


def save(estate: Path, entries: dict) -> None:
    """Atomic, 0600 (it names keys, never values)."""
    import tempfile
    p = path(estate)
    fd, tmp = tempfile.mkstemp(prefix=".credentials.", dir=p.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"credentials": entries}, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def entry(name: str, kind: str, base_url: str = "", models: dict | None = None, cap: int | None = None) -> dict:
    """A checked entry (Refused names what's wrong). A key needs a cap; a login has no endpoint."""
    slug(name)
    if kind not in KINDS:
        raise Refused("a credential is a login (a Claude subscription) or a key (an API key)")
    base_url = (base_url or "").strip()
    if kind == "login" and base_url:
        raise Refused("a login is a Claude subscription: it has no endpoint of its own")
    if base_url and not URL.fullmatch(base_url):
        raise Refused("the endpoint is an https:// address")
    if kind == "key" and not (isinstance(cap, int) and 0 < cap <= 10**10):
        raise Refused("an API key spends money: give it a daily cap in tokens")
    m = {t: str(v).strip() for t, v in (models or {}).items() if t in TIERS and str(v or "").strip()}
    if any(not re.fullmatch(r"[A-Za-z0-9._:/@-]{1,80}", v) for v in m.values()):
        raise Refused("a model name is letters, digits and . _ : / @ -")
    return {"kind": kind, "base_url": base_url, "models": m, **({"cap_tokens_day": cap} if kind == "key" else {})}


def value_ok(kind: str, base_url: str, value: str) -> bool:
    """The WHOLE value has its kind's shape (a pasted line break is no part of it)."""
    shape = SHAPE["login"] if kind == "login" else SHAPE["key"] if base_url else SHAPE["anthropic-key"]
    return bool(shape.fullmatch(value or ""))


def pairs(name: str, e: dict, env: dict) -> list[tuple[str, str]] | None:
    """The environment an agent on credential `name` gets, or None when its value isn't in .env (the caller falls
    back to the org's default, loudly)."""
    v = env.get(PREFIX + slug(name), "")
    if not v:
        return None
    if e["kind"] == "login":
        out = [("CLAUDE_CODE_OAUTH_TOKEN", v)]
    elif e.get("base_url"):
        out = [("ANTHROPIC_BASE_URL", e["base_url"]), ("ANTHROPIC_AUTH_TOKEN", v)]
    else:
        out = [("ANTHROPIC_API_KEY", v)]
    # ONE login live in the session (medic 12468): every OTHER way Claude Code can authenticate is set empty, so the
    # org's token or a key in the process env can never win over the credential the agent was connected to
    out += [(k, "") for k in AUTH if k not in {x for x, _ in out}]
    return out + [(f"ANTHROPIC_DEFAULT_{t.upper()}_MODEL", m) for t, m in sorted((e.get("models") or {}).items())]


def used_by(runtime: dict) -> dict[str, list[str]]:
    """{credential: [agents]} from runtime.json's entries."""
    out: dict[str, list[str]] = {}
    for agent, ent in (runtime or {}).items():
        if isinstance(ent, dict) and ent.get("credential"):
            out.setdefault(ent["credential"], []).append(agent)
    return {k: sorted(v) for k, v in out.items()}


def login_of(estate: Path, agent: str, env: dict | None = None) -> tuple[str | None, str | None]:
    """(name, token) of the vault LOGIN `agent` runs on (runtime.json -> the vault -> .env), or (None, None): the org's
    own login. The one place this question is answered: the Stop hook measures that login's limits with its token, the
    prompt line and the mind read how that login feels by its name."""
    try:
        ent = json.loads((Path(estate) / "runtime.json").read_text()).get(agent) or {}
    except (OSError, ValueError, AttributeError):
        return None, None
    name = ent.get("credential") if isinstance(ent, dict) else None
    e = load(estate).get(name) if name else None
    if not e or e["kind"] != "login":
        return None, None
    if env is None:
        from astryx import config
        env = config.read_env(Path(estate) / ".env")
    return name, env.get(PREFIX + slug(name)) or None
