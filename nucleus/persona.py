#!/usr/bin/env python3
"""astryx · persona — who each person actually IS to the owner, derived from how they talk.

THE ASK. "Do you have extracted chats with that person to build a persona of each one — so
you know who this person is to me." The people graph answers WHO EXISTS; it says nothing
about whether someone is a daily confidant or a contractor you messaged twice in March. A
personal-assistant org that cannot tell those apart will treat them the same, which is the
failure the whole people layer was built to end.

THE DESIGN DECISION THAT MATTERS: BEHAVIOUR, NOT TRANSCRIPTS. This reads message history
and stores NO MESSAGE TEXT — not a snippet, not a keyword, not a topic model. Everything
here is derived from metadata about the exchange: volume, span, cadence, who reaches out
first, how fast each side replies, what hours you talk, whether media flows.

That is a real constraint and it is chosen, not conceded. Storing chat content would create
the single most sensitive artifact this org has ever held — hundreds of people's private
conversations, about people who never agreed to anything, in a file that would ride every
backup. And the behavioural signals answer the actual question better than keywords would:
"you have talked most days for two years, he replies within minutes, and it is always after
23:00" tells you what a relationship IS. A bag of words tells you what it was about once.

If content-level personas are ever wanted, that is a separate decision with a separate
artifact and a separate conversation, not a quiet extension of this file.

WHAT THE SIGNALS MEAN, stated because a number nobody can interpret is decoration:
    cadence      how often a conversation happens, in days between exchanges
    balance      share of messages the OWNER sent — 0.5 is mutual, 0.9 is one-sided
    latency      median minutes to reply, each direction, which is the closest thing to
                 a measure of how much someone prioritises the other
    hours        the modal hour band — work-hours-only reads very differently from 01:00
    span         first to last contact, so a two-week burst is not mistaken for a decade

Library:
    signals(msgs, now_ts) -> dict     pure; testable without a channel
    shape(sig)            -> str      a human sentence, derived from the numbers
    build(limit=...)      -> dict     walk DM contacts, returns {personas, notes}
"""
from __future__ import annotations

import json
import statistics
import sys
import time as _time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Storage is social_person columns in postgres — the same store as the people graph,
# per the owner's postgres-for-everything ruling. No JSON cache: the tier/ file era
# ended when it produced a second store and a double-serve.

MIN_MSGS = 8            # below this, every derived statistic is noise
MAX_CONTACTS = 120      # bounded per run; busiest-first so the real relationships are covered
MSGS_PER_CONTACT = 300
BUDGET_S = 20           # the pulse kills a check at 30s — see people.py for the full reasoning


