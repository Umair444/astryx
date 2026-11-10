#!/usr/bin/env python3
"""Oracle: the chat workspace's unified conversation list (observatory/api/workspace.py), pure derivation only, no
database and no app: the functions GET /api/ws/threads and PUT /api/ws/threads/meta are built from.
  - SURFACES: chat:/obs:/cv: are the owner's three surfaces; wa:, plan-, t:, a bare prefix and None are not.
  - LISTING: only threads the OWNER is a party of; an archived canvas chat drops out; pinned first, then newest.
  - AGENTS: live agents only (a canvas page, an invitee, the pulse never a recipient); a desk thread obs:<agent> and
    a canvas chat name their agent even before it has spoken (the composer must always have someone to send to).
  - TITLES: custom > the owner's first line (routing prefixes and file embeds stripped) > a canvas brief's name >
    the canvas shell's title > a name from the thread; never empty.
  - META: a patch never mutates its input; a blank title clears; unpinning the last field removes the entry.
  - ROLE: the first sentence of the charter's italic subtitle, multi-line subtitles too.
WS_SRC names another workspace.py (a mutant) to run the same arms against."""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

SUBJECT = Path(os.environ.get("WS_SRC") or REPO / "observatory" / "api" / "workspace.py")
spec = importlib.util.spec_from_file_location("ws_subject", SUBJECT)
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


ROSTER = {"seed", "db", "lending", "memory"}


def agg(thread, parties, last_ts, first_owner="hello", last_body="reply", count=2):
    return {"thread": thread, "parties": parties, "last_ts": last_ts, "first_owner": first_owner,
            "last_body": last_body, "last_from": parties[-1], "count": count}


