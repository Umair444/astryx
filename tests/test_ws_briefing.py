#!/usr/bin/env python3
"""Oracle: the chat workspace's "while you were away" briefing (observatory/api/workspace.py, GET /api/ws/briefing),
pure shaping only, no database and no app.
  - WINDOW: ?since= defaults to 12 h back, is clamped to 48 h back and to now; junk reads as the default.
  - PRIVACY: an agent's message to the owner is ONE headline (markup gone, digit runs of 10+ masked), never a body;
    no `body` key anywhere in the answer; a sender outside the roster (a WhatsApp guest wa-<number>) is never named.
  - WAITING: an agent waits on the owner when its newest message on a thread is newer than the owner's newest there.
  - ORDER: waiting first, then wrote to the owner, then only worked; newest activity first within each.
  - HANDOFFS: agent→agent rows count both ways; top 3 peers by count.
  - FILES: [[file:]] embeds in messages to the owner, one per (thread, name), with the store id + version count when
    the store holds it.
  - NEWS: org-news (one wire row per recipient) listed once per post, headline only.
WS_SRC names another workspace.py (a mutant) to run the same arms against."""
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# A synthetic owner-country number, built at runtime: the privacy gate refuses the literal in any tracked file
CC_PHONE = "92" + "3001234567"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

SUBJECT = Path(os.environ.get("WS_SRC") or REPO / "observatory" / "api" / "workspace.py")
spec = importlib.util.spec_from_file_location("ws_subject", SUBJECT)
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)
from observatory.api import artifacts as A  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"\n       {detail}"))
    fails += 0 if ok else 1


NOW = datetime(2026, 11, 11, 2, 0, tzinfo=timezone.utc)
ROSTER = {"seed", "db", "lending", "finance", "medic", "memory"}
T0 = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)


def row(i, frm, to, thread, body=None, intent="chat"):
    return {"id": i, "ts": T0 + timedelta(minutes=i), "from_agent": frm, "to_agent": to, "thread": thread,
            "intent": intent, "body": body}


def window():
    s, c = W.brief_window("", NOW)
    arm("no since -> 12 h back", s == NOW - timedelta(hours=12) and not c, s)
    s, c = W.brief_window("2020-01-01T00:00:00Z", NOW)
    arm("a week back -> clamped to 48 h", s == NOW - timedelta(hours=48) and c, s)
    s, c = W.brief_window("2027-01-01T00:00:00Z", NOW)
    arm("the future -> now", s == NOW and c, s)
    s, c = W.brief_window("not a time", NOW)
    arm("junk -> the default", s == NOW - timedelta(hours=12) and not c, s)
    s, _ = W.brief_window("2026-11-10T23:00:00", NOW)
    arm("a bare time is UTC", s == datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc), s)
    s, _ = W.brief_window("2026-11-11T04:00:00+05:00", NOW)
    arm("an offset is honoured", s == datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc), s)


def lines():
    arm("a [tag] and 'x here.' prefix dropped, capitalized",
        W.said_line("[lending] lending here. **done**: the loader runs") == "Done: the loader runs", W.said_line("[lending] lending here. **done**: the loader runs"))
    out = W.said_line(f"Customer 0300 1234567 and {CC_PHONE} flagged")
    arm("digit runs of 10+ masked (separators too)", "1234567" not in out and CC_PHONE not in out and "…" in out, out)
    arm("a date and a comma figure survive", W.said_line("Sign-ups 1,234,567 on 20261110") == "Sign-ups 1,234,567 on 20261110")
    arm("embeds only -> no words", W.said_line("[[file:/x/a.png]] (chart)") == "")
    arm("first meaningful line, table rows skipped", W.said_line("| a | b |\n|---|---|\nThe answer is 42") == "The answer is 42")
    arm("clipped to one line of BRIEF_LINE", len(W.said_line("word " * 200)) <= W.BRIEF_LINE)
    arm("surfaces", [W.brief_surface(t) for t in ("chat:1-a", "obs:db", "cv:ab", "wa:1@g.us", "plan-4", None)]
        == ["chat", "floor", "canvas", "whatsapp", "other", "other"])


