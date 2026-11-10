#!/usr/bin/env python3
"""Oracle: the chat workspace's full-text search (observatory/api/workspace.py, GET /api/ws/search), pure derivation
only, no database and no app:
  - ARGS: the ILIKE pattern escapes % _ \\ (the owner's "50%" is a literal); the tsquery is built from \\w words only as
    PREFIX terms (`quer:*`), so no to_tsquery syntax the owner types (& | ! : * ( ) ') ever reaches Postgres; a query
    with no word of 2+ characters has no tsquery (ILIKE carries it); an empty or blank query searches nothing.
  - SPANS: the whole phrase where it occurs, else every word STARTING with a term (the whole word marked), else a term
    inside a word; case-insensitive; overlapping spans merged.
  - SNIPPET: cut from the CLEANED body (no [[file:]] embed, no [project:] block, no [[ann:]] marker, no "[chat with]"
    line), "…" where cut, the marks are offsets INTO the snippet and point at the matched text; a hit only inside the
    hidden markup is no snippet at all.
  - HITS: an archived canvas chat and a non-owner surface are out; the owner's one message fanned out to several agents
    shows once; the limit holds; newest-first order is kept.
  - CHANGES: a send-changes body ([changes to <name>: vA (x) -> vB (y)] + note + a diff fence) reads "Changes to
    <name> (vA -> vB): <note>"; the diff is never a preview, a title or a snippet.
  - PLAIN: markdown marks (stars, ticks, heading hashes, a table's rule row) go, cell bars read " · ", snake_case stays.
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


def marked(cut):
    """the marked substrings of a (snippet, marks) pair"""
    text, marks = cut
    return [text[s:e] for s, e in marks]


def main():
    print("args")
    arm("blank searches nothing", W.search_args("") is None and W.search_args("   \n ") is None)
    like, ts = W.search_args("Revenue  check")
    arm("ILIKE carries the whole query, whitespace folded", like == "%Revenue check%", like)
    arm("tsquery = prefix terms joined by &", ts == "revenue:* & check:*", ts)
    like, ts = W.search_args("50%_off\\x")
    arm("ILIKE escapes % _ and \\", like == "%50\\%\\_off\\\\x%", like)
    _, ts = W.search_args("a & b | !c:* (d) 'e'")
    arm("one-letter words give no tsquery", ts == "", ts)
    _, ts = W.search_args("drop' & | !table:* (x)")
    arm("tsquery holds words only, never the owner's operators", ts == "drop:* & table:* & x:*", ts)
    _, ts = W.search_args("q q Q")
    arm("a repeated word once", ts == "", ts)
    _, ts = W.search_args("db db DB")
    arm("terms deduplicated case-insensitively", ts == "db:*", ts)
    arm("the query is capped", len(W.search_args("x" * 5000)[0]) == W.SEARCH_Q_MAX + 2)

    print("spans")
    arm("phrase wins", W.match_spans("The Revenue checks are in. revenue alone", "revenue check") == [(4, 18)])
    arm("else word prefixes, whole word marked", W.match_spans("querying the queries", "quer") == [(0, 8), (13, 20)])
    arm("a word start beats a hit inside a word", W.match_spans("conquer quest", "que") == [(8, 13)], W.match_spans("conquer quest", "que"))
    arm("inside a word only when nothing starts with it", W.match_spans("conquer", "quer") == [(3, 7)], W.match_spans("conquer", "quer"))
    arm("several terms, each word", W.match_spans("db answered seed", "seed db") == [(0, 2), (12, 16)])
    arm("overlaps merge", W.match_spans("aaaa", "aa") == [(0, 4)], W.match_spans("aaaa", "aa"))
    arm("no hit, no spans", W.match_spans("hello", "zebra") == [])

    print("snippet")
    body = "[chat with seed, db]\nPlease check the settlement totals for yesterday [[file:/x/y/report.pdf]] (report.pdf)"
    cut = W.snippet(body, "settlement")
    arm("the team line and the embed are gone", cut and "chat with" not in cut[0] and "[[file" not in cut[0] and "report.pdf" not in cut[0], cut)
    arm("marks point at the match", cut and marked(cut) == ["settlement"], cut)
    arm("a hit only inside an embed is no snippet", W.snippet(body, "report.pdf") is None)
    proj = "[project: Q4 close]\nsecret instructions about ledgers\n[/project]\nWhat changed in the ledger?"
    arm("a hit only inside the [project:] block is no snippet", W.snippet(proj, "instructions") is None)
    arm("the owner's words after the block still hit", marked(W.snippet(proj, "ledger")) == ["ledger"])
    ann = "[[ann:notes.md#a1]] > the margin quote\nwhy is this 12?"
    arm("an [[ann:]] marker never hits", W.snippet(ann, "notes.md") is None)
    long = ("word " * 80) + "needle " + ("tail " * 80)
    cut = W.snippet(long, "needle")
    arm("cut on both sides with …", cut[0].startswith("…") and cut[0].endswith("…"), cut[0][:40])
    arm("the cut keeps the match marked", marked(cut) == ["needle"], cut)
    arm("the snippet is bounded", len(cut[0]) <= W.SNIPPET + 2, len(cut[0]))
    arm("starts on a word", cut[0][1:5] == "word", cut[0][:8])
    cut = W.snippet("needle at the start " + "x " * 200, "needle")
    arm("no leading … when the match is near the start", not cut[0].startswith("…") and cut[1] == [[0, 6]], cut[1])
    cut = W.snippet("Ünïcode Straße und STRASSE", "straße")
    arm("unicode, case-insensitive", cut and marked(cut) == ["Straße"], cut)

    md = "**Revenue** by month:\n| Month | Revenue |\n|---|---:|\n| Aug | 11,521.2 |\n## Notes\n`d_dfs.financial_product_fact` holds it"
    cut = W.snippet(md, "revenue")
    arm("markdown flattened: no stars, no |---| rule, bars as ·", cut and "**" not in cut[0] and "---" not in cut[0] and "|" not in cut[0] and "Month · Revenue · Aug · 11,521.2" in cut[0], cut)
    arm("…and marks still point at the match", cut and marked(cut) == ["Revenue", "Revenue"], cut)
    arm("snake_case survives, heading hash and ticks go", "d_dfs.financial_product_fact holds" in W.plain(md) and "#" not in W.plain(md), W.plain(md))

    print("send-changes")
    ch = ("[chat with db, seed]\n[changes to report.md: v2 (db) → v4 (owner)]\nI tightened the summary; work from this.\n\n"
          "```diff\n@@ -3,4 +3,4 @@\n-Revenue rose 4%.\n+Revenue rose 4.2% (checked).\n```\n"
          "(37 more diff lines not shown: the attached file is the whole new version)\n[[file:/m/report.md]] (report.md)")
    arm("clean(): header summarized, note kept, diff + overflow line + embed gone",
        W.clean(ch) == "Changes to report.md (v2 → v4): I tightened the summary; work from this.", W.clean(ch))
    arm("first_line() (a title) is the summary", W.first_line(ch) == "Changes to report.md (v2 → v4):", W.first_line(ch))
    arm("a diff cut short by the 400-char preview still goes", W.clean(ch[:150]).endswith("work from this."), W.clean(ch[:150]))
    arm("a hit inside the diff is no snippet", W.snippet(ch, "checked") is None)
    arm("the note still hits", marked(W.snippet(ch, "tightened")) == ["tightened"])
    arm("a body that merely mentions changes is untouched", W.clean("see [changes to x] later") == "see [changes to x] later")

    print("hits")
    rows = [
        {"id": 9, "ts": "2099-12-31T10:00:09", "thread": "chat:a", "from_agent": "owner", "to_agent": "db", "body": "[chat with db, seed]\nthe revenue number"},
        {"id": 8, "ts": "2099-12-31T10:00:08", "thread": "chat:a", "from_agent": "owner", "to_agent": "seed", "body": "[chat with db, seed]\nthe revenue number"},
        {"id": 7, "ts": "2099-12-31T10:00:07", "thread": "cv:old", "from_agent": "owner", "to_agent": "lending", "body": "revenue on an archived canvas"},
        {"id": 6, "ts": "2099-12-31T10:00:06", "thread": "wa:1@g.us", "from_agent": "owner", "to_agent": "seed", "body": "revenue on whatsapp"},
        {"id": 5, "ts": "2099-12-31T10:00:05", "thread": "obs:db", "from_agent": "db", "to_agent": "owner", "body": "[[file:/m/revenue.xlsx]] (revenue.xlsx)"},
        {"id": 4, "ts": "2099-12-31T10:00:04", "thread": "obs:db", "from_agent": "db", "to_agent": "owner", "body": "Revenue was flat."},
        {"id": 3, "ts": "2099-12-31T10:00:03", "thread": "obs:seed", "from_agent": "seed", "to_agent": "owner", "body": "revenue again"},
    ]
    hits = W.search_hits(rows, "revenue", {"cv:old"}, 10)
    ids = [h["msg_id"] for h in hits]
    arm("fan-out once, archived/whatsapp/embed-only out, newest first", ids == [9, 4, 3], ids)
    h = hits[0]
    arm("a hit carries thread, msg, ts, from, snippet, marks",
        h["thread"] == "chat:a" and h["from"] == "owner" and h["snippet"] == "the revenue number" and h["marks"] == [[4, 11]], h)
    arm("the limit holds", [x["msg_id"] for x in W.search_hits(rows, "revenue", set(), 2)] == [9, 7])


if __name__ == "__main__":
    print(f"test_ws_search: {SUBJECT}")
    main()
    print(f"\n{'FAIL' if fails else 'PASS'}: {fails} failing arm(s)")
    sys.exit(1 if fails else 0)
