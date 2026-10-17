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
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

REPO = repo_root(__file__)


def _estate() -> Path:
    """The org's estate, read at CALL time: REPO on one org (exactly what it was, an oracle's `R.REPO = root` rebinding
    included), the HOME on a multi-org host (plan-11324 S3a)."""
    from astryx import orgs
    return paths.home() if orgs.multi() else REPO

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
        f = _estate() / ".env"
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
        self.root = Path(root) if root else _estate() / "tier" / "release"

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
            data = memoryview(body.encode())
            while data:                                   # os.write may write SHORT; a body is all of it or nothing
                data = data[os.write(fd, data):]
        except OSError:
            os.unlink(d / ptr)                            # no half-body left under a pointer nothing names
            raise
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


# ── S1b: the label's source, the seats' one send, the CLI the channel server shells out to ──────────────────────────
class GrantError(Refused):
    """A Grants entry that LOOKS like a private grant but isn't exactly `owner_private:<declared tier>`. It refuses,
    never reads as 'unlabelled': a typo in the one identity meant to be private would otherwise put its content on
    the wire by today's raw path (a4 #46035)."""


class UnknownLabel(GrantError):
    """No charter resolves for the identity: its label is UNKNOWN. Still never ORG, but not a malformed grant either.
    The channel server STARTS such a body (its ear works) with every send refused (S1b-2), as step.py withholds;
    only a malformed grant refuses the start (a4 #46035). `label` exits 3 for it, 1 for a malformed grant."""


GRANT_PREFIX = "owner_private:"
OWNER_ADDRESSES = frozenset({"owner"})       # the only channel-bound destination a labelled member may address


def charter(agent: str, agents_dir: Path | None = None) -> Path | None:
    """The agent's charter through the org's ONE resolver (nucleus/charter.resolve: any depth, examples/ and .git
    excluded, a duplicated stem raises), the same one src/astryx/core/tier.py reads (a3 #46041). Only an EXACT name
    resolves: resolve() sanitises, so 'seed*' would otherwise mean seed.md, a glob passing as an identity."""
    from astryx.core import charter as C
    d = Path(agents_dir) if agents_dir else _estate() / "agents"
    if not agent or "".join(c for c in agent if c.isalnum() or c in "-_").lower() != agent:
        return None
    try:
        return C.resolve(agent, d)
    except C.Collision as e:
        raise GrantError(f"{agent}: {str(e).splitlines()[0]}")


def label_of(agent: str, agents_dir: Path | None = None) -> frozenset:
    """The label a session of `agent` carries: the tiers its charter's `Grants:` line names as
    `owner_private:<tier>` (v4 D2a: the identity IS the role). No such grant → ORG; NO CHARTER → GrantError
    (tier.py's polarity: an unresolvable identity is private, never public). Any entry that
    mentions 'private' or a declared tier name but isn't exactly a declared grant → GrantError, named."""
    p = charter(agent, agents_dir)
    if p is None:                    # UNKNOWN, never ORG: a labelled member whose charter moved, or whose name drifted
        raise UnknownLabel(f"no charter resolves for {agent!r}: its label is UNKNOWN, so it can't send as org")
    line = next((ln for ln in p.read_text(errors="replace").splitlines() if ln.startswith("Grants:")), "")
    tiers = set()
    for e in (x.strip() for x in line.split(":", 1)[1].split(",") if line) if line else ():
        if not e:
            continue
        if e.startswith(GRANT_PREFIX) and e[len(GRANT_PREFIX):] in TIERS:
            tiers.add(e[len(GRANT_PREFIX):])
        elif re.search(r"private", e, re.I) or any(t in e.lower() for t in TIERS):
            raise GrantError(f"{agent}'s Grants entry {e!r} is not exactly {GRANT_PREFIX}<one of "
                             f"{','.join(sorted(TIERS))}>: refusing rather than running unlabelled")
    return frozenset(tiers)


TIER_KEY = "tier"


