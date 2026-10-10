"""astryx · release — the ONE door through which personal-tier content reaches an audience (plan-9139 S1a).

The rule (a1 #45031): content labelled L may reach audience A only when A ⊆ ∩ readers(t) for t in L. A is DERIVED
from the route, never supplied by the caller; L is derived from the session, never passed by the agent (v4 #45058).
This module is that rule and nothing else. It is PURE and wired into nothing yet: S1b points the seats at it
(server.mjs send, step.py AUTO-DELIVER, the bridges' wire_insert), S1c makes the bridge deliver only rows it STAMPED.

What lives here, each with its oracle arm in tests/test_release.py:
  label algebra   a label is a SET of tiers (a3 R3-1). The empty set is ORG (public). An unknown tier is PRIVATE:
                  it releases to the owner only, never wider (v4 D2 "an unknown label is treated as private").
  audience()      from the route's own facts plus a LIVE membership read for groups; never cached (a2 #45069's
                  carried trip). Anything it can't establish is UNKNOWN, and UNKNOWN is never ⊆ anything.
  release()       an owner-addressed release from a labelled member: the destination is the member's own route
                  whose audience ⊆ readers(L); the body goes to the tier store and the row gets a POINTER plus
                  metadata (bytes, keyed body MAC, route key, route-file sha). The caller names no route and no jid.
  stamp()         a keyed MAC over (row id, route key, label, pointer, body MAC): it binds WHAT was released as
                  well as where (a3 F1). open_stamped() is what S1c's bridge calls: the stamp verifies, the pointer
                  sits in the label's own tier dir, and the RESOLVED body's MAC matches, or nothing is delivered.
                  The destination comes from the stamp's route, never from the thread.
  agent_send()    a labelled member's send to an AGENT carries no caller-chosen free text (a1 BC-2, #45066): the
                  body is withheld, the thread is derived, the intent comes from a closed enum.

GRADES, as v4's table states them: the MAC key is same-uid readable, so the stamp and the body MAC are prevention
against outsiders and DUMP readers (backups, pg_dump, federation copies), and accident-grade against a resident.
Who is behind a 1:1 route is the route's DECLARATION (seed #45086), the same grade as every route.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

OWNER = "owner"
ORG = frozenset()                       # the org label: no tier, public to the org
TIERS = frozenset({"career", "family", "health", "finance", "identity"})
# readers(t) for every declared tier. S1 releases ONLY to an owner-only audience; the family GROUP needs a declared
# family reader set and a live membership read that the sync daemon's store lock blocks today (S0), so family-tier
# content goes to the owner's DM, which is the design's default (a1 F3).
READERS = {t: frozenset({OWNER}) for t in TIERS}
UNKNOWN = None                          # an audience nobody could establish
INTENTS = frozenset({"chat", "receipt", "task"})   # a labelled member's agent-addressed intents (a1 BC-2)
METADATA_CAP = 64                       # the longest derived string a labelled agent-addressed row may carry
MAC_KEY_ENV = "ASTRYX_RELEASE_KEY"

_TIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
UNKNOWN_TIER = "unknown"                # what any name outside _TIER_RE becomes: private, and injective to encode
# The thread shapes an agent-addressed reply may KEEP: the wire's own (send-minted `t-…`, plan threads). Anything
# else, a channel thread above all (wa:/tg:/dc:/cv:… carry a jid or chat id), is replaced by `tier-<sender>`.
# An allowlist, so a channel prefix nobody listed fails closed (a3 F2, #45211).
_ORG_THREAD_RE = re.compile(r"^(?:t-[a-z0-9]{4,16}|plan-\d{1,9})$")
_PTR_RE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")


class Refused(Exception):
    """A release the rule does not allow. The reason never carries content, a jid or a chat id."""


# ── label algebra ─────────────────────────────────────────────────────────────────────────────────────────────────
def label(tiers) -> frozenset:
    """A label from an iterable of tier names. A bare str is REFUSED (it would iterate to its letters). A name
    outside [a-z][a-z0-9_] becomes UNKNOWN_TIER: still private, and no name can carry the separator the stamp
    encodes with, so two distinct labels never encode alike (a3 F3)."""
    if isinstance(tiers, (str, bytes)):
        raise Refused("label() takes an iterable of tier names, not one string")
    return frozenset(t if _TIER_RE.fullmatch(t) else UNKNOWN_TIER for t in (str(x) for x in (tiers or ())))


def readers(lbl: frozenset):
    """∩ readers(t) over the label. ORG reads as None: no restriction, the org's own audience."""
    if not lbl:
        return None
    out = None
    for t in lbl:
        r = READERS.get(t, frozenset({OWNER}))        # unknown tier → private: the owner only
        out = r if out is None else out & r
    return out


