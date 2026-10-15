"""astryx · release_migrate — a labelled identity's HISTORY into the tier store, before its route is rebound (plan-9139 S1e).

a3 BC-2 (#45057, ruled #55033): the door makes FUTURE ingress and release a pointer, but `messages` already holds the
bodies of past rows on the route about to be labelled, readable by every DSN, pg_dump and backup. And under v4 D2a the
label is the IDENTITY's, so the agent's own session history (steps, turns), written before S1d stripped it, is the
same class. This moves both, one transaction, behind a pointer and a keyed body MAC, and counts what is left.

    python -m astryx.security.release_migrate --agent canopus --channel whatsapp --tier career          # the census
    python -m astryx.security.release_migrate --agent canopus --channel whatsapp --tier career --apply  # + the move

WHAT MOVES (a body that is already one of the door's own exact markers is left alone, so a rerun is a no-op):
  messages  every row on the route's thread or delivered to its handle: {body, every delivery key outside KEEP} → one
            blob; body = the marker; delivery = the KEEP keys + migrated {pointer, body_mac, tier, at} (D1: an ALLOW-
            list, so a future bridge field is content by default). thread stays: it names the route (D3), like handle
  polls     the route chat's: {question, options, votes} → one blob; question = the marker; options = {migrated}
  steps     the agent's: content → a blob; content = the marker; meta += migrated (the toolreg ids stay)
  turns     the agent's: {raw_payload, input_prompt} → a blob; raw_payload = {withheld, usage, migrated}; the prompt a
            marker; session_id (spawn.sh resumes from it) and every metadata column stay
THE CENSUS is content-blind and identifier-blind (D3): counts only, never a thread, handle, chat or body. A row passes
only on an EXACT anchored marker (D2), a migrated one only with its pointer: detection grade, stated. S1d's write-time
step forms pass too (a3: else every post-S1d step alarms). RESIDUALS outside the database are counted and printed every
run: the agent's transcript files (its resume store: not moved), the shared auto-memory files named for it or its tier,
the chronicle editions naming it. While any is non-zero the census never reads "history clean": disposing of them is
the owner's call, with the backups and pg_dumps made before the move (b).
FUNCTION, accepted: the agent's own query_steps and night review, and the observatory, read markers afterwards; its
session resolves a pointer through read_for under its label like any tier member.
ORPHANS, accepted: a blob is written before the transaction commits, so a rolled-back run leaves unreferenced blobs in
the tier dir, and a rerun writes new ones. They are unreachable (no row names them) and stay in the tier store.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from astryx.security import release as R

KEEP = frozenset({"ok", "handle", "message_id", "door", "migrated"})    # a migrated row's delivery: exactly these (D1)
# what a door-era row on a tier route legitimately carries besides KEEP: the release record, the ingress pointer or its
# withheld reason, the identity fields ingress keeps (bridges/common._INGRESS_META), and a receipt whose rendered is a
# door marker and whose error is the classified form. Anything else is content.
DOOR_KEYS = KEEP | {"release", "ingress", "ingress_withheld", "rendered", "error", "sender_jid", "phone", "push_name",
                    "sender_id", "username", "display_name", "reply_to_id", "reply_to_sender_jid"}
_T = r"[a-z][a-z0-9_]*"
MIGRATED_RX = re.compile(r"\[migrated to the " + _T + r" tier store: [0-9]+ bytes\]")
DOOR_BODY_RX = (MIGRATED_RX, re.compile(r"\[tier-routed: [0-9]+ bytes, [a-z0-9_,]+\]"),
                re.compile(r"\[released: [0-9]+ bytes, [a-z0-9_,]+\]"),
                re.compile(r"\[tier-routed message withheld: [A-Za-z]+\]"))
CLASSIFIED_RX = re.compile(r"[a-z][a-z-]*: [A-Za-z_][A-Za-z0-9_]*(; [a-z][a-z-]*: [A-Za-z_][A-Za-z0-9_]*)*")
_TOOL = r"[A-Za-z0-9_.:-]+"
STEP_RX = (MIGRATED_RX,                                                    # S1d's write-time forms, and its fixed lines
           re.compile(_TOOL + r": \[tier-labelled session\]"), re.compile(r"\[tier-labelled session: [0-9]+ bytes\]"),
           re.compile(r"DENIED, (child spawn|secret holder): \[tier-labelled session\]"),
           re.compile(_TOOL + r" done"), re.compile(_TOOL + r": failed"), re.compile(r"\(turn unreadable\)"),
           re.compile(r"(secret|grep) guard unevaluable \([A-Za-z_]+\): allowed( \(plan-5497\))?"),
           re.compile(r"turn transcript withheld: secret redaction unavailable \(plan-5497\)"))
PROMPT_RX = (MIGRATED_RX, re.compile(r"\[tier-labelled session\]"))
PREFIX = {"whatsapp": "wa", "telegram": "tg", "discord": "dc"}


def marker(tier: str, n: int) -> str:
    return f"[migrated to the {tier} tier store: {n} bytes]"


def _full(rxs, s) -> bool:
    return isinstance(s, str) and any(rx.fullmatch(s) for rx in rxs)


def _obj(v) -> dict:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


def route_clean(body, delivery) -> bool:
    d = _obj(delivery)
    if not _full(DOOR_BODY_RX, body):
        return False
    if MIGRATED_RX.fullmatch(body) and not _obj(d.get("migrated")).get("pointer"):
        return False                                              # D2: a migrated marker names its pointer
    if any(k not in DOOR_KEYS for k in d):
        return False
    if d.get("rendered") is not None and not _full(DOOR_BODY_RX, d["rendered"]):
        return False
    return d.get("error") is None or bool(CLASSIFIED_RX.fullmatch(str(d["error"])))


def step_clean(content, meta) -> bool:
    if MIGRATED_RX.fullmatch(content or "") and not _obj(_obj(meta).get("migrated")).get("pointer"):
        return False
    return _full(STEP_RX, content)


def turn_clean(raw, prompt) -> bool:
    r = _obj(raw)
    return "withheld" in r and set(r) <= {"withheld", "usage", "migrated"} and (prompt is None or _full(PROMPT_RX, prompt))


def poll_clean(question, options) -> bool:
    return bool(MIGRATED_RX.fullmatch(question or "")) and bool(_obj(_obj(options).get("migrated")).get("pointer"))


def route_of(agent: str, channel: str, tier: str, routes=None) -> dict:
    """The ONE route `agent` serves on `channel`. It may already declare THIS tier; any other tier refuses."""
    hits = [r for ch, r, _ in (routes if routes is not None else R.declared_routes()) if ch == channel
            and r.get("agent") == agent]
    if len(hits) != 1:
        raise R.Refused(f"{agent} serves {len(hits)} {channel} route(s); the migration needs exactly one")
    t = R.route_tier(hits[0])
    if t not in (None, tier):
        raise R.Refused(f"the route already declares tier {t!r}, not {tier!r}")
    return hits[0]


def _transcript_dir(agent: str) -> Path:
    home = (R.REPO / "homes" / agent).resolve()
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(home))


def residuals(agent: str, tier: str) -> dict:
    """Copies of the history OUTSIDE the database, counted (a3 #55033). Never their names or contents."""
    td = _transcript_dir(agent)
    files = [p for p in td.glob("*.jsonl") if p.is_file()] if td.is_dir() else []
    mem = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(R.REPO.resolve())) / "memory"
    memf = [p for p in mem.glob("*") if p.is_file() and (agent in p.name.lower() or tier in p.name.lower())] \
        if mem.is_dir() else []
    chron = R.REPO / "memory" / "library" / "chronicle"
    eds = sum(1 for p in chron.glob("*.md") if agent in p.read_text(errors="replace")) if chron.is_dir() else 0
    return {"transcript_files": len(files), "transcript_bytes": sum(p.stat().st_size for p in files),
            "automemory_files": len(memf), "chronicle_editions": eds}


