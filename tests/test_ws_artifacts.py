#!/usr/bin/env python3
"""Oracle: the chat workspace's artifact store (observatory/api/artifacts.py; contract
homes/seed/chat-rebuild/ARTIFACTS_API.md). The store is a temp dir, the sources temp files under a temp estate bound
into chat.readable's gate; no database and no app.
  - IDENTITY: id = sha1(thread + "\\n" + name)[:16], deterministic; names reduced to a safe charset, a label keeps
    the source's extension; thread dirs carry no ':' and no '..'.
  - VERSIONS: import -> v1 by the posting agent; the same SOURCE again -> no new version; a changed source -> v2 by that
    agent; an owner save -> v3 by owner; an unchanged save -> 409; restore v1 -> v4 holding v1's bytes, message
    "restore <short> (v1)", history never rewritten; content by rev returns each version's bytes.
    RE-OPEN never reverts an owner edit: an unchanged source (or its bytes from a new path) is a no-op whatever the
    head holds; only a source that changed since its last import adds a version, by the agent.
  - ANNOTATIONS: empty etag first; a PUT with it lands and is committed; a stale etag is 412; an absent If-Match on an
    existing file is 412; a malformed annotation is 400; annotation commits are not versions.
  - MEDIA: every [[file:]] embed, with and without a label, oldest first, sender and kind attached.
  - SAFETY: a path outside the gate (an outside file, a '..' escape, a dot-path, an .env) is 403 and nothing lands;
    a non-hex id is 404; an oversize source is 413; a binary artifact refuses a save (415).
  - SERVING: the bytes decide the content type (an .html is text/plain; a .png is image/png); an .svg whose bytes ARE
    an SVG is image/svg+xml under SVG_CSP (sandbox, nothing fetched or run); an agent home's Claude scratchpad is
    readable through the gate, as bridges/embed_root lets it attach from there.
  - PROVENANCE (iteration 7): an import naming its message records source/msg/msg_ts on the version (trailers); a
    version without one answers nulls; bytes from a message OLDER than a recorded one never become the head
    (superseded); restore takes a message (a revert names whose change it undoes).
  - CREATE: words become a NEW text artifact, v1 by the author, .md added when the name is not text; the same words
    again are the same artifact; other words under a taken name get "name (2).md"; empty/bad thread/bad author refused.
ART_SRC names another artifacts.py (a mutant) to run the same arms against."""
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