def releasable(lbl: frozenset, aud) -> bool:
    """A ⊆ readers(L). UNKNOWN never releases, and nor does an empty audience: a door to nobody is a bug."""
    if aud is UNKNOWN or not aud:
        return False
    r = readers(lbl)
    return r is None or aud <= r


# ── audience ──────────────────────────────────────────────────────────────────────────────────────────────────────
def chat_kind(channel: str, chat: str) -> str:
    """'dm' | 'group' | 'unknown', from the chat id's own shape. WhatsApp: a group jid ends @g.us, a person's in
    @s.whatsapp.net or @lid. Telegram: a positive id is a user's private chat, a negative one a group or channel
    (S0 measured the live route's getChat type 'private' with a positive id). Discord routes are channels: groups."""
    chat = str(chat or "")
    if channel == "whatsapp":
        if chat.endswith("@g.us"):
            return "group"
        if chat.endswith("@s.whatsapp.net") or chat.endswith("@lid"):
            return "dm"
        return "unknown"
    if channel == "telegram":
        if re.fullmatch(r"-\d+", chat):
            return "group"
        if re.fullmatch(r"\d+", chat):
            return "dm"
        return "unknown"
    if channel == "discord":
        return "group"
    return "unknown"


def audience(channel: str, route: dict, members=None):
    """The set of principals a delivery on this route reaches, or UNKNOWN.

    dm     the route's DECLARED counterpart (`counterpart: "owner"`); an undeclared counterpart is UNKNOWN.
    group  `members(channel, chat)` is called NOW: a live read, never a cached snapshot. Each id the route
           declares as the owner's (`owner_ids`) reads OWNER; anyone else reads as an outsider principal. A read
           that fails or isn't available is UNKNOWN.
    A disabled route reaches nobody that this door may name: UNKNOWN."""
    if not isinstance(route, dict) or not route.get("enabled"):
        return UNKNOWN
    kind = chat_kind(channel, route.get("chat"))
    if kind == "dm":
        return frozenset({OWNER}) if route.get("counterpart") == OWNER else UNKNOWN
    if kind == "group":
        if members is None:
            return UNKNOWN
        try:
            ids = list(members(channel, route.get("chat")))
        except Exception:  # noqa: BLE001 — any failure to read membership is UNKNOWN, never "probably fine"
            return UNKNOWN
        if not ids:
            return UNKNOWN
        own = {str(x) for x in (route.get("owner_ids") or ())}
        return frozenset(OWNER if str(i) in own else f"outsider:{n}" for n, i in enumerate(ids))
    return UNKNOWN


# ── keys, MACs, the tier store ────────────────────────────────────────────────────────────────────────────────────
def mac_key(env: dict | None = None) -> bytes:
    """The release key, from the process env or .env. Absent → Refused: no key, no door (fails closed)."""
    v = (env if env is not None else os.environ).get(MAC_KEY_ENV)
    if not v and env is None:
        f = REPO / ".env"
        if f.exists():
            for ln in f.read_text().splitlines():
                if ln.startswith(MAC_KEY_ENV + "="):
                    v = ln.split("=", 1)[1].strip()
    if not v or len(v) < 32:
        raise Refused(f"no {MAC_KEY_ENV} (or shorter than 32 chars): nothing can be released or stamped")
    return v.encode()


def _mac(key: bytes, *parts: str) -> str:
    return hmac.new(key, "\x1f".join(parts).encode(), hashlib.sha256).hexdigest()


def route_key(key: bytes, channel: str, route: dict) -> str:
    """A content-free name for a route: a keyed MAC of channel + chat, so an audit row never carries a jid."""
    return _mac(key, "route", channel, str(route.get("chat")))[:24]


def body_mac(key: bytes, body: str) -> str:
    """Keyed, never a bare sha256: a short family message is low-entropy and a bare hash is guessable (a1 F4)."""
    return _mac(key, "body", body)


def _label_text(lbl: frozenset) -> str:
    return ",".join(sorted(lbl))


def stamp(key: bytes, row_id: int, rkey: str, lbl: frozenset, pointer: str, bmac: str) -> str:
    """Binds WHAT was released, not only where (a3 F1): a pointer or body swapped on a stamped row fails it."""
    return _mac(key, "stamp", str(int(row_id)), rkey, _label_text(lbl), str(pointer), str(bmac))


def verify_stamp(key: bytes, row_id: int, rkey: str, lbl: frozenset, pointer: str, bmac: str, value: str) -> bool:
    return bool(value) and hmac.compare_digest(stamp(key, row_id, rkey, lbl, pointer, bmac), str(value))