def _route_rows(cur, channel, chat):
    return cur.execute("SELECT id, body, delivery FROM messages WHERE thread = %s OR delivery->>'handle' = %s "
                       "ORDER BY id", (f"{PREFIX[channel]}:{chat}", f"{channel}:{chat}")).fetchall()


def census(cur, agent: str, channel: str, chat: str, tier: str) -> dict:
    """{table: [total, still text-bearing]} plus the residuals. Content-blind and identifier-blind."""
    rr = _route_rows(cur, channel, chat)
    polls = cur.execute("SELECT question, options FROM polls WHERE chat = %s", (chat,)).fetchall()
    steps = cur.execute("SELECT content, meta FROM steps WHERE agent = %s", (agent,)).fetchall()
    turns = cur.execute("SELECT raw_payload, input_prompt FROM turns WHERE agent = %s", (agent,)).fetchall()
    out = {"messages": [len(rr), sum(1 for _, b, d in rr if not route_clean(b, d))],
           "polls": [len(polls), sum(1 for q, o in polls if not poll_clean(q, o))],
           "steps": [len(steps), sum(1 for c, m in steps if not step_clean(c, m))],
           "turns": [len(turns), sum(1 for r, p in turns if not turn_clean(r, p))],
           "residuals": residuals(agent, tier)}
    db = sum(v[1] for k, v in out.items() if k != "residuals")
    out["database_clean"] = db == 0
    out["history_clean"] = db == 0 and not any(out["residuals"].values())
    return out


