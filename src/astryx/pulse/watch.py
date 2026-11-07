"""A declarative watch's memory and its wake: pure, no database, no clock of its own (plan-12214, a4 #65062, #65074).

on=new    fires on rows absent from memory; an empty result clears it; with renag, a row still present fires again
          per row. on=while fires while the result is non-empty: at onset (after `after`), then every renag.
step() returns the wake and TWO next states, because whether the wake was accepted is only known in process():
  accepted    the wake was sent or held
  swallowed   say() found an earlier wake of this trigger still unread. Today's bug F1h: the pulse recorded the rows
              as seen and dropped the wake, so they were never told. Rows and clocks advance only on `accepted`;
              what doesn't depend on a wake (departures, while's first-true, the previous evaluation) advances on both.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CAP = 200                  # rows one evaluation reads; also the bound on stored row hashes
BODY = 2400                # room for rows in a wake: say() cuts at 3000, and a cut row would be consumed unseen
OVER_CAP_RENAG = timedelta(days=1)
STORM_K = 5                # evaluations in a row where nothing of the previous result survives


@dataclass
class Step:
    body: str | None = None
    accepted: dict = field(default_factory=dict)
    swallowed: dict = field(default_factory=dict)
    off: str | None = None


def row_key(row) -> str:
    return hashlib.sha256(repr(row).encode()).hexdigest()[:16]


def _at(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _fit(items: list, room: int) -> list:
    """The items whose reprs fit in `room`; at least one, so a huge row can't wedge the queue behind it."""
    out, used = [], 0
    for key, text in items:
        if out and used + len(text) + 1 > room:
            break
        out.append((key, text[:room]))
        used += len(text) + 1
    return out


def _new(rows: list, state: dict, renag: timedelta | None, now: datetime) -> Step:
    cur = {row_key(r): repr(r) for r in rows}
    seen = {k: v for k, v in state.get("seen", {}).items() if k in cur}      # a departure is always recorded
    prev = set(state.get("prev", []))
    churn = state.get("churn", 0) + 1 if prev and cur and not prev & set(cur) else 0
    base = {**state, "seen": seen, "prev": list(cur), "churn": churn}
    swallowed = dict(base)
    if churn >= STORM_K:
        return Step(f"storm: {churn} evaluations in a row returned none of the previous rows, so a column changes on "
                    "every read (now(), an age, a timestamp) and every row looks new. Select only columns that "
                    "identify the event, then `trigger action=enable`. This watch is off until then.",
                    accepted=base, swallowed=swallowed, off="storm")
    new = [(k, t) for k, t in cur.items() if k not in seen]
    due, soon = [], []
    if renag is not None:
        for k, _t in sorted(((k, seen[k]) for k in cur if k in seen), key=lambda x: x[1]):    # least recently fired first
            age = now - _at(seen[k])
            if age >= renag:
                due.append((k, cur[k]))
            elif age >= renag / 2:                     # a wake is going anyway: staggered rows share it (a3 BC-7)
                soon.append((k, cur[k]))
    if not new and not due:
        return Step(accepted=base, swallowed=swallowed)
    # Room is split while both groups have rows: a busy feed must not starve a stuck row, nor the reverse (a2 #65078).
    new_room = BODY if not due else (BODY // 2 if new else 0)
    shown_new = _fit(new, new_room) if new else []
    left = BODY - sum(len(t) + 1 for _, t in shown_new)
    shown_due = _fit(due, left) if due else []
    left -= sum(len(t) + 1 for _, t in shown_due)
    shown_soon = []
    if left > 0 and soon:
        fit = _fit(soon, left)
        shown_soon = fit if sum(len(t) + 1 for _, t in fit) <= left else []
    still = shown_due + shown_soon
    head = [f"{len(new)} new" + (f", showing {len(shown_new)}" if len(shown_new) < len(new) else "")] if new else []
    if still:
        head.append(f"{len(due) + len(soon)} still present" + (f", showing {len(still)}"
                                                               if len(still) < len(due) + len(soon) else ""))
    lines = [t for _, t in shown_new]
    if still:
        lines += ["still present:"] + [t for _, t in still]
    more = len(shown_new) < len(new) or len(shown_due) < len(due)
    tail = "\nThe rest come in the next wakes; run your query to see them now." if more else ""
    stamp = now.isoformat()
    accepted = {**base, "seen": {**seen, **{k: stamp for k, _ in shown_new + still}}}
    return Step("; ".join(head) + ":\n" + "\n".join(lines) + tail, accepted=accepted, swallowed=swallowed)


def _while(rows: list, state: dict, after: timedelta | None, renag: timedelta | None, now: datetime) -> Step:
    if not rows:
        clear = {k: v for k, v in state.items() if k not in ("since", "last")}
        return Step(accepted=clear, swallowed=clear)
    since = state.get("since") or now.isoformat()
    base = {**state, "since": since}                                    # a first-true persists with no wake at all
    if after is not None and now - _at(since) < after:
        return Step(accepted=base, swallowed=base)
    last = _at(state.get("last"))
    if last is not None and (renag is None or now - last < renag):
        return Step(accepted=base, swallowed=base)
    text = repr(rows)
    shown = text[:BODY] + (f"\n(cut at {BODY} bytes; run your query for the rest)" if len(text) > BODY else "")
    return Step(f"condition true since {since} ({len(rows)} rows): {shown}",
                accepted={**base, "last": now.isoformat()}, swallowed=base)


def step(rows: list, over_cap: bool, on: str, state: dict, *, after: timedelta | None = None,
         renag: timedelta | None = None, now: datetime, ms: int | None = None) -> Step:
    state = {k: v for k, v in (state or {}).items() if k != "last_digest"}   # the old whole-result digest
    if ms is not None:
        state["eval_ms"] = ms
    if over_cap:
        last = _at(state.get("over_cap"))
        base = {**state, "over_cap": state.get("over_cap")}
        if last is not None and now - last < OVER_CAP_RENAG:
            return Step(accepted=base, swallowed=base)
        return Step(f"this watch returned more than {CAP} rows, so it can't tell what is new and is NOT watching. "
                    "Narrow the query. It says this again daily while it stays over.",
                    accepted={**state, "over_cap": now.isoformat()}, swallowed=base)
    state.pop("over_cap", None)
    if on == "while":
        return _while(rows, state, after, renag, now)
    return _new(rows, state, renag, now)