def main():
    print("surfaces")
    arm("chat: is chat", W.surface_of("chat:20991231-abc") == "chat")
    arm("obs: is floor", W.surface_of("obs:seed") == "floor")
    arm("cv: is canvas", W.surface_of("cv:d7be445eb6") == "canvas")
    for t in ("wa:120@g.us", "plan-412", "t:xyz", "chat:", None, "", "observatory"):
        arm(f"{t!r} is not an owner surface", W.surface_of(t) is None)

    print("listing")
    aggs = [
        agg("chat:20991231-a", ["owner", "db", "seed", None], "2099-12-31T10:00:00"),
        agg("obs:seed", ["owner", "seed"], "2099-12-31T11:00:00"),
        agg("cv:aaa", ["owner", "lending", "canvas-1"], "2099-12-30T09:00:00"),
        agg("cv:bbb", ["cv-guest", "lending"], "2099-12-31T12:00:00"),            # an invitee's chat
        agg("cv:ccc", ["owner", "lending"], "2099-12-31T13:00:00"),               # archived
        agg("wa:123@g.us", ["owner", "seed"], "2099-12-31T14:00:00"),            # WhatsApp: never listed
        agg("plan-9", ["seed", "db"], "2099-12-31T15:00:00"),                    # agent-to-agent
    ]
    meta = {"cv:aaa": {"pinned": True}, "chat:20991231-a": {"title": "  Revenue   check "}}
    projects = [{"id": "q4", "threads": ["chat:20991231-a"]}]
    canvas = {"cv:ccc": {"archived": True, "agent": "lending"}, "cv:aaa": {"agent": "lending", "title": "Dash"}}
    rows = W.build_rows(aggs, meta, projects, ROSTER, canvas)
    ids = [r["thread"] for r in rows]
    arm("only the owner's chat/obs/cv threads, archived dropped", ids == ["cv:aaa", "obs:seed", "chat:20991231-a"], ids)
    arm("pinned first", rows[0]["pinned"] and not rows[1]["pinned"])
    arm("then newest first", ids[1:] == ["obs:seed", "chat:20991231-a"])
    by = {r["thread"]: r for r in rows}
    arm("custom title wins, whitespace folded", by["chat:20991231-a"]["title"] == "Revenue check" and by["chat:20991231-a"]["custom_title"])
    arm("project attached", by["chat:20991231-a"]["project"] == "q4" and by["obs:seed"]["project"] is None)
    arm("agents: live, non-owner, first-listed first", by["chat:20991231-a"]["agents"] == ["db", "seed"], by["chat:20991231-a"]["agents"])
    arm("a canvas page is never a recipient", by["cv:aaa"]["agents"] == ["lending"], by["cv:aaa"]["agents"])
    arm("surface carried", [r["surface"] for r in rows] == ["canvas", "floor", "chat"])
    arm("an empty input lists nothing", W.build_rows([], {}, [], ROSTER) == [])

    print("agents")
    arm("desk thread names its agent before it speaks", W.agents_of("obs:db", ["owner"], ROSTER) == ["db"])
    arm("canvas chat names its agent before it speaks", W.agents_of("cv:x", ["owner"], ROSTER, "lending") == ["lending"])
    arm("an unknown name on a desk thread is not invented", W.agents_of("obs:library-1f", ["owner", "memory"], ROSTER) == ["memory"])
    arm("no roster: pseudo-parties still excluded", W.agents_of("cv:x", ["owner", "canvas-3", "cv-ann", "seed"], set()) == ["seed"])

    print("titles")
    t = W.derive_title
    arm("first owner line", t("chat:x", None, "Find the drop\nin MAU please", None, []) == "Find the drop")
    arm("team prefix stripped", t("chat:x", None, "[chat with @db — everyone here reads this thread; reply on it]\nQ3 numbers", None, []) == "Q3 numbers")
    arm("embeds stripped", t("chat:x", None, "[[file:/m/upload/ab.png]] (shot.png)\nWhat is this", None, []) == "What is this")
    arm("embed only = Attachment", t("chat:x", None, "[[file:/m/upload/ab.png]] (shot.png)", None, []) == "Attachment")
    arm("canvas prefix stripped", t("cv:x", None, '[canvas #1 "Dash" v7] add a slope', None, []) == "add a slope")
    arm("canvas brief names the canvas", t("cv:canvas-1", None, 'NEW CANVAS #1 — "Lending Dashboard" (tier org) for owner.', None, []) == "Lending Dashboard")
    arm("canvas title when the owner never wrote", t("cv:x", None, None, "Hello there", ["seed"]) == "Hello there")
    arm("desk fallback", t("obs:seed", None, None, None, ["seed"]) == "Desk with Seed")
    arm("chat fallback names the agent", t("chat:x", None, None, None, ["db"]) == "Chat with Db")
    arm("never empty", t("chat:x", "   ", "", "", []) == "New chat")
    long = "x" * 200
    arm("clipped to TITLE_MAX with an ellipsis", len(t("chat:x", None, long, None, [])) == W.TITLE_MAX and t("chat:x", None, long, None, []).endswith("…"))

    print("meta")
    m0 = {"a": {"title": "T"}, "b": {"pinned": True}}
    m1 = W.apply_meta(m0, "a", pinned=True)
    arm("patch adds a pin, keeps the title", m1["a"] == {"title": "T", "pinned": True})
    arm("input never mutated", m0 == {"a": {"title": "T"}, "b": {"pinned": True}})
    arm("blank title clears", "title" not in W.apply_meta(m1, "a", title="  ")["a"])
    arm("an emptied entry is removed", "b" not in W.apply_meta(m0, "b", pinned=False))
    arm("title folded and capped", W.apply_meta({}, "c", title="a\n\n b" + "z" * 200)["c"]["title"].startswith("a b") and len(W.apply_meta({}, "c", title="z" * 300)["c"]["title"]) == W.TITLE_MAX)
    arm("valid_thread refuses WhatsApp and NUL", not W.valid_thread("wa:1@g.us") and not W.valid_thread("chat:a\x00") and W.valid_thread("obs:seed"))

    print("role")
    arm("multi-line italic subtitle, first sentence", W.role_of("# The seed\n*The founding agent. An astryx org ships\nwith one charter.*\n\nGrants: org") == "The founding agent.")
    arm("one-line subtitle", W.role_of("# db\n*The jazzcash database seat. A methodical mind.*\n## Identity") == "The jazzcash database seat.")
    arm("no subtitle: first prose line", W.role_of("# x\n\nGrants: org\nYou watch the pulse. Always.") == "You watch the pulse.")
    arm("empty charter: empty role", W.role_of("") == "")
    arm("metadata subtitle: the title's epithet", W.role_of("# medic — the org's physician\n*resident · ships with the genome ·\nmethods self-amendable*") == "The org's physician", W.role_of("# medic — the org's physician\n*resident · ships*"))

    print("preview")
    arm("clean drops embeds and folds", W.clean("[[file:/a/b.pdf]] (b.pdf)\n  see   attached ") == "see attached")
    pj = "[project: Q4 close]\nKeep it short.\n---\nFiles: [[file:/m/upload/ab.pdf]] (plan.pdf)\n[/project]\n[chat with @db — everyone here reads this thread; reply on it]\nWhat moved in October?"
    arm("a project chat's context block is hidden from the preview", W.clean(pj) == "What moved in October?", W.clean(pj))
    arm("... and from the title (custom > first line)", W.derive_title("chat:1-a", None, pj, None, ["db"]) == "What moved in October?")
    arm("a block cut short (no close) hides entirely, never leaks instructions", W.clean("[project: Q4]\nsecret-ish brief") == "")
    arm("a body that merely mentions [project: x] mid-text is untouched", W.clean("see [project: x]\nok") == "see [project: x] ok")
    arm("the SQL cuts the block before the 400-char clip", "[/project]" in W.THREADS_SQL and "+ 12" in W.THREADS_SQL)

    print("meta route (in-process, a temp estate; skipped without fastapi)")
    try:
        import json
        import tempfile
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        print("  SKIP  fastapi/httpx not importable")
        return
    est = Path(tempfile.mkdtemp())
    W.bind(lambda: None, est, roster=lambda: ROSTER)
    app = FastAPI()
    app.include_router(W.router)
    c = TestClient(app)
    r1 = c.put("/api/ws/threads/meta", json={"thread": "obs:seed", "pinned": True})
    r2 = c.put("/api/ws/threads/meta", json={"thread": "obs:seed", "title": " My  desk "})
    arm("pin then title accumulate", r1.status_code == 200 and r2.json() == {"thread": "obs:seed", "pinned": True, "title": "My desk"}, r2.text)
    arm("a WhatsApp thread is refused", c.put("/api/ws/threads/meta", json={"thread": "wa:1@g.us", "pinned": True}).status_code == 400)
    arm("an empty patch is refused", c.put("/api/ws/threads/meta", json={"thread": "obs:seed"}).status_code == 400)
    c.put("/api/ws/threads/meta", json={"thread": "obs:seed", "pinned": False, "title": ""})
    stored = json.loads((est / "chat" / "threads.json").read_text())
    arm("clearing both leaves nothing stored", stored == {"threads": {}}, stored)


if __name__ == "__main__":
    print(f"test_ws_threads: {SUBJECT}")
    main()
    print(f"\n{'FAIL' if fails else 'PASS'}: {fails} failing arm(s)")
    sys.exit(1 if fails else 0)