def route_tier(route) -> str | None:
    """The tier a route DECLARES (`"tier": "<declared tier>"`), or None when it declares none. A key that LOOKS like
    a tier declaration but isn't exactly `tier` (Tier, tiers, tier_name…), or a value outside TIERS, raises
    GrantError: the route grant's polarity (a4 #46035), so a typo can't put a private chat on today's raw path."""
    if not isinstance(route, dict):
        return None
    odd = sorted(str(k) for k in route if "tier" in str(k).lower() and k != TIER_KEY)
    if odd:
        raise GrantError(f"route key {odd[0]!r} is not exactly {TIER_KEY!r}: refusing rather than routing it untiered")
    if TIER_KEY not in route:
        return None
    t = route[TIER_KEY]
    if t not in TIERS:
        raise GrantError(f"the route declares tier {t!r}, which is not one of {','.join(sorted(TIERS))}")
    if route.get("live_steps"):
        # live_steps streams STEP text straight to the chat and never passes deliver()'s door: a tiered route can't
        # have that second egress (a4 #53717), so the declaration itself is refused
        raise GrantError(f"a {t} route can't carry live_steps: step text would reach the chat around the door")
    return t


def live_steps_ok(route) -> bool:
    """A live_steps job may start only on an ORG route: one declaring live_steps and no tier. A malformed or tiered
    declaration is never a yes (S1c, a4 #53717)."""
    try:
        return bool(isinstance(route, dict) and route.get("live_steps")) and route_tier(route) is None
    except GrantError:
        return False


def ingress(channel: str, route: dict, body: str, key: bytes, store: "TierStore") -> tuple[str, dict]:
    """An INBOUND message on a route that declares a tier (S1b-2b, #46033 item 4): the body goes to the tier store
    and the row carries a size marker plus delivery.ingress {pointer, body_mac, tier}. The labelled member's channel
    server resolves the pointer (`read`, label-checked); every other reader sees the marker.
    Refused (GrantError for a bad declaration, Refused otherwise) BEFORE anything is stored when: the route
    declares no valid tier; it is `open` (a stranger's text would enter the tier store); or its audience isn't within
    readers(tier), i.e. it isn't a DM declared as the owner's. The caller passes the key, so no key → no call."""
    tier = route_tier(route)
    if tier is None:
        raise Refused("this route declares no tier: ingress is not its path")
    if route.get("open"):
        raise GrantError(f"a {tier} route can't be open: a stranger's text would enter the {tier} store")
    lbl = frozenset({tier})
    if not releasable(lbl, audience(channel, route)):
        raise Refused(f"the route's audience isn't within readers({tier}): only a DM declared as the owner's")
    try:
        pointer = store.put(lbl, body)
    except OSError as e:          # a full disk, a bad permission, no tier root: every caller WITHHOLDS (a4 #53081)
        raise Refused(f"the {tier} store could not take the body ({type(e).__name__})") from None
    return (f"[tier-routed: {len(body.encode())} bytes, {tier}]",
            {"ingress": {"pointer": pointer, "body_mac": body_mac(key, body), "tier": tier}})


def read_for(agent: str, pointer: str, bmac: str, *, key: bytes, store: "TierStore",
             agents_dir: Path | None = None) -> str:
    """The body behind `pointer` for a session of `agent`. THE READ RULE (a3's cross-tier refusal, adopted in
    #45071; a4 #46035 item 4): the pointer's tiers must ALL be in the agent's own label; an org or UNKNOWN agent
    reads nothing; and the resolved body must carry the row's keyed MAC, so a swapped file or a pointer lifted from
    another row resolves to nothing."""
    lbl = label_of(agent, agents_dir)
    tiers = frozenset(str(pointer).partition("/")[0].split("+"))
    if not lbl or not tiers <= lbl:
        raise Refused("the pointer's tier is not in this member's label")
    try:
        body = store.get(pointer, tiers)
    except OSError:
        raise Refused("no body under that pointer")
    if not hmac.compare_digest(body_mac(key, body), str(bmac)):
        raise Refused("the resolved body is not the body the row names")
    return body


