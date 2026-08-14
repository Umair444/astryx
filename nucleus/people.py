#!/usr/bin/env python3
"""astryx · people — the owner's social graph, derived from the channels he actually uses.

WHY, AND WHY IT IS NOT relations.md. `nucleus/world.py` reads the owner's HAND-WRITTEN
instruments, which for a new joiner are empty — so the People lens would open blank and
read as broken. This module derives the same shape from the channels the org is already
connected to. For this org that is WhatsApp; the CHANNELS map below is the extension
point, so a joiner who connects a different channel gets a populated graph on day one
without editing code.

WHAT IT BUILDS
    person  — one per human, identified by a SALTED HASH of their channel id
    group   — a shared context (a WhatsApp group), which is where relations come from
    edges   — person↔group co-membership, and person↔owner for a direct conversation

Co-membership is the load-bearing edge: two people in the same group is a real relation,
and it is what makes a degrees-of-separation question answerable at all. Group ROSTERS are
not exposed by `wacli chats show`, so membership is derived from message SENDERS — which
means the graph shows people who have SPOKEN, not everyone present. That is a real
limitation and it is reported in the output rather than papered over: a lurker is invisible
here, and a graph that silently omits people would be worse than one that says so.

THE IDENTITY RULE, WHICH IS THE WHOLE PRIVACY DESIGN. A WhatsApp JID IS a phone number
(`<country><number>@s.whatsapp.net`). Hundreds of these belong to third parties who never
agreed to be in anyone's graph. So the raw JID NEVER enters a node id, a label, or an
attribute: identity is `sha256(salt + jid)`, truncated. The salt is local and secret, which
matters because phone-number space is only ~10^10 — an UNSALTED hash of a phone number is
brute-forceable in seconds and would be pseudonymity in name only.

This also happens to be exactly what a federated version needs: two orgs can compare salted
hashes under a SHARED salt to discover they know the same person without either learning a
number. That is deliberate groundwork, NOT an invitation to ship it — exporting third
parties' identities to other orgs is the owner's decision to make, and until he makes it
nothing here crosses the wire.

Library:
    scan(limit_groups=...) -> dict   {people, groups, edges, notes}
    pid(jid)               -> str    stable salted hash id
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time as _time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# How many recently-active groups to walk per run, and how deep. Bounded because a full
# sweep of 211 groups is minutes of subprocess time on a trigger that runs nightly; the
# recency ordering means the ACTIVE parts of the owner's life stay current and the dormant
# ones age out slowly. Both numbers are reported so a partial scan is never silent.
MAX_GROUPS = 45
MSGS_PER_GROUP = 120
# WALL-CLOCK BUDGET, and it is load-bearing rather than defensive. The pulse kills a check
# at CHECK_TIMEOUT=30s. Warm, a 45-group scan is ~8s (measured: 0.17s/group). COLD it was
# over three minutes — and cold is exactly the state after a reboot, which is exactly when
# a 03:40 nightly runs. A killed run never persists state, so the sweep would re-announce
# its baseline every night and never once report a change: a guard that appears to work
# and silently never does. So the scan bounds ITSELF by time and returns what it has,
# saying what it did not reach, rather than being killed mid-flight.
BUDGET_S = 18
_JID_RE = re.compile(r"^(\d+)@(s\.whatsapp\.net|g\.us)$")


def _salt() -> str:
    """Local, secret, stable. Falls back to the org id — still local-only, but a dedicated
    PEOPLE_SALT in .env is better because it can be rotated without changing org identity."""
    for k in ("PEOPLE_SALT", "ASTRYX_ORG"):
        v = os.environ.get(k)
        if v:
            return v
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            for k in ("PEOPLE_SALT=", "ASTRYX_ORG="):
                if line.startswith(k):
                    return line.split("=", 1)[1].strip()
    return "astryx-unsalted"        # last resort; scan() warns loudly when this is hit


def pid(jid: str) -> str:
    """Stable pseudonymous id. The raw jid never leaves this function."""
    return "p" + hashlib.sha256((_salt() + "|" + jid).encode()).hexdigest()[:14]


def _wa(*args: str, timeout: int = 90):
    """One wacli call, JSON out. Returns None on any failure — a channel being down must
    degrade the sweep, never raise into the pulse."""
    cli = os.environ.get("WA_CLI", "docker exec wacli-sync wacli").split()
    try:
        r = subprocess.run([*cli, *args, "--json"], capture_output=True,
                           text=True, timeout=timeout)
        if r.returncode != 0:
            return None
        d = json.loads(r.stdout)
    except Exception:
        return None
    if isinstance(d, dict):
        if d.get("success") is False:
            return None
        return d.get("data", d)
    return d


def _display(name: str | None, jid: str) -> str:
    """A label safe to render. A contact 'name' can BE a phone number — people save each
    other that way constantly — so a numeric-looking label is replaced rather than shown.
    Checking only the jid would let the number through in the one field a human reads."""
    n = (name or "").strip()
    if not n or _JID_RE.match(n):
        return "unknown"
    # SUBSTRING, NOT fullmatch. The first cut required the WHOLE label to look like a
    # number, so `+97487856986🇶🇦🇸🇦 🌎` — a real contact, a real Qatar number with emoji
    # appended — sailed through and rendered in the one field a human reads. My own test
    # passed because its fixtures were CLEAN numeric strings; real address books are not.
    # Found by reading the live payload, not by reading the code.
    #
    # So: hunt the digit RUN anywhere in the string, after stripping the separators people
    # actually type. A run of 7+ is redacted in place; if that leaves nothing meaningful,
    # the label becomes unknown. Over-masking a nickname costs a little context, while
    # under-masking publishes a number — the asymmetry decides the direction.
    stripped = re.sub(r"[\s+()\-.]", "", n)
    if re.search(r"\d{7,}", stripped):
        masked = re.sub(r"[\d\s+()\-.]{7,}", "…", n).strip()
        masked = re.sub(r"\d{7,}", "…", masked).strip()
        letters = re.sub(r"[^A-Za-z]", "", masked)
        return masked[:48] if len(letters) >= 3 else "unknown"
    return n[:48]


def scan(limit_groups: int = MAX_GROUPS, msgs: int = MSGS_PER_GROUP,
         budget_s: float = BUDGET_S) -> dict:
    """Walk the channels and build the social graph. Pure read; writes nothing."""
    notes: list[str] = []
    if _salt() == "astryx-unsalted":
        notes.append("NO SALT: set PEOPLE_SALT in .env — an unsalted hash of a phone "
                     "number is brute-forceable and offers no real pseudonymity")

    chats = _wa("chats", "list", "--limit", "500")
    if chats is None:
        return {"people": {}, "groups": {}, "edges": [],
                "notes": ["whatsapp channel unreachable — nothing scanned (this is NOT "
                          "an empty social graph, it is an unread one)"]}
    if isinstance(chats, dict):
        chats = chats.get("chats") or chats.get("items") or []

    groups = [c for c in chats if str(c.get("jid", "")).endswith("@g.us")]
    dms = [c for c in chats if str(c.get("jid", "")).endswith("@s.whatsapp.net")]
    groups.sort(key=lambda c: str(c.get("last_message_ts") or ""), reverse=True)
    scanned = groups[:limit_groups]
    if len(groups) > len(scanned):
        notes.append(f"scanned the {len(scanned)} most recently active of {len(groups)} "
                     f"groups (bounded per run; dormant groups age out slowly)")

    people: dict[str, dict] = {}
    gnodes: dict[str, dict] = {}
    edges: list[dict] = []

    for c in dms:                                  # a direct conversation is a relation
        jid = c["jid"]
        i = pid(jid)
        people.setdefault(i, {"id": i, "label": _display(c.get("name"), jid),
                              "channel": "whatsapp", "direct": True, "groups": 0})
        people[i]["direct"] = True

    silent = 0
    started = _time.monotonic()
    reached = 0
    for c in scanned:
        if _time.monotonic() - started > budget_s:
            notes.append(f"TIME BUDGET reached after {reached} of {len(scanned)} groups "
                         f"({budget_s}s) — returning a partial but VALID graph rather than "
                         f"being killed mid-run; the unreached groups are unread, not empty")
            break
        reached += 1
        gj = c["jid"]
        gi = "g" + hashlib.sha256((_salt() + "|" + gj).encode()).hexdigest()[:12]
        gnodes[gi] = {"id": gi, "label": _display(c.get("name"), gj), "channel": "whatsapp"}
        ms = _wa("messages", "list", "--chat", gj, "--limit", str(msgs))
        if ms is None:
            silent += 1
            continue
        if isinstance(ms, dict):
            ms = ms.get("messages") or ms.get("items") or []
        seen = set()
        for m in ms or []:
            sj = m.get("SenderJID") or ""
            if not sj or m.get("FromMe"):
                continue
            i = pid(sj)
            if i not in seen:
                seen.add(i)
                edges.append({"src": i, "dst": gi, "rel": "member-of"})
            p = people.setdefault(i, {"id": i, "label": _display(m.get("SenderName"), sj),
                                      "channel": "whatsapp", "direct": False, "groups": 0})
            if p["label"] == "unknown":
                p["label"] = _display(m.get("SenderName"), sj)
            p["groups"] += 1 if i in seen else 0
    if silent:
        notes.append(f"{silent} group(s) returned no messages — their members are absent "
                     f"from this graph, not proven absent from the group")
    notes.append("membership is derived from message SENDERS: people who never posted are "
                 "invisible here (wacli does not expose group rosters)")
    return {"people": people, "groups": gnodes, "edges": edges, "notes": notes}


# UNDER tier/ ON PURPOSE. This is 736 real names in plaintext, which local.md classifies
# as the human-personal tier, and tier/ is the path the law already contemplates for it.
# The placement IS the protection: steward's pii_sweep is STRUCTURALLY blind to this class
# — a name is not a regex, so no pattern distinguishes a contact from any other word, and
# pointing a detector at this file would catch nothing while making both of us believe the
# surface was watched. When detection is unavailable at any price, the guard has to be
# where the file lives and what never leaves it.
def _org() -> str:
    import os
    v = os.environ.get("ASTRYX_ORG")
    if v:
        return v
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_ORG="):
                return line.split("=", 1)[1].strip()
    return "local"


def _dsn() -> str | None:
    import os
    v = os.environ.get("ASTRYX_DSN")
    if v:
        return v
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_DSN="):
                return line.split("=", 1)[1].strip()
    return None


def write_pg(g: dict, personas: dict | None = None) -> dict:
    """Persist the scan into social_person / social_edge — THE store, not a cache.

    HISTORY, because the reversal should be legible: this first landed as
    tier/people-graph.json, justified as keeping names out of the backup. The owner
    struck that down and he was right — backup.sh's own header already classifies the
    dump as FULL owner-PII, and `messages` already carries longer-lived personal data
    than a display name. The file bought no privacy; it bought a SECOND store, an
    unversioned artifact no new joiner would get from schema.sql, and an API-side merge
    that eventually served every person twice. Postgres for everything.

    DELETE-then-INSERT scoped to THIS org's rows: the table is multi-org by design
    (federation peers replicate their structure in), so a rebuild must never touch
    rows another org sent us.
    """
    import psycopg
    dsn = _dsn()
    if not dsn:
        raise RuntimeError("no ASTRYX_DSN")
    org = _org()
    personas = personas or {}
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM social_edge WHERE org=%s", (org,))
            cur.execute("DELETE FROM social_person WHERE org=%s", (org,))
            for p_ in g.get("people", {}).values():
                per = personas.get(p_["id"]) or {}
                cur.execute(
                    "INSERT INTO social_person (org,id,kind,label,direct,relation,who,shape,confidence) "
                    "VALUES (%s,%s,'person',%s,%s,%s,%s,%s,%s)",
                    (org, p_["id"], p_["label"], bool(p_.get("direct")),
                     per.get("relation"), per.get("who"), per.get("shape"),
                     per.get("confidence")))
            for gg in g.get("groups", {}).values():
                cur.execute(
                    "INSERT INTO social_person (org,id,kind,label) VALUES (%s,%s,'group',%s)",
                    (org, gg["id"], gg["label"]))
            seen = set()
            for e in g.get("edges", []):
                k = (e["src"], e["dst"], e.get("rel", "member-of"))
                if k in seen:
                    continue
                seen.add(k)
                cur.execute(
                    "INSERT INTO social_edge (org,src,dst,rel) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    (org, e["src"], e["dst"], e.get("rel", "member-of")))
        conn.commit()
    return {"org": org, "people": len(g.get("people", {})),
            "groups": len(g.get("groups", {})), "edges": len(g.get("edges", []))}


def main() -> int:
    g = scan()
    if not g["people"] and not g["groups"]:
        for n in g["notes"]:
            print(f"  note: {n}")
        return 77
    try:
        from nucleus import persona
        w = write_pg(g, personas=persona.load_pg())
        print(f"  -> social_person/social_edge (org={w['org']})")
    except Exception as e:
        print(f"  note: not persisted ({e}) — scan printed only")
    named = sum(1 for p in g["people"].values() if p["label"] != "unknown")
    print(f"  people: {len(g['people'])} ({named} with a usable name)")
    print(f"  groups: {len(g['groups'])}")
    print(f"  edges : {len(g['edges'])} co-membership")
    degree: dict[str, int] = {}
    for e in g["edges"]:
        degree[e["src"]] = degree.get(e["src"], 0) + 1
    top = sorted(degree.items(), key=lambda kv: -kv[1])[:8]
    if top:
        print("\n  most-connected (shared groups):")
        for i, d in top:
            print(f"     {g['people'][i]['label']:<28} {d}")
    print()
    for n in g["notes"]:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
