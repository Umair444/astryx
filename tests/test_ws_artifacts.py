#!/usr/bin/env python3
"""Oracle: the chat workspace's artifact store (observatory/api/artifacts.py; contract
homes/seed/chat-rebuild/ARTIFACTS_API.md). The store is a temp dir, the sources temp files under a temp estate bound
into chat.readable's gate; no database and no app.
  - IDENTITY: id = sha1(thread + "\\n" + name)[:16], deterministic; names reduced to a safe charset, a label keeps
    the source's extension; thread dirs carry no ':' and no '..'.
  - VERSIONS: import -> v1 by the posting agent; the same bytes again -> no new version; changed bytes -> v2 by that
    agent; an owner save -> v3 by owner; an unchanged save -> 409; restore v1 -> v4 holding v1's bytes, message
    "restore <short> (v1)", history never rewritten; content by rev returns each version's bytes.
  - ANNOTATIONS: empty etag first; a PUT with it lands and is committed; a stale etag is 412; an absent If-Match on an
    existing file is 412; a malformed annotation is 400; annotation commits are not versions.
  - MEDIA: every [[file:]] embed, with and without a label, oldest first, sender and kind attached.
  - SAFETY: a path outside the gate (an outside file, a '..' escape, a dot-path, an .env) is 403 and nothing lands;
    a non-hex id is 404; an oversize source is 413; a binary artifact refuses a save (415).
  - SERVING: the bytes decide the content type (an .html is text/plain; a .png is image/png).
ART_SRC names another artifacts.py (a mutant) to run the same arms against."""
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

SUBJECT = Path(os.environ.get("ART_SRC") or REPO / "observatory" / "api" / "artifacts.py")
spec = importlib.util.spec_from_file_location("art_subject", SUBJECT)
A = importlib.util.module_from_spec(spec)
sys.modules["art_subject"] = A          # pydantic resolves the models' annotations through it
spec.loader.exec_module(A)
from observatory.api import chat as C  # noqa: E402 — the gate the subject reads through

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
    arm("version shape", set(a1["versions"][0]) == {"rev", "short", "n", "author", "ts", "message"})
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
    arm("annotation commits are not versions", len(S.artifact(a1["id"])["versions"]) == 4)
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

    print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