def declared_routes(bridges_dir: Path | None = None) -> list:
    """(channel, route, routes_file) for every route declared in bridges/routes-<channel>.json (v4 D5's route
    domain). A route's `tier`, when present, must be a declared tier, or the whole read refuses (a4 #46035)."""
    out = []
    for f in sorted((Path(bridges_dir) if bridges_dir else REPO / "bridges").glob("routes-*.json")):
        import json
        try:
            rows = json.loads(f.read_text())
        except (OSError, ValueError):
            raise Refused(f"{f.name} is unreadable: no route can be established")
        for r in rows if isinstance(rows, list) else []:
            try:
                route_tier(r)
            except GrantError as e:
                raise GrantError(f"a route in {f.name}: {e}")
            out.append((f.stem.split("-", 1)[1], r, f))
    return out


def send_row(cur, sender: str, lbl: frozenset, to: str, thread, intent, body: str, *, key: bytes,
             store: TierStore, routes, members=None, inbound_thread=None, agents_dir: Path | None = None) -> int:
    """The ONE write every seat makes for a LABELLED sender (server.mjs send, step.py AUTO-DELIVER). Returns the id.

      to 'owner'       release(): a pending row whose body is a size marker, thread `tier-<sender>` (no chat id
                       on the wire: the destination is the stamp's route, S1c), and delivery.release carrying the
                       pointer, keyed body MAC, route key, route-file sha, label and the STAMP over the row id.
      to an agent      agent_send()'s shape: body withheld, thread derived, intent clamped.
      to anything else no charter names (a person's wa-/tg-/dc-/cv- address, a typo): Refused, an allowlist.
    Any refusal raises BEFORE a row is written: no key, no route, a bad label. An ORG label is not this path."""
    import json
    if not lbl:
        raise Refused("send_row is the labelled path; an org-labelled sender keeps today's write")
    if to in OWNER_ADDRESSES:
        rel = release(sender, lbl, body, routes, key, store, members)
        marker = f"[released: {rel['bytes']} bytes, {rel['label']}]"
        rid = cur.execute(
            "INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, delivery) "
            "VALUES (%s,'local',%s,'local',%s,'chat',%s,%s) RETURNING id",
            (sender, to, f"tier-{sender}"[:METADATA_CAP], marker, json.dumps({"release": rel}))).fetchone()[0]
        rel["stamp"] = stamp(key, rid, rel["route_key"], lbl, rel["pointer"], rel["body_mac"])
        cur.execute("UPDATE messages SET delivery = %s WHERE id = %s", (json.dumps({"release": rel}), rid))
        return rid
    if charter(to, agents_dir) is None:            # an allowlist: a person's channel address (wa-/tg-/…), a new
        raise Refused("a labelled member's non-owner send goes only to an AGENT (a charter by that name); "
                      "this address has none")    # channel's prefix, or a typo all fail closed
    shape = agent_send(sender, lbl, to, thread, intent, body, inbound_thread)
    return cur.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body) "
        "VALUES (%s,'local',%s,'local',%s,%s,%s) RETURNING id",
        (sender, shape["to"], shape["thread"], shape["intent"], shape["body"])).fetchone()[0]


# ── S1c: the door at the bridge ───────────────────────────────────────────────────────────────────────────────────
# Every chat bridge's deliver() asks this first (a4 #45091). A STAMPED row is delivered only through open_stamped(),
# to the route its stamp names; an UNSTAMPED row only to a DECLARED ORG ROUTE of that bridge (the census exemption).
# Every other destination is refused: an off-route chat, a tiered route, a route nobody declared. The exemption is
# keyed on "a declared org route", never on "not labelled" — a destination on NO route is the stray-row case.
def released(row) -> dict | None:
    """The row's delivery.release, or None. asyncpg hands jsonb back as text; psycopg as a dict."""
    d = row.get("delivery") if hasattr(row, "get") else row["delivery"]
    if isinstance(d, str):
        import json
        try:
            d = json.loads(d)
        except ValueError:
            return None
    rel = d.get("release") if isinstance(d, dict) else None
    return rel if isinstance(rel, dict) else None