SUBJECT = Path(os.environ.get("ART_SRC") or REPO / "observatory" / "api" / "artifacts.py")
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_ws_artifacts", REPO, deps=('fastapi', 'asyncpg', 'psycopg'), env=False)   # a clean clone (no venv): 77, not an import crash
spec = importlib.util.spec_from_file_location("art_subject", SUBJECT)
A = importlib.util.module_from_spec(spec)
sys.modules["art_subject"] = A          # pydantic resolves the models' annotations through it
spec.loader.exec_module(A)
from observatory.api import chat as C  # noqa: E402 — the gate the subject reads through
from astryx.security.serve import SVG_CSP  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def code_of(fn, *a):
    try:
        fn(*a)
        return 200
    except A.StoreError as e:
        return e.status


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ws-art-"))
    estate, media = tmp / "estate", tmp / "estate" / "media"
    home = estate / "homes" / "db"
    (media / "upload").mkdir(parents=True)
    home.mkdir(parents=True)
    C.bind(None, estate, media, REPO)
    S = A.Store(tmp / "store", max_bytes=1024 * 1024)
    T = "chat:20991231-abc"
    ts0 = datetime(2099, 12, 30, tzinfo=timezone.utc)

    print("identity")
    arm("id is sha1(thread\\nname)[:16]",
        A.artifact_id(T, "report.md") == hashlib.sha1(f"{T}\nreport.md".encode()).hexdigest()[:16])
    arm("id is deterministic", A.artifact_id(T, "a.csv") == A.artifact_id(T, "a.csv"))
    arm("id differs by thread", A.artifact_id(T, "a.csv") != A.artifact_id("obs:seed", "a.csv"))
    arm("name: basename of the path", A.artifact_name("/x/homes/db/out/q3.csv") == "q3.csv")
    arm("name: a label wins", A.artifact_name("/m/upload/1f.pdf", "Board deck.pdf") == "Board deck.pdf")
    arm("name: a label without extension keeps the source's",
        A.artifact_name("/m/upload/1f.png", "photo") == "photo.png", A.artifact_name("/m/upload/1f.png", "photo"))
    for bad in ("../../etc/passwd", "a/b/../c.md", ".env", "x:y\\z.md", "..", "x.md.annotations.json"):
        n = A.safe_name(bad)
        arm(f"name {bad!r} -> {n!r} is safe", "/" not in n and ":" not in n and not n.startswith(".")
            and not n.endswith(A.ANN) and n not in ("", ".", ".."))
    d = A.thread_dir("wa:../../x@g.us")
    arm("thread dir has no ':' and no escape", ":" not in d and "/" not in d and not d.startswith("."), d)
    arm("kinds", [A.kind_of(n) for n in ("a.md", "b.CSV", "c.py", "d.svg", "e.pdf", "f.docx", "g.xlsx", "h.bin")]
        == ["text", "table", "code", "image", "pdf", "docx", "sheet", "binary"])

    print("versions")
    src = home / "report.md"
    src.write_bytes(b"# Q3\nrevenue up\n")
    a1 = A.import_source(S, str(src), T, "db")
    arm("import -> v1", len(a1["versions"]) == 1 and a1["versions"][0]["n"] == 1, a1["versions"])
    arm("v1 authored by the agent", a1["versions"][0]["author"] == "db")
    arm("artifact shape", set(a1) == {"id", "thread", "name", "kind", "path_in_store", "size", "head", "versions"}
        and a1["id"] == A.artifact_id(T, "report.md") and a1["kind"] == "text" and a1["size"] == 16
        and a1["head"] == a1["versions"][0]["rev"] and len(a1["head"]) == 40, a1)
    arm("version shape", set(a1["versions"][0]) == {"rev", "short", "n", "author", "ts", "message", "source", "msg", "msg_ts"},
        a1["versions"][0])
    arm("no message named -> source recorded, msg null", a1["versions"][0]["source"] == str(src.resolve())
        and a1["versions"][0]["msg"] is None and a1["versions"][0]["msg_ts"] is None, a1["versions"][0])
    arm("stored under the thread dir", a1["path_in_store"] == "chat_20991231-abc/report.md", a1["path_in_store"])
    a1b = A.import_source(S, str(src), T, "db")
    arm("same bytes again -> no new version", a1b["head"] == a1["head"] and len(a1b["versions"]) == 1)
    src.write_bytes(b"# Q3\nrevenue up 4%\n")
    a2 = A.import_source(S, str(src), T, "db")
    arm("changed bytes -> v2 by the agent", len(a2["versions"]) == 2 and a2["versions"][0]["n"] == 2
        and a2["versions"][0]["author"] == "db", a2["versions"])
    a3 = S.save(a1["id"], "# Q3\nrevenue up 4% (owner note)\n", "my note")
    arm("save -> v3 by owner", a3["versions"][0]["n"] == 3 and a3["versions"][0]["author"] == "owner"
        and a3["versions"][0]["message"] == "my note", a3["versions"][0])
    arm("an unchanged save -> 409", code_of(S.save, a1["id"], "# Q3\nrevenue up 4% (owner note)\n") == 409)
    v1 = a3["versions"][-1]
    a4 = S.restore(a1["id"], v1["short"])
    arm("restore v1 -> v4 by owner", len(a4["versions"]) == 4 and a4["versions"][0]["author"] == "owner"
        and a4["versions"][0]["message"] == f"restore {v1['short']} (v1)", a4["versions"][0])
    arm("v4 holds v1's bytes", S.content(a1["id"])[0] == b"# Q3\nrevenue up\n")
    arm("history kept: v2's bytes by rev", S.content(a1["id"], a4["versions"][2]["rev"])[0] == b"# Q3\nrevenue up 4%\n")
    arm("newest first, numbered", [v["n"] for v in a4["versions"]] == [4, 3, 2, 1])
    arm("a rev of no version -> 404", code_of(S.content, a1["id"], "deadbeef") == 404)
    arm("restore to the head's bytes -> 409", code_of(S.restore, a1["id"], a4["head"]) == 409)
    a5 = A.import_source(S, str(src), T, "db")
    arm("owner edit kept: re-open with the source unchanged since import -> no new version, head stays",
        a5["head"] == a4["head"] and len(a5["versions"]) == 4 and S.content(a1["id"])[0] == b"# Q3\nrevenue up\n",
        a5["versions"][0])
    a5s = S.save(a1["id"], "# Q3\nowner's own words\n")
    a5b = A.import_source(S, str(src), T, "db")
    arm("re-open after a save -> head is still the owner's edit", a5b["head"] == a5s["head"]
        and a5b["versions"][0]["author"] == "owner" and S.content(a1["id"])[0] == b"# Q3\nowner's own words\n")
    alias = home / "alias" / "report.md"
    alias.parent.mkdir()
    alias.write_bytes(b"# Q3\nrevenue up 4%\n")                  # bytes this artifact already imported, a new path
    a5c = A.import_source(S, str(alias), T, "db")
    arm("an already-imported source's bytes from a new path -> no version", a5c["head"] == a5s["head"])
    src.write_bytes(b"# Q3\nrevenue up 5%\n")
    a6 = A.import_source(S, str(src), T, "db")
    arm("the source changed -> a new version by the agent", len(a6["versions"]) == 6
        and a6["versions"][0]["author"] == "db" and S.content(a1["id"])[0] == b"# Q3\nrevenue up 5%\n", a6["versions"][0])
    a6b = A.import_source(S, str(src), T, "db")
    arm("and again unchanged -> no-op", a6b["head"] == a6["head"])
    a4 = S.restore(a1["id"], v1["short"])                        # back to v1's bytes for the arms below
    arm("listed for its thread", [x["id"] for x in S.list(T)] == [a1["id"]] and S.list("chat:other") == [])
    up = media / "upload" / "1f2e.png"
    up.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    img = A.import_source(S, str(up), T, "owner", "chart")
    arm("an upload by label -> image artifact", img["name"] == "chart.png" and img["kind"] == "image"
        and img["versions"][0]["author"] == "owner", img)
    arm("a binary artifact refuses a save (415)", code_of(S.save, img["id"], "x") == 415)
    arm("newest first in the list", [x["id"] for x in S.list(T)][0] == img["id"])
    log = subprocess.run(["git", "-C", str(S.root), "log", "--format=%an <%ae>"], capture_output=True, text=True).stdout
    arm("commit authors are per-commit, @astryx.local", "db <db@astryx.local>" in log and "owner <owner@astryx.local>" in log)

    print("provenance")
    S2 = A.Store(tmp / "store2", max_bytes=1024 * 1024)   # its own store: the library arms below count S's
    T2 = "chat:20991231-prov"
    prov = home / "prov.md"
    prov.write_bytes(b"one\n")
    p1 = A.import_source(S2, str(prov), T2, "db", None, {"id": 100, "ts": "2099-12-31T10:00:00+00:00"})
    arm("v1 records its message", p1["versions"][0]["msg"] == 100 and p1["versions"][0]["msg_ts"] == "2099-12-31T10:00:00+00:00"
        and p1["versions"][0]["source"] == str(prov.resolve()), p1["versions"][0])
    arm("the subject stays the subject (trailers are not the message)", p1["versions"][0]["message"] == "import prov.md")
    prov.write_bytes(b"two\n")
    p2 = A.import_source(S2, str(prov), T2, "db", None, {"id": 120, "ts": "2099-12-31T11:00:00+00:00"})
    arm("a newer message's bytes -> v2 recording it", len(p2["versions"]) == 2 and p2["versions"][0]["msg"] == 120
        and p2["versions"][1]["msg"] == 100, [v["msg"] for v in p2["versions"]])
    old = home / "older" / "prov.md"
    old.parent.mkdir()
    old.write_bytes(b"zero\n")
    p3 = A.import_source(S2, str(old), T2, "db", None, {"id": 90, "ts": "2099-12-31T09:00:00+00:00"})
    arm("an OLDER message's other bytes never become the head -> superseded", p3.get("superseded") is True
        and p3["head"] == p2["head"] and S2.content(p1["id"])[0] == b"two\n", p3.get("superseded"))
    p4 = A.import_source(S2, str(prov), T2, "db", None, {"id": 90, "ts": "2099-12-31T09:00:00+00:00"})
    arm("an older message whose bytes ARE the head -> no version, not superseded", p4["head"] == p2["head"]
        and not p4.get("superseded"))
    arm("the library carries provenance too", next(x for x in S2.list_all() if x["id"] == p1["id"])["versions"]
        == S2.artifact(p1["id"])["versions"])
    arm("a hostile ts is reduced to a timestamp's charset", A.provenance({"id": 5, "ts": "x\nAstryx-Msg: 9"}, None)
        == "\n\nAstryx-Msg: 5\nAstryx-Msg-Ts: xAstryx-Msg: 9", repr(A.provenance({"id": 5, "ts": "x\nAstryx-Msg: 9"}, None)))
    rv = S2.restore(p1["id"], p1["versions"][0]["short"], "revert db's v2 (back to v1)")
    arm("restore with a message -> that subject, by owner", rv["versions"][0]["message"] == "revert db's v2 (back to v1)"
        and rv["versions"][0]["author"] == "owner" and rv["versions"][0]["msg"] is None and S2.content(p1["id"])[0] == b"one\n",
        rv["versions"][0])

    print("create")
    c1 = S2.create(T2, "Q3 answer", "# Q3\nrevenue up\n", "db", {"id": 130, "ts": "2099-12-31T12:00:00+00:00"})
    arm("words -> a NEW text artifact, .md added, v1 by the author", c1["name"] == "Q3 answer.md" and c1["kind"] == "text"
        and len(c1["versions"]) == 1 and c1["versions"][0]["author"] == "db" and c1["versions"][0]["msg"] == 130, c1)
    arm("it holds the words", S2.content(c1["id"])[0] == b"# Q3\nrevenue up\n")
    arm("the same words again -> the same artifact", S2.create(T2, "Q3 answer", "# Q3\nrevenue up\n", "db")["id"] == c1["id"])
    c2 = S2.create(T2, "Q3 answer.md", "other words\n", "db")
    arm("other words under a taken name -> 'name (2).md'", c2["name"] == "Q3 answer (2).md" and c2["id"] != c1["id"], c2["name"])
    arm("a non-text name gets .md", S2.create(T2, "data.json", "{}\n", "seed")["name"] == "data.json.md")
    tc = S2.create(T2, "Revenue by region.csv", "region,rev\nNorth,10\n", "db")
    arm("a table keeps .csv and is a table (a turn's table charted, iteration 9)", tc["name"] == "Revenue by region.csv"
        and tc["kind"] == "table" and tc["versions"][0]["author"] == "db", tc)
    arm("a hostile table name is still reduced", S2.create(T2, "../x.tsv", "a\tb\n", "db")["name"] == "x.tsv")
    arm("an editable text: the owner can save over it", S2.save(c1["id"], "# Q3\nrevenue up (checked)\n")["versions"][0]["n"] == 2)
    again = S2.create(T2, "Q3 answer", "# Q3\nrevenue up\n", "db")
    arm("the same turn opened again after an owner edit -> the EDITED document, not a '(n)' copy (iteration 11)",
        again["id"] == c1["id"] and again["versions"][0]["n"] == 2 and again["versions"][0]["author"] == "owner", again)
    other = S2.create(T2, "Q3 answer", "# Q3\nrevenue up\n", "seed")
    arm("the same words from ANOTHER author are not that document", other["id"] != c1["id"], other["name"])
    for label, args in (("empty text", (T2, "x", "  ", "db")), ("no thread", ("", "x", "t", "db")),
                        ("a bad author", (T2, "x", "t", "../db"))):
        arm(f"{label} -> 400", code_of(S2.create, *args) == 400)
    arm("oversize -> 413", code_of(S2.create, T2, "big", "x" * (1024 * 1024 + 1), "db") == 413)
    arm("a hostile name is reduced", "/" not in S2.create(T2, "../../etc/passwd", "p\n", "db")["path_in_store"].split("/", 1)[1])

    print("library")
    lib = S.list_all()
    arm("every artifact, one git log, newest head first", [x["id"] for x in lib][:2] == [img["id"], a1["id"]], [x["name"] for x in lib])
    one = next(x for x in lib if x["id"] == a1["id"])
    full = S.artifact(a1["id"])
    arm("the library's versions equal the artifact's own", one["versions"] == full["versions"] and one["head"] == full["head"])
    arm("+ author (who made v1) and updated (the head's time)", one["author"] == "db" and one["updated"] == full["versions"][0]["ts"], one)
    arm("the artifact shape plus author/updated only", set(one) == set(full) | {"author", "updated"}, set(one))
    arm("an empty store lists nothing", A.Store(tmp / "nostore").list_all() == [])

    print("export")
    exp = S.export(img["id"], media)
    arm("unchanged since import -> the source path itself (no copy)", exp == {"id": img["id"], "name": "chart.png", "path": str(up.resolve())}, exp)
    ex1 = S.export(a1["id"], media)                       # head = v1's bytes (restored), its source holds 5% now
    snap = Path(ex1["path"])
    arm("an owner-made head -> a snapshot under media/upload, the head's bytes",
        snap.parent == media / "upload" and snap.read_bytes() == S.content(a1["id"])[0] and snap.suffix == ".md", ex1)
    arm("the snapshot passes the file gate (an agent and the chip can read it)", C.readable(ex1["path"]) is not None)
    arm("the same head -> the same file, written once", S.export(a1["id"], media) == ex1)
    arm("an unknown id -> 404", code_of(S.export, "0" * 16, media) == 404)

    print("library media")
    rows2 = [{"id": 1, "ts": ts0, "from_agent": "owner", "thread": T, "body": "[[file:/m/upload/ab.png]] (chart)"},
             {"id": 4, "ts": ts0, "from_agent": "db", "thread": T, "body": "[[file:/m/upload/ab.png]] (chart)"},
             {"id": 6, "ts": ts0, "from_agent": "db", "thread": "obs:db", "body": "[[file:/h/homes/db/new.csv]]"}]
    lm = A.library_media(rows2, S.index())
    arm("one entry per (thread, file), newest mention first", [(x["thread"], x["msg_id"]) for x in lm] == [("obs:db", 6), (T, 4)], lm)
    arm("an embed the store holds names its artifact; one it doesn't is None",
        lm[1]["artifact"] == img["id"] and lm[0]["artifact"] is None, lm)

    print("annotations")
    g = S.annotations(a1["id"])
    arm("none yet: empty etag, no items", g == {"etag": "", "items": []}, g)
    ann = [{"id": "a1", "kind": "highlight", "color": "yellow", "anchor": {"quote": "revenue", "prefix": "# Q3\n",
            "suffix": " up", "start": 5, "end": 12}, "author": "owner", "ts": "2099-12-31T00:00:00Z"}]
    p1 = S.put_annotations(a1["id"], ann, "")
    arm("PUT with the empty etag lands", p1["items"] == ann and len(p1["etag"]) == 64, p1)
    arm("GET round-trips", S.annotations(a1["id"]) == p1)
    arm("a stale etag -> 412", code_of(S.put_annotations, a1["id"], ann + [dict(ann[0], id="a2")], "") == 412)
    p2 = S.put_annotations(a1["id"], ann + [dict(ann[0], id="a2", kind="comment", body="why?")], p1["etag"])
    arm("the current etag lands, new etag", len(p2["items"]) == 2 and p2["etag"] != p1["etag"])
    arm("the old etag is now stale -> 412", code_of(S.put_annotations, a1["id"], ann, p1["etag"]) == 412)
    arm("malformed -> 400", code_of(S.put_annotations, a1["id"], [{"id": "x", "kind": "scribble"}], p2["etag"]) == 400)
    arm("annotation commits are not versions", len(S.artifact(a1["id"])["versions"]) == 7)
    log1 = subprocess.run(["git", "-C", str(S.root), "log", "-1", "--format=%an|%s"], capture_output=True, text=True)
    arm("committed by owner as 'annotate'", log1.stdout.strip() == "owner|annotate", log1.stdout)

    print("media")
    ts = datetime(2099, 12, 31, tzinfo=timezone.utc)
    rows = [
        {"id": 9, "ts": ts, "from_agent": "db", "body": "here: [[file:/h/homes/db/q3.csv]] and [[file:/h/homes/db/x.pdf]] (Deck)"},
        {"id": 3, "ts": ts, "from_agent": "owner", "body": "[[file:/m/upload/ab.png]] (photo of whiteboard)"},
        {"id": 5, "ts": ts, "from_agent": "seed", "body": "no files"},
    ]
    m = A.parse_media(rows)
    arm("every embed, oldest first", [x["msg_id"] for x in m] == [3, 9, 9], m)
    arm("label + name + kind + sender", m[0] == {"path": "/m/upload/ab.png", "label": "photo of whiteboard",
        "name": "photo of whiteboard.png", "kind": "image", "from": "owner", "ts": ts.isoformat(), "msg_id": 3}, m[0])
    arm("no label -> basename", m[1]["label"] is None and m[1]["name"] == "q3.csv" and m[1]["kind"] == "table")
    arm("a label after the path", m[2]["label"] == "Deck" and m[2]["name"] == "Deck.pdf")
    arm("the id matches what open makes", A.artifact_id(T, m[1]["name"]) == A.artifact_id(T, A.artifact_name(
        "/h/homes/db/q3.csv")))

    print("version subjects = the carrying message's headline (iteration 12)")
    hs = home / "wallets.md"
    hs.write_bytes(b"v1\n")
    h1 = A.import_source(S, str(hs), T, "db", None, {"id": 501, "ts": "2099-12-31T10:00:00+00:00"},
                         "Active wallets 6.4% after the September close")
    arm("v1's message is the headline", h1["versions"][0]["message"] == "Active wallets 6.4% after the September close"
        and h1["versions"][0]["msg"] == 501, h1["versions"][0])
    hs.write_bytes(b"v2\n")
    h2 = A.import_source(S, str(hs), T, "db", None, {"id": 502, "ts": "2099-12-31T11:00:00+00:00"}, "Revised: 6.1%")
    arm("a new version takes ITS message's headline", h2["versions"][0]["message"] == "Revised: 6.1%"
        and h2["versions"][0]["msg"] == 502 and h2["versions"][0]["n"] == 2, h2["versions"][0])
    hs.write_bytes(b"v3\n")
    h3 = A.import_source(S, str(hs), T, "db", None, {"id": 503, "ts": "2099-12-31T12:00:00+00:00"})
    arm("no headline -> the generic subject", h3["versions"][0]["message"] == "new version of wallets.md", h3["versions"][0])

    import asyncio

    class Pool:
        def __init__(self, row):
            self.row, self.calls = row, []

        async def fetchrow(self, sql, *args):
            self.calls.append((sql, args))
            return self.row
    body = "[[file:/h/homes/db/wallets.md]] (wallets.md)\n## **Active wallets** 6.4% after the _September_ close\n\nmore"
    p = Pool({"body": body})
    A.bind(lambda: p, estate)
    got = asyncio.run(A.msg_headline(None, 501, T))
    arm("looked up by id: embed dropped, marks dropped", got == "Active wallets 6.4% after the September close", got)
    arm("scoped to the import's own thread AND the owner's conversations", p.calls and p.calls[0][1] == (501, T)
        and "thread = $2" in A.HEADLINE_SQL and "owner" in A.HEADLINE_SQL, p.calls)
    p.calls.clear()
    arm("a WhatsApp thread names nothing (no query)", asyncio.run(A.msg_headline(None, 501, "wa:1@g.us")) is None and not p.calls)
    arm("no message id names nothing", asyncio.run(A.msg_headline(None, None, T)) is None)
    arm("an id from elsewhere (no row) names nothing", (A.bind(lambda: Pool(None), estate), asyncio.run(A.msg_headline(None, 9, T)))[1] is None)
    arm("a body with no words of its own names nothing",
        (A.bind(lambda: Pool({"body": "[[file:/h/x.pdf]]"}), estate), asyncio.run(A.msg_headline(None, 9, T)))[1] is None)
    long = "Wallets " + "x" * 200
    arm("clipped to 80", len((A.bind(lambda: Pool({"body": long}), estate), asyncio.run(A.msg_headline(None, 9, T)))[1]) == A.HEADLINE_MAX)

    class Broken:
        async def fetchrow(self, *a):
            raise RuntimeError("db down")
    arm("no database -> the generic subject", (A.bind(lambda: Broken(), estate), asyncio.run(A.msg_headline(None, 9, T)))[1] is None)

    print("safety")
    outside = tmp / "outside.md"
    outside.write_text("secret")
    (home / ".claude").mkdir()
    (home / ".claude" / "s.md").write_text("x")
    (home / "x.env").write_text("K=v")
    for name, path in (("an outside file", str(outside)), ("a '..' escape", str(home / ".." / ".." / ".." / "outside.md")),
                       ("a home's dot-path", str(home / ".claude" / "s.md")), ("an .env", str(home / "x.env")),
                       ("/etc/passwd", "/etc/passwd"), ("a NUL", str(src) + "\x00"), ("empty", "")):
        arm(f"{name} -> 403", code_of(A.import_source, S, path, T, "db") == 403)
    arm("nothing outside landed", not any(p.name in ("outside.md", "s.md", "x.env", "passwd")
                                          for p in S.root.rglob("*") if ".git" not in p.parts))
    arm("a bad author -> 400", code_of(A.import_source, S, str(src), T, "../x") == 400)
    arm("no thread -> 400", code_of(A.import_source, S, str(src), "", "db") == 400)
    for bad in ("../../etc", "ZZZZZZZZZZZZZZZZ", a1["id"][:15], a1["id"] + "0", ""):
        arm(f"id {bad!r} -> 404", code_of(S.artifact, bad) == 404)
    big = home / "big.txt"
    big.write_bytes(b"x" * (1024 * 1024 + 1))
    arm("an oversize source -> 413", code_of(A.import_source, S, str(big), T, "db") == 413)

    print("serving")
    arm("html is text/plain", A.content_type("p.html", b"<script>1</script>").startswith("text/plain"))
    arm("csv is text/csv", A.content_type("a.csv", b"a,b\n1,2\n") == "text/csv; charset=utf-8")
    arm("png is image/png", A.content_type("a.png", b"\x89PNG\r\n\x1a\n\x00") == "image/png")
    arm("a .png that's text stays text", A.content_type("a.png", b"<svg onload=1>").startswith("text/plain"))
    arm("docx zip -> its OOXML type", A.content_type("a.docx", b"PK\x03\x04rest").endswith("wordprocessingml.document"))
    arm("unknown bytes -> octet-stream", A.content_type("a.bin", b"\x00\x01\xff") == "application/octet-stream")

    print("svg (11-11: the owner's avatar.svg never drew)")
    SVG = (b'<?xml version="1.0"?>\n<!-- a chart -->\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
           b'<style>rect{fill:#3a6}</style><rect width="8" height="8"/><script>alert(1)</script></svg>')
    arm("an .svg that IS one -> image/svg+xml (an <img> can draw it)", A.content_type("logo.svg", SVG) == "image/svg+xml",
        A.content_type("logo.svg", SVG))
    arm("an .svg that isn't one stays text/plain", A.content_type("x.svg", b"<html><script>1</script>").startswith("text/plain"))
    arm("svg bytes NOT named .svg stay text/plain", A.content_type("x.txt", SVG).startswith("text/plain"))
    arm("svg bytes named .png stay text/plain", A.content_type("x.png", SVG).startswith("text/plain"))
    sv = home / "chart.svg"
    sv.write_bytes(SVG)
    asv = A.import_source(S, str(sv), T, "db")
    page = home / "page.html"
    page.write_text("<script>alert(1)</script>")
    ahtml = A.import_source(S, str(page), T, "db")

    class Req:
        query_params: dict = {}
    real_store, A.store = A.store, (lambda: S)
    try:
        r = asyncio.run(A.art_content(asv["id"], Req(), None))
        rh = asyncio.run(A.art_content(ahtml["id"], Req(), None))
    finally:
        A.store = real_store
    csp = r.headers.get("content-security-policy", "")
    arm("the content route serves the svg as image/svg+xml", r.headers.get("content-type") == "image/svg+xml" and r.body == SVG,
        dict(r.headers))
    arm("its CSP is the svg one: a sandbox, nothing fetched or run, inline style allowed",
        csp == SVG_CSP and csp.startswith("sandbox;") and "default-src 'none'" in csp and "script-src" not in csp
        and "style-src 'unsafe-inline'" in csp, csp)
    arm("nosniff on the svg", r.headers.get("x-content-type-options") == "nosniff", dict(r.headers))
    arm("an .html keeps the plain sandbox CSP, text/plain", rh.headers.get("content-security-policy") == A.CSP
        and rh.headers.get("content-type", "").startswith("text/plain"), dict(rh.headers))

    print("scratchpads (11-11: db attached avatar.svg from its Claude scratchpad; the panel answered 404)")
    scratch = C.scratch_root(home)
    other = C.scratch_root(estate / "not-a-home")
    try:
        (scratch / "sess" / "scratchpad").mkdir(parents=True)
        (scratch / "sess" / ".claude").mkdir(parents=True)
        (other / "sess").mkdir(parents=True)
        ok = scratch / "sess" / "scratchpad" / "avatar.svg"
        ok.write_bytes(SVG)
        (scratch / "sess" / ".claude" / "s.json").write_text("{}")
        (other / "sess" / "x.svg").write_bytes(SVG)
        arm("an agent home's scratchpad is readable", C.readable(str(ok)) == ok.resolve())
        arm("a dot-path in a scratchpad is not", C.readable(str(scratch / "sess" / ".claude" / "s.json")) is None)
        arm("a scratchpad of no agent home is not", C.readable(str(other / "sess" / "x.svg")) is None)
        arm("the open imports it", code_of(A.import_source, S, str(ok), T, "db") == 200)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.rmtree(other, ignore_errors=True)

    print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
