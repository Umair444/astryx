"""astryx · catalog — Harness and Keys (owner 11-16; docs/superpowers/specs/2026-11-16-harness-and-keys-design.md).

Three nouns. A HARNESS is a CLI an agent's body runs in (a row of cli_adapters.json). A PROVIDER serves the tokens (a
row of providers.json, this module's to read). A KEY is a provider plus a secret, named by the owner (astryx.core.vault).
This module answers the two questions between them, from the tables alone, so a new provider or harness is a row and
never a branch here:

    fits(harness, provider, entry)       can an agent on this harness run on this key?    (the format they share)
    env(harness, provider, entry, value, model, effort)   the environment that makes it so  (the harness's `connect`)

and checks a key with its provider's one free authenticated GET (check). Never a value in a return but env's.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from astryx.core import cli_adapters

PATH = Path(__file__).resolve().parent.parent / "data" / "providers.json"
FORMATS = ("anthropic", "openai", "gemini")
URL = re.compile(r"https://[A-Za-z0-9.-]+(?::\d{1,5})?(?:/[A-Za-z0-9._~/-]*)?")
MODEL = re.compile(r"[A-Za-z0-9._:/@-]{1,80}")


class Refused(ValueError):
    pass


def providers(p: Path | None = None) -> dict:
    return json.loads(Path(p or PATH).read_text())["providers"]


def harnesses(rows: dict | None = None) -> dict:
    """{id: row} of every harness (cli_adapters.load: judged)."""
    return cli_adapters.load() if rows is None else rows


def fmt(harness: dict, pid: str, entry: dict | None = None, cat: dict | None = None) -> str | None:
    """How a key of provider `pid` plugs into `harness`: 'login', a format both speak, or None (it doesn't fit). A
    custom endpoint speaks the one format its entry names."""
    p = (cat or providers()).get(pid)
    if p is None:
        return None
    if p["auth"] == "login":
        return "login" if pid in harness.get("logins", ()) else None
    served = [(entry or {}).get("format")] if p.get("custom") else list(p.get("speaks") or {})
    return next((f for f in harness.get("speaks", ()) if f in served), None)


def fits(harness: dict, pid: str, entry: dict | None = None, cat: dict | None = None) -> bool:
    return fmt(harness, pid, entry, cat) is not None


def endpoint(pid: str, entry: dict, f: str, cat: dict | None = None) -> str:
    p = (cat or providers())[pid]
    return entry.get("base_url", "") if p.get("custom") else (p.get("speaks") or {}).get(f, "")


def env(harness: dict, pid: str, entry: dict, value: str, effort: str = "",
        cat: dict | None = None) -> list[tuple[str, str]]:
    """The (var, value) pairs an agent on `harness` runs on this key with. Every OTHER auth var the harness reads is
    set empty, so one login is live in the session and nothing in the process env can win over the key it was
    connected to (medic 12468). The harness's tier aliases (its background calls use them too) map to the key's own
    choice, else the provider's; a native provider has none, its aliases are the harness's own. The model an agent
    RUNS is the launch line's (runtime_env.connection), not an env var."""
    cat = cat or providers()
    c, p = harness.get("connect"), cat[pid]
    f = fmt(harness, pid, entry, cat)
    if not c or f is None:
        raise Refused(f"{harness.get('name', 'this harness')} can't run on {p['name']}")
    if f == "login":
        out = [(c["login"][pid], value)]
    elif p.get("native") == f:
        out = [(c[f]["key"], value)]
    else:
        out = [(c[f]["base_url"], endpoint(pid, entry, f, cat)), (c[f]["token"], value)]
    auth = {v for v in c["login"].values()} | {v for k in FORMATS for v in (c.get(k) or {}).values()}
    out += [(k, "") for k in sorted(auth - {k for k, _ in out})]
    tiers = {**(p.get("tiers") or {}), **(entry.get("models") or {})}
    out += [(c["tiers"][t], m) for t, m in sorted(tiers.items()) if t in c.get("tiers", {}) and m]
    if effort and c.get("effort"):
        out.append((c["effort"], effort))
    return out


def shape_ok(pid: str, value: str, cat: dict | None = None) -> bool:
    """The WHOLE value has its provider's key shape (a login's token is the harness's to shape: astryx.core.vault)."""
    s = (cat or providers())[pid].get("shape")
    return bool(s and re.fullmatch(s, value or ""))


def check(pid: str, value: str, timeout: int = 8, cat: dict | None = None) -> str:
    """'ok' | 'rejected' | 'unchecked': the provider's one free authenticated GET (a model or key listing), never a
    billed call. The value is sent only to the catalog's own URL for that provider, never to an owner-given one."""
    ck = (cat or providers())[pid].get("check")
    if not ck:
        return "unchecked"
    head = {"bearer": {"Authorization": f"Bearer {value}"}, "x-api-key": {"x-api-key": value},
            "x-goog-api-key": {"x-goog-api-key": value}}[ck["auth"]]
    req = urllib.request.Request(ck["url"], headers={**head, **(ck.get("headers") or {}), "User-Agent": "astryx/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "ok" if r.status == 200 else "unchecked"
    except urllib.error.HTTPError as e:
        return "rejected" if e.code in (401, 403) else "unchecked"
    except Exception:  # noqa: BLE001 — a network failure says nothing about the key; never its text (it may echo it)
        return "unchecked"