def migrate(cur, agent: str, channel: str, chat: str, tier: str, *, key: bytes, store: "R.TierStore",
            now: str | None = None) -> dict:
    """Move every text-bearing row (census's rule) into the tier store, in the caller's transaction. -> {table: n}."""
    lbl = R.label([tier])
    at = now or datetime.now(timezone.utc).isoformat()
    from psycopg.types.json import Jsonb

    def put(obj):
        blob = json.dumps(obj, default=str, sort_keys=True)
        return blob, {"pointer": store.put(lbl, blob), "body_mac": R.body_mac(key, blob), "tier": tier, "at": at}
    moved = {"messages": 0, "polls": 0, "steps": 0, "turns": 0}
    for rid, body, delivery in _route_rows(cur, channel, chat):
        if route_clean(body, delivery):
            continue
        d = _obj(delivery)
        blob, mig = put({"body": body, "delivery": {k: v for k, v in d.items() if k not in KEEP}})
        cur.execute("UPDATE messages SET body = %s, delivery = %s WHERE id = %s",
                    (marker(tier, len(blob.encode())), Jsonb({**{k: d[k] for k in KEEP if k in d}, "migrated": mig}),
                     rid))
        moved["messages"] += 1
    for mid, q, o, v in cur.execute("SELECT msg_id, question, options, votes FROM polls WHERE chat = %s",
                                    (chat,)).fetchall():
        if poll_clean(q, o):
            continue
        blob, mig = put({"question": q, "options": o, "votes": v})
        cur.execute("UPDATE polls SET question = %s, options = %s, votes = %s WHERE msg_id = %s AND chat = %s",
                    (marker(tier, len(blob.encode())), Jsonb({"migrated": mig}), Jsonb({}), mid, chat))
        moved["polls"] += 1
    for sid, c, m in cur.execute("SELECT id, content, meta FROM steps WHERE agent = %s", (agent,)).fetchall():
        if step_clean(c, m):
            continue
        blob, mig = put({"content": c})
        cur.execute("UPDATE steps SET content = %s, meta = %s WHERE id = %s",
                    (marker(tier, len(blob.encode())), Jsonb({**_obj(m), "migrated": mig}), sid))
        moved["steps"] += 1
    for tid, r, p in cur.execute("SELECT id, raw_payload, input_prompt FROM turns WHERE agent = %s",
                                 (agent,)).fetchall():
        if turn_clean(r, p):
            continue
        blob, mig = put({"raw_payload": r, "input_prompt": p})
        cur.execute("UPDATE turns SET raw_payload = %s, input_prompt = %s WHERE id = %s",
                    (Jsonb({"withheld": "migrated", "usage": _obj(r).get("usage"), "migrated": mig}),
                     marker(tier, len(blob.encode())), tid))
        moved["turns"] += 1
    return moved


def main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="python -m astryx.security.release_migrate")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--channel", required=True, choices=sorted(PREFIX))
    ap.add_argument("--tier", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if a.tier not in R.TIERS:
            raise R.Refused(f"{a.tier!r} is not a declared tier")
        chat = str(route_of(a.agent, a.channel, a.tier).get("chat"))
        key = R.mac_key() if a.apply else None              # no key → refused BEFORE anything is written
        import psycopg
        with psycopg.connect(R._dsn(), autocommit=False) as c, c.cursor() as cur:
            before = census(cur, a.agent, a.channel, chat, a.tier)
            print(json.dumps({"census_before": before}))
            if not a.apply:
                return 0
            moved = migrate(cur, a.agent, a.channel, chat, a.tier, key=key, store=R.TierStore())
            after = census(cur, a.agent, a.channel, chat, a.tier)
            if not after["database_clean"]:
                c.rollback()
                print(json.dumps({"moved": moved, "census_after": after, "error": "the database census is not 0 "
                                  "after the move: rolled back"}))
                return 1
            c.commit()
            print(json.dumps({"moved": moved, "census_after": after}))
            if not after["history_clean"]:
                print("history is NOT clean: the residuals outside the database stand (the owner's call)",
                      file=sys.stderr)
            return 0
    except R.Refused as e:
        print(json.dumps({"error": str(e)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