def signals(msgs: list[dict], now_ts: float | None = None) -> dict:
    """Behavioural signals for one conversation. PURE — no channel, no clock unless given,
    so the oracle can drive it with fixtures and get identical answers every run."""
    ts = []
    for m in msgs:
        t = m.get("Timestamp")
        if isinstance(t, (int, float)):
            ts.append((float(t), bool(m.get("FromMe")), m))
        elif isinstance(t, str) and t:
            try:
                from datetime import datetime
                ts.append((datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp(),
                           bool(m.get("FromMe")), m))
            except Exception:
                continue
    if len(ts) < 2:
        return {"messages": len(ts), "insufficient": True}
    ts.sort(key=lambda x: x[0])
    first, last = ts[0][0], ts[-1][0]
    mine = sum(1 for _, fm, _ in ts if fm)
    span_days = max(1.0, (last - first) / 86400)

    # Reply latency: a gap where the DIRECTION changes is someone answering.
    lat = {"mine": [], "theirs": []}
    for (t0, f0, _), (t1, f1, _) in zip(ts, ts[1:]):
        if f0 != f1:
            lat["mine" if f1 else "theirs"].append((t1 - t0) / 60.0)

    hours = [int((t % 86400) // 3600) for t, _, _ in ts]
    media = sum(1 for _, _, m in ts if m.get("MediaType"))
    now = now_ts if now_ts is not None else _time.time()
    return {
        "messages": len(ts),
        "first_ts": first,
        "last_ts": last,
        "span_days": round(span_days, 1),
        "days_since": round((now - last) / 86400, 1),
        "balance": round(mine / len(ts), 2),
        "cadence_days": round(span_days / max(1, len(ts) / 2), 2),
        "reply_mine_min": round(statistics.median(lat["mine"]), 1) if lat["mine"] else None,
        "reply_theirs_min": round(statistics.median(lat["theirs"]), 1) if lat["theirs"] else None,
        "modal_hour": max(set(hours), key=hours.count) if hours else None,
        "media_share": round(media / len(ts), 2),
        "insufficient": len(ts) < MIN_MSGS,
    }


def shape(sig: dict) -> str:
    """One sentence a human can act on. Numbers do not tell you who someone is; the
    RELATIONS between them do, and this is where that judgement is written down so it can
    be argued with rather than hidden in a chart."""
    if sig.get("insufficient"):
        return "too little history to characterise"
    bits = []
    c = sig["cadence_days"]
    bits.append("in contact most days" if c <= 1.5 else
                "weekly contact" if c <= 8 else
                "occasional contact" if c <= 45 else "rare contact")
    b = sig["balance"]
    if b >= 0.72:
        bits.append("you do most of the reaching out")
    elif b <= 0.28:
        bits.append("they do most of the reaching out")
    else:
        bits.append("mutual")
    rt, rm = sig.get("reply_theirs_min"), sig.get("reply_mine_min")
    if rt is not None and rt <= 15:
        bits.append("they reply fast")
    elif rt is not None and rt >= 720:
        bits.append("they are slow to reply")
    if rm is not None and rt is not None and rm > rt * 4:
        bits.append("you are the slower one")
    h = sig.get("modal_hour")
    if h is not None:
        bits.append("mostly late at night" if h >= 22 or h <= 4 else
                    "mostly work hours" if 9 <= h <= 17 else "mostly evenings")
    d = sig["days_since"]
    if d > 180:
        bits.append(f"dormant for {int(d)} days")
    if sig["span_days"] > 365:
        bits.append(f"known for {sig['span_days'] / 365:.1f} years")
    return "; ".join(bits)


def build(limit: int = MAX_CONTACTS, budget_s: float = BUDGET_S) -> dict:
    """Walk DM contacts busiest-first and derive a persona for each. Reads only; the raw
    text is never returned, stored, or logged."""
    from nucleus import people
    notes: list[str] = []
    chats = people._wa("chats", "list", "--limit", "500")
    if chats is None:
        return {"personas": {}, "notes": ["whatsapp unreachable — nothing derived (this is "
                                          "an UNREAD channel, not a person with no history)"]}
    if isinstance(chats, dict):
        chats = chats.get("chats") or chats.get("items") or []
    dms = [c for c in chats if str(c.get("jid", "")).endswith("@s.whatsapp.net")]
    dms.sort(key=lambda c: str(c.get("last_message_ts") or ""), reverse=True)
    todo = dms[:limit]
    if len(dms) > len(todo):
        notes.append(f"derived for the {len(todo)} most recently active of {len(dms)} direct "
                     f"contacts (bounded per run)")

    out: dict[str, dict] = {}
    started = _time.monotonic()
    done = 0
    for c in todo:
        if _time.monotonic() - started > budget_s:
            notes.append(f"TIME BUDGET reached after {done} of {len(todo)} contacts — "
                         f"partial but valid; the rest are underived, not characterless")
            break
        done += 1
        res = people._wa("messages", "list", "--chat", c["jid"],
                         "--limit", str(MSGS_PER_CONTACT))
        if res is None:
            continue
        msgs = res.get("messages") if isinstance(res, dict) else res
        sig = signals(msgs or [])
        if sig.get("messages", 0) < 2:
            continue
        out[people.pid(c["jid"])] = {
            "label": people._display(c.get("name"), c["jid"]),
            "shape": shape(sig),
            **{k: v for k, v in sig.items() if k not in ("first_ts", "last_ts")},
        }
    notes.append("personas are BEHAVIOURAL: derived from cadence, balance, latency and "
                 "hours. No message text, keyword or topic is read into the result.")
    return {"personas": out, "notes": notes}


def load_pg() -> dict:
    """id -> persona fields, from social_person. The one store."""
    from nucleus import people
    import psycopg
    dsn = people._dsn()
    if not dsn:
        return {}
    out = {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, relation, who, shape, confidence FROM social_person "
                    "WHERE org=%s AND kind='person'", (people._org(),))
        for i, rel, who, shp, conf in cur.fetchall():
            out[i] = {"relation": rel, "who": who, "shape": shp, "confidence": conf}
    return out


def apply_pg(personas: dict) -> int:
    """Write derived persona fields onto their social_person rows."""
    from nucleus import people
    import psycopg
    dsn = people._dsn()
    if not dsn:
        return 0
    n = 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for pid, per in personas.items():
                cur.execute(
                    "UPDATE social_person SET shape=%s, relation=COALESCE(%s,relation), "
                    "who=COALESCE(%s,who), confidence=COALESCE(%s,confidence) "
                    "WHERE org=%s AND id=%s",
                    (per.get("shape"), per.get("relation"), per.get("who"),
                     per.get("confidence"), people._org(), pid))
                n += cur.rowcount
        conn.commit()
    return n


def main() -> int:
    g = build()
    if not g["personas"]:
        for n in g["notes"]:
            print(f"  note: {n}")
        return 77
    n = apply_pg(g["personas"])
    print(f"  {n} social_person rows updated")
    rows = sorted(g["personas"].values(), key=lambda p: -p.get("messages", 0))
    print(f"  {len(rows)} personas derived\n")
    for p in rows[:12]:
        print(f"  {p['label'][:22]:<22} {p.get('messages',0):>5} msgs   {p['shape']}")
    print()
    for n in g["notes"]:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
