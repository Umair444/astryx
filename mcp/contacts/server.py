#!/usr/bin/env python3
"""astryx · contacts MCP server — resolve a WhatsApp sender to a known person.

The wire stamps an unknown group sender as `wa-<number>`, and WhatsApp hands out
privacy `@lid` device-ids that don't look like a phone number at all. This tool
answers "who is this?" from the owner's own synced WhatsApp contacts (wacli's
contact store) — so an agent SEARCHES the identity instead of treating every
unfamiliar id as a stranger. Capability over constraint.

wacli's contact store is keyed by phone number (pn); it has no idea a privacy
`@lid` belongs to a contact. The lid↔pn table lives in whatsmeow's session.db
(`whatsmeow_lid_map`), which no wacli command exposes. So for a lid we bridge:
lid → pn (from session.db, read-only) → contact label (from wacli). Access to
session.db is via `docker cp` out of the same container wacli already runs in —
read-only, no host permission grant.

Granted per charter (`Grants: contacts`). PERSONAL TIER — HARD: contact numbers are
the owner's private data. Resolution returns the contact LABEL only, never a raw
phone number and never a number-bearing jid. The lid_map is read to name a sender,
never to surface the number behind it.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ENV = Path(__file__).resolve().parents[2] / ".env"
_cfg = dict(
    line.split("=", 1)
    for line in ENV.read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
WA = shlex.split(_cfg.get("WA_CLI", "wacli"))
CTR = WA[WA.index("exec") + 1] if "exec" in WA else "wacli-sync"
SESSION_DB = f"{_cfg.get('WA_DATA_CTR', '/data')}/store/session.db"

mcp = FastMCP("astryx-contacts")

# Never echo the caller's id/query back: it may itself be a phone number or a
# number-bearing jid, and the tool result is logged to the RAG-reachable step
# stream. Unknowns get a fixed, numberless answer.
_UNKNOWN = "unknown sender — not in the owner's known contacts"


def _wacli(*args: str) -> list[dict]:
    r = subprocess.run([*WA, "contacts", *args, "--json"],
                       capture_output=True, text=True, timeout=15)
    try:
        out = json.loads(r.stdout)
        return out.get("data") or []
    except Exception:
        return []


def _label(c: dict) -> str:
    """The name we may say on the wire — never the number behind it. A contact can
    be *saved as* its own number (name == digits); such a label is itself a pn leak,
    so any candidate carrying a 7+ digit run is rejected in favour of a numberless
    placeholder."""
    for cand in (c.get("name"), c.get("alias"), c.get("system_name")):
        if cand and not re.search(r"\d{7,}", cand):
            return cand
    return "(contact saved by number)"


# ── lid → pn bridge ──────────────────────────────────────────────────────────
# whatsmeow_lid_map(lid TEXT, pn TEXT), both bare digits. Held in-process; the
# copied db is read read-only and deleted at once — the numbers never touch disk
# we keep or any wire artifact.
_lidmap: dict[str, str] = {}
_lidmap_at = 0.0
_REFRESH_THROTTLE = 15  # s — a miss may refresh at most this often


def _load_lidmap() -> None:
    global _lidmap, _lidmap_at
    _lidmap_at = time.monotonic()
    tmp = tempfile.mkdtemp(prefix="astryx-lidmap.")
    os.chmod(tmp, 0o700)
    dst = os.path.join(tmp, "session.db")
    try:
        subprocess.run(["docker", "cp", f"{CTR}:{SESSION_DB}", dst],
                       capture_output=True, timeout=20, check=True)
        db = sqlite3.connect(f"file:{dst}?mode=ro&immutable=1", uri=True)
        try:
            _lidmap = {lid: pn for lid, pn in
                       db.execute("SELECT lid, pn FROM whatsmeow_lid_map")}
        finally:
            db.close()
    except Exception:
        pass  # keep any prior map; lid resolution degrades to "unknown", never crashes
    finally:
        try:
            os.remove(dst)
        except OSError:
            pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass


def _lid_to_pn(key: str) -> str | None:
    """Bare lid digits → bare pn. Cache hit is instant; a miss refreshes (throttled)
    so a freshly-synced contact's lid still resolves promptly."""
    if key in _lidmap:
        return _lidmap[key]
    if not _lidmap or time.monotonic() - _lidmap_at > _REFRESH_THROTTLE:
        _load_lidmap()
    return _lidmap.get(key)


def _find(*queries: str) -> dict | None:
    """First contact whose jid/phone actually matches one of the queries."""
    for q in queries:
        if not q:
            continue
        k = q.split("@")[0]
        for c in _wacli("search", q):
            if k and k in (c.get("jid", "").split("@")[0], c.get("phone", "")):
                return c
    return None


@mcp.tool()
def contact_search(query: str) -> str:
    """Find people in the owner's WhatsApp contacts by name, alias, or number.
    Returns matching names. Use this before treating a sender as an unknown
    stranger. (Numbers are personal-tier and are never returned.)"""
    rows = _wacli("search", query)
    if not rows:
        return "no matching contact"
    seen, names = set(), []
    for c in rows[:20]:
        n = _label(c)
        if n not in seen:
            seen.add(n)
            names.append(n)
    return "known contacts: " + ", ".join(names)


@mcp.tool()
def contact_resolve(id: str) -> str:
    """Resolve one WhatsApp jid, phone number, or privacy @lid to who it is.
    Accepts a phone number, a full jid (…@s.whatsapp.net), or a privacy @lid id.
    Returns the contact NAME if known, else states it's unknown. The raw number is
    never returned."""
    key = id.split("@")[0].split(":")[0]  # strip @lid/@s.whatsapp.net and :device
    if not key:
        return _UNKNOWN
    # 1) the contact store already knows this jid or number
    hit = _find(id, key)
    if hit:
        return _label(hit)
    # 2) privacy @lid → pn bridge (the store is keyed by pn, not lid)
    if key.isdigit():
        pn = _lid_to_pn(key)
        if pn:
            hit = _find(pn)
            if hit:
                return _label(hit)
            return ("recognized WhatsApp device, but the number behind this @lid "
                    "isn't a named contact (unknown sender)")
    return _UNKNOWN


if __name__ == "__main__":
    mcp.run()