def open_stamped(key: bytes, store: "TierStore", row_id: int, rkey: str, lbl: frozenset, pointer: str, bmac: str,
                 value: str) -> str:
    """What S1c's bridge calls before delivering: the stamp must verify, the pointer must sit in the stamped label's
    tier dir, and the RESOLVED body's keyed MAC must equal the stamped one. Any miss → Refused, nothing returned."""
    if not verify_stamp(key, row_id, rkey, lbl, pointer, bmac, value):
        raise Refused("stamp does not verify")
    body = store.get(pointer, lbl)
    if not hmac.compare_digest(body_mac(key, body), str(bmac)):
        raise Refused("the resolved body is not the body that was released")
    return body


class TierStore:
    """Where released bodies live: one file per body under <root>/<tier>/, created 0600 and never overwritten. The
    root is OUTSIDE every org member's home (a1 BC-1). The repo's tier/ is gitignored and rides backup.sh's
    state capture."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else REPO / "tier" / "release"

    @staticmethod
    def tier_dir(lbl: frozenset) -> str:
        return "+".join(sorted(lbl)) or "org"

    def put(self, lbl: frozenset, body: str) -> str:
        tier = self.tier_dir(lbl)
        if not all(_TIER_RE.fullmatch(t) for t in lbl):
            raise Refused("a tier name outside [a-z0-9_] can't name a store directory")
        d = self.root / tier
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        ptr = secrets.token_urlsafe(24)
        fd = os.open(d / ptr, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, body.encode())
        finally:
            os.close(fd)
        return f"{tier}/{ptr}"

    def get(self, pointer: str, lbl: frozenset) -> str:
        """lbl is REQUIRED: the pointer's tier dir must BE that label's, so a career body can't ride a family stamp,
        and no caller can read across tiers by forgetting an argument (a3 MC-1, #45213)."""
        tier, _, ptr = str(pointer).partition("/")
        if not (all(_TIER_RE.fullmatch(t) for t in tier.split("+")) and _PTR_RE.fullmatch(ptr)):
            raise Refused("malformed pointer")
        if tier != self.tier_dir(frozenset(lbl)):
            raise Refused("the pointer's tier is not the stamped label")
        return (self.root / tier / ptr).read_text()


def route_file_sha(path: Path) -> str:
    """sha256 of the routes file as it stood at release: a forged trusted set shows up in the audit (a2 G2)."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


# ── the door ──────────────────────────────────────────────────────────────────────────────────────────────────────
def release(sender: str, lbl: frozenset, body: str, routes, key: bytes, store: TierStore, members=None) -> dict:
    """An owner-addressed release from `sender`, whose session carries `lbl`.

    routes: (channel, route, routes_file) for every running bridge's declared routes (v4 D5).
    The destination is the ONE route the sender serves whose audience ⊆ readers(lbl). None → Refused; more than one
    → Refused (the door never guesses between two of the owner's surfaces). The body goes to the tier store; what
    returns is the row's METADATA: pointer, bytes, keyed body MAC, route key, route-file sha, label. No body."""
    if not lbl:
        raise Refused("an org-labelled send is not a release; it goes on the wire as it always has")
    ok = []
    for channel, route, rfile in routes:
        if route.get("agent") != sender:
            continue
        if releasable(lbl, audience(channel, route, members)):
            ok.append((channel, route, rfile))
    if not ok:
        raise Refused(f"{sender} serves no route whose audience is within readers({_label_text(lbl)})")
    if len(ok) > 1:
        raise Refused(f"{sender} serves {len(ok)} owner-only routes; the door won't pick one")
    channel, route, rfile = ok[0]
    return {"pointer": store.put(lbl, body), "bytes": len(body.encode()), "body_mac": body_mac(key, body),
            "channel": channel, "route_key": route_key(key, channel, route), "route_sha": route_file_sha(rfile),
            "label": _label_text(lbl)}


def agent_send(sender: str, lbl: frozenset, to: str, thread, intent, body: str, inbound_thread=None) -> dict:
    """The shape of a send from `sender` to another AGENT. An org-labelled session passes through unchanged.

    A labelled one carries no caller-chosen free text (a1 BC-2): the body is withheld and replaced by its size; the
    thread is the inbound's own thread when this is a reply on it, else `tier-<sender>`; the intent is clamped to
    a closed enum. Every derived string is capped. A thread key is content too: a steered member could write an
    instruction into it and the recipient's channel notification would deliver it."""
    if not lbl:
        return {"to": to, "thread": thread, "intent": intent, "body": body}
    keep = inbound_thread and thread == inbound_thread and _ORG_THREAD_RE.fullmatch(str(inbound_thread))
    th = inbound_thread if keep else f"tier-{sender}"
    return {"to": to, "thread": th[:METADATA_CAP], "intent": intent if intent in INTENTS else "chat",
            "body": f"[tier-labelled {_label_text(lbl)}: {len(body.encode())} bytes withheld]"[:METADATA_CAP]}