def door_stamped(row, channel: str, routes, *, key: bytes, store: "TierStore", members=None) -> tuple[dict, str]:
    """A released row → (the route its stamp names, the resolved body). The destination is the ONE route of this
    bridge whose route_key matches the stamp's; delivery.release.channel only pre-filters, it isn't what the stamp
    binds. The route must STILL release to the label (a route rebound since release fails here). Refused on any miss."""
    rel = released(row)
    if rel is None:
        raise Refused("not a released row")
    lbl = label(str(rel.get("label") or "").split(",")) if rel.get("label") else ORG
    if not lbl:
        raise Refused("a released row with no label")
    rkey = str(rel.get("route_key") or "")
    hits = [r for r in routes if hmac.compare_digest(route_key(key, channel, r), rkey)]
    if len(hits) != 1:
        raise Refused(f"the stamp names {'no' if not hits else len(hits)} route(s) of this bridge")
    route = hits[0]
    if not releasable(lbl, audience(channel, route, members)):
        raise Refused(f"the stamped route's audience is no longer within readers({_label_text(lbl)})")
    body = open_stamped(key, store, int(row["id"]), rkey, lbl, str(rel.get("pointer")), str(rel.get("body_mac")),
                        str(rel.get("stamp") or ""))
    return route, body


def door_org(channel: str, chat, routes) -> dict:
    """An UNSTAMPED row's destination must be a DECLARED ORG ROUTE of this bridge: enabled, in its routes file,
    declaring no tier. Returns that route; Refused otherwise (a malformed tier declaration refuses too)."""
    hits = [r for r in routes if r.get("enabled") and str(r.get("chat")) == str(chat)]
    if not hits:
        raise Refused("an unstamped row to a destination on no declared route of this bridge")
    for r in hits:
        if route_tier(r) is not None:
            raise Refused("an unstamped row to a TIERED route: that route takes only released rows")
    return hits[0]


def _dsn() -> str:
    try:
        return config.dsn(_estate() / ".env")
    except LookupError:
        raise Refused("no ASTRYX_DSN")


def main(argv=None) -> int:
    """The channel server's door into this module (server.mjs is node; the door is ONE, here):

        python -m astryx.security.release label <agent>   JSON list of the agent's tiers; rc 1 on a malformed grant,
                                                  rc 3 when no charter resolves (UNKNOWN)
        python -m astryx.security.release send            stdin {to, thread, intent, body, inbound_thread}; sender is
                                                  $ASTRYX_AGENT; prints {"id": n} or {"error": reason}; rc 0 / 1
        python -m astryx.security.release read <pointer> <body_mac>   the body, for $ASTRYX_AGENT, only under
                                                  read_for()'s rule (its tiers ⊆ the label, the MAC matches); rc 1
    Errors print a reason that carries no content, jid or chat id."""
    import json
    import sys
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["label"] and len(argv) == 2:
            try:
                print(json.dumps(sorted(label_of(argv[1]))))
            except UnknownLabel as e:
                print(json.dumps({"error": str(e), "unknown": True}))
                return 3
            return 0
        agent = os.environ.get("ASTRYX_AGENT") or ""
        if argv == ["send"]:
            req = json.loads(sys.stdin.read())
            lbl = label_of(agent)
            import psycopg
            with psycopg.connect(_dsn(), autocommit=False) as c, c.cursor() as cur:
                rid = send_row(cur, agent, lbl, str(req.get("to", "")), req.get("thread"), req.get("intent"),
                               str(req.get("body", "")), key=mac_key(), store=TierStore(),
                               routes=declared_routes(), inbound_thread=req.get("inbound_thread"))
                c.commit()
            print(json.dumps({"id": rid}))
            return 0
        if argv[:1] == ["read"] and len(argv) == 3:
            sys.stdout.write(read_for(agent, argv[1], argv[2], key=mac_key(), store=TierStore()))
            return 0
    except Refused as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print("usage: python -m astryx.security.release label <agent> | send | read <pointer> <body_mac>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