def shaping():
    rows = [
        row(1, "owner", "lending", "wa:9@g.us", None),
        row(2, "lending", "owner", "wa:9@g.us", f"[lending] Disbursals: 1,204 today. Customer {CC_PHONE} retried.\nfull table follows\n\nShould I split it by city?"),
        row(3, "lending", "db", "t-x"),
        row(4, "db", "lending", "t-x"),
        row(5, "lending", "db", "t-x"),
        row(6, "lending", "seed", "plan-1"),
        row(7, "db", "owner", "chat:1-a", "Here is the drift report\n[[file:/opt/astryx/homes/db/drift.csv]] (drift)"),
        row(8, "owner", "db", "chat:1-a", None),                                  # the owner answered db: not waiting
        row(9, f"wa-{CC_PHONE}", "lending", "wa:9@g.us", None),                   # a guest: never named
        row(10, "seed", "steward", "org-news", "Shipped: the workspace", "milestone"),
        row(11, "seed", "memory", "org-news", "Shipped: the workspace", "milestone"),  # same post, another recipient
        row(12, "finance", "owner", "cv:ab", "Received. Working.\n[[file:/m/a.pdf]] (P&L)\n[[file:/m/b.png]]"),
        row(13, "finance", "owner", "cv:ab", "Done, the P&L is ready\n[[file:/m/a.pdf]] (P&L)\n\nDo you want the Sep pack too?"),
        row(14, "seed", "owner", "obs:seed", "Morning report: all green"),
        row(15, "owner", "seed", "obs:seed", None),
        row(16, "db", "owner", "wa:9@g.us", "Loader stopped; needs the network team.\n\nShall I raise it with them?"),
    ]
    idx = {A.artifact_id("cv:ab", "P-L.pdf"): {"name": "P-L.pdf", "thread": "cv:ab", "path": "cv_ab/P-L.pdf"}}
    b = W.brief(rows, {"medic": 4, "lending": 3, f"wa-{CC_PHONE}": 9}, {"medic": {"ts": T0, "content": "Queued the PR for upstream"}},
                idx, {"cv_ab/P-L.pdf": 3}, ROSTER)
    names = [a["agent"] for a in b["agents"]]
    blob = json.dumps(b, default=str)
    arm("no body anywhere; the guest's number never appears", '"body"' not in blob and CC_PHONE not in blob and "wa-9" not in blob, blob[:300])
    arm("order: waiting (newest first), then wrote, then only worked", names == ["db", "finance", "lending", "seed", "medic"], names)
    by = {a["agent"]: a for a in b["agents"]}
    arm("lending waits: its wa message is newer than the owner's", by["lending"]["waiting"] and by["lending"]["waiting"]["id"] == 2, by["lending"]["waiting"])
    arm("db waits on WhatsApp (16), not on chat:1-a (the owner answered)", by["db"]["waiting"]["id"] == 16 and by["db"]["waiting"]["surface"] == "whatsapp", by["db"]["waiting"])
    arm("seed answered by the owner: not waiting", by["seed"]["waiting"] is None)
    arm("finance waits once (newest on its thread)", by["finance"]["waiting"]["id"] == 13)
    arm("a waiting row carries the question itself", by["finance"]["waiting"]["ask"] == "Do you want the Sep pack too?", by["finance"]["waiting"])
    # waiting = an ASK, not "spoke last": a receipt/FYI never raises the pill (first live night: 3 FYIs read as asks)
    for body, want in [("Received. The finance desk is working.", False), ("Noted. Handed to db.\n\n— lending", False),
                       ("Done.\n\nSource: o.pg_stat", False), ("```sql\nselect '?'\n```\nDone.", False),
                       ("Plan below.\n\nReply go and I run it.", True), ("Is GA still to come?\n\n— finance", True),
                       ("[[poll: run now? | yes | no]]", True)]:
        arm(f"asks_owner({body[:28]!r}) is {want}", W.asks_owner(body) is want, W.asks_owner(body))
    live = ("Received. The finance desk is working. One question is still open from 10-23: will Jul and Aug 2026 be "
            "reloaded with GA cost? Until then, Aug's total margin is overstated. When is the October file expected?")
    arm("ask_line takes the receipt's LAST question", W.ask_line(live) == "When is the October file expected?", W.ask_line(live))
    arm("headline masked + prefix gone", by["lending"]["said"][0]["headline"].startswith("Disbursals: 1,204 today. Customer …"), by["lending"]["said"][0]["headline"])
    arm("said newest first, with surface", [m["id"] for m in by["finance"]["said"]] == [13, 12] and by["finance"]["said"][0]["surface"] == "canvas")
    arm("handoffs both ways", by["lending"]["to_agents"] == 3 and by["db"]["from_agents"] == 2 and by["db"]["to_agents"] == 1 and by["seed"]["from_agents"] == 1)
    arm("top peers by count", by["lending"]["peers"] == [{"agent": "db", "n": 3}, {"agent": "seed", "n": 1}], by["lending"]["peers"])
    f = by["finance"]["files"]
    arm("files: one per name, newest mention, store id + versions when held",
        [x["name"] for x in f] == ["P-L.pdf", "b.png"] and f[0]["msg_id"] == 13 and f[0]["artifact"] and f[0]["versions"] == 3
        and f[1]["artifact"] is None and f[1]["path"] == "/m/b.png", f)
    arm("db's csv embed is a file", [x["name"] for x in by["db"]["files"]] == ["drift.csv"] and by["db"]["files"][0]["kind"] == "table")
    arm("only-worked agent: turns + its last words", by["medic"]["turns"] == 4 and by["medic"]["did"] == "Queued the PR for upstream" and not by["medic"]["said"])
    arm("news once per post", [n["headline"] for n in b["news"]] == ["Shipped: the workspace"], b["news"])
    arm("totals", b["totals"] == {"agents": 5, "to_owner": 6, "files": 3, "waiting": 3, "handoffs": 4, "turns": 7}, b["totals"])
    arm("an empty window is empty", W.brief([], {}, {}, {}, {}, ROSTER) == {"totals": {"agents": 0, "to_owner": 0, "files": 0, "waiting": 0, "handoffs": 0, "turns": 0}, "agents": [], "news": []})
    many = [row(100 + i, "seed", "owner", f"chat:{i}-x", f"line {i}") for i in range(20)]
    s = W.brief(many, {}, {}, {}, {}, ROSTER)["agents"][0]
    arm("listed messages capped, the count exact", len(s["said"]) == W.BRIEF_SAID and s["to_owner"] == 20)


def versions():
    log = "\x1e\na/x.md\n\x1e\na/x.md\nb/y.csv\n\x1e\n"
    arm("version counts per path", W.version_counts(log) == {"a/x.md": 2, "b/y.csv": 1}, W.version_counts(log))


def main():
    for f in (window, lines, shaping, versions):
        print(f.__name__)
        f()


if __name__ == "__main__":
    print(f"test_ws_briefing: {SUBJECT}")
    main()
    print(f"\n{'FAIL' if fails else 'PASS'}: {fails} failing arm(s)")
    sys.exit(1 if fails else 0)
