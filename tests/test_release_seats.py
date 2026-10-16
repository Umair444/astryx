#!/usr/bin/env python3
"""Oracle for plan-9139 S1b's python half: the label's source and the seats that write through the one door.

  LABEL      label_of() reads `owner_private:<tier>` from the agent's charter (v4 D2a). A malformed private-looking
             grant REFUSES, never reads as unlabelled (a4 #46035); a route's undeclared tier refuses too
  SEND       send_row() for a labelled sender: to the owner → a stamped pointer row, no body, no chat id, and
             open_stamped() returns the body; to an agent → body withheld, thread derived, intent clamped; to a
             person's channel address → refused; no key → refused; every refusal writes NO row
  SEAT       step.py AUTO-DELIVER for a labelled member goes through send_row (the sentinel never lands in messages);
             refused → no row and a metadata-only error step; an UNLABELLED agent's AUTO-DELIVER is today's row
  CLI        `label` refuses a malformed grant (rc 1); `read` refuses another tier's pointer (rc 1)
Fixtures only: a temp root (charters, routes, tier store), short fixture ids (privacy gate), a stamped fixture DB,
a synthetic key. NOT covered here, stated: the session strip of turns.raw_payload (S1d) and the node seats (S1b-2).
Exit 0 pass · 1 fail · 77 no psycopg / no fixture DB.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security import release as R  # noqa: E402

fails = []
SENT = "S1B-SENTINEL-private-reply-4a7c"
KEY = "k" * 40


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except R.Refused as e:
        return e
    return None


root = Path(tempfile.mkdtemp(prefix="relseats."))
(root / "agents" / "canopus").mkdir(parents=True)
(root / "bridges").mkdir()
(root / "agents" / "canopus" / "member.md").write_text("# member\nGrants: browser, owner_private:career\n")
(root / "agents" / "plain.md").write_text("# plain\nGrants: gmail, contacts\n")
(root / "agents" / "peer.md").write_text("# peer\n")
ROUTE = {"chat": "101@s.whatsapp.net", "agent": "member", "enabled": True, "counterpart": "owner", "tier": "career"}
(root / "bridges" / "routes-whatsapp.json").write_text(json.dumps([ROUTE]))
R.REPO = root                                   # the module reads charters, routes and the store under its REPO
os.environ[R.MAC_KEY_ENV] = KEY

print("label:")
check("an exact grant labels the member {career}", R.label_of("member") == {"career"})
check("no private grant → ORG", R.label_of("plain") == R.ORG)
check("NO charter → REFUSED (UNKNOWN), never ORG: a moved or renamed member must not fall back to raw sends "
      "(a3 #46041)", isinstance(refused(R.label_of, "nobody"), R.GrantError))
# shipped examples are `<name>.example.md` or live under a `*.example/` dir (agents/abstractors.example/…): the org
# resolver excludes both; a raw rglob of `member.md` matched the second and refused the real member as a collision
(root / "agents" / "members.example").mkdir()
(root / "agents" / "members.example" / "member.md").write_text("# shipped example with the member's stem\n")
(root / "agents" / "member.example.md").write_text("# shipped example\n")
check("a shipped example twin of the member's stem does NOT collide (the org resolver excludes *.example)",
      R.label_of("member") == {"career"})
for bad in ("owner-private:career", "owner_private: career", "owner_private:Career", "owner_private:carrer",
            "career", "private_notes"):
    (root / "agents" / "bad.md").write_text(f"# bad\nGrants: gmail, {bad}\n")
    check(f"a malformed grant {bad!r} REFUSES, never reads unlabelled", isinstance(refused(R.label_of, "bad"),
                                                                              R.GrantError))
(root / "agents" / "bad.md").unlink()
(root / "agents" / "dup").mkdir()
(root / "agents" / "dup" / "member.md").write_text("# a second member\n")
check("two charters with one name → refused (ambiguous identity)", isinstance(refused(R.label_of, "member"),
                                                                              R.GrantError))
(root / "agents" / "dup" / "member.md").unlink()
(root / "bridges" / "routes-telegram.json").write_text(json.dumps([{"chat": "7", "agent": "x", "tier": "secret"}]))
check("a route declaring an undeclared tier → the route read refuses", isinstance(refused(R.declared_routes),
                                                                                   R.GrantError))
(root / "bridges" / "routes-telegram.json").unlink()

print("cli:")
(root / "agents" / "bad.md").write_text("# bad\nGrants: owner-private:career\n")
buf = io.StringIO()
with redirect_stdout(buf):
    rc = R.main(["label", "bad"])
check("`label` on a malformed grant → rc 1, named", rc == 1 and "not exactly" in buf.getvalue(), buf.getvalue())
(root / "agents" / "bad.md").unlink()
fam = R.TierStore().put(R.label(["family"]), "fam-body")
os.environ["ASTRYX_AGENT"] = "member"
buf = io.StringIO()
with redirect_stdout(buf):
    rc = R.main(["read", fam, R.body_mac(KEY.encode(), "fam-body")])
check("`read` of ANOTHER tier's pointer → rc 1, and no body", rc == 1 and "fam-body" not in buf.getvalue())

try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  db arms: {type(e).__name__}: {e}")
    print(f"\n{'FAIL' if fails else 'SKIP (partial)'}")
    sys.exit(1 if fails else 77)


def count(c, where="TRUE", args=()):
    return c.execute(f"SELECT count(*) FROM messages WHERE {where}", args).fetchone()[0]


def blob(c):
    return json.dumps([list(map(str, r)) for r in c.execute(
        "SELECT from_agent, to_agent, thread, intent, body, delivery FROM messages").fetchall()])


routes = R.declared_routes()
store = R.TierStore()
lbl = R.label(["career"])
try:
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        print("send_row:")
        rid = R.send_row(c.cursor(), "member", lbl, "owner", "anything", "chat", SENT, key=KEY.encode(), store=store,
                         routes=routes)
        row = c.execute("SELECT thread, body, delivery FROM messages WHERE id=%s", (rid,)).fetchone()
        rel = (row[2] or {}).get("release", {})
        check("to the owner: a row whose body is a size marker and whose thread is tier-<sender>",
              row[1].startswith("[released: ") and row[0] == "tier-member", str(row[:2]))
        check("…the sentinel and the chat id are ABSENT from every messages column",
              SENT not in blob(c) and "101@" not in blob(c))
        check("…and the stamped row opens to the body (open_stamped: stamp, tier dir, resolved-body MAC)",
              R.open_stamped(KEY.encode(), store, rid, rel.get("route_key"), lbl, rel.get("pointer"),
                             rel.get("body_mac"), rel.get("stamp")) == SENT)
        aid = R.send_row(c.cursor(), "member", lbl, "peer", "SENT-THREAD", "SENT-INTENT", SENT, key=KEY.encode(),
                         store=store, routes=routes)
        arow = c.execute("SELECT thread, intent, body FROM messages WHERE id=%s", (aid,)).fetchone()
        check("to an AGENT: body withheld, thread derived, intent clamped (a1 BC-2)",
              arow[0] == "tier-member" and arow[1] == "chat" and SENT not in arow[2], str(arow))
        n = count(c)
        check("to a person's channel address (wa-…) → refused, NO row",
              refused(R.send_row, c.cursor(), "member", lbl, "wa-555", None, "chat", SENT, key=KEY.encode(),
                      store=store, routes=routes) is not None and count(c) == n)
        check("to a GLOB that sanitises to an agent ('peer*') → refused, NO row (an identity is an exact name)",
              refused(R.send_row, c.cursor(), "member", lbl, "peer*", None, "chat", SENT, key=KEY.encode(),
                      store=store, routes=routes) is not None and count(c) == n)
        check("from a sender with no owner-only route → refused, NO row",
              refused(R.send_row, c.cursor(), "other", lbl, "owner", None, "chat", SENT, key=KEY.encode(),
                      store=store, routes=routes) is not None and count(c) == n)
        os.environ.pop(R.MAC_KEY_ENV)
        check("NO KEY → refused, NO row", refused(lambda: R.send_row(c.cursor(), "member", lbl, "owner", None, "chat",
                                                                     SENT, key=R.mac_key(), store=store,
                                                                     routes=routes)) is not None and count(c) == n)
        os.environ[R.MAC_KEY_ENV] = KEY

    print("seat (step.py AUTO-DELIVER):")
    # handle_stop back-fills turn_id onto the agent's sends inside the turn's window, and a row from the arms above
    # would then read as "already replied" and correctly skip the seat: start the seat arms on a clean table.
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        c.execute("DELETE FROM messages")
    spec = importlib.util.spec_from_file_location("step_under_test", REPO / "hooks" / "step.py")
    step = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(step)

    def stop(agent, inbound_from="owner"):
        with psycopg.connect(fx["dsn"]) as c:
            mid = c.execute("INSERT INTO messages (from_agent, from_org, to_agent, thread, body, status) VALUES "
                            "(%s,'whatsapp',%s,'wa:101@s.whatsapp.net','hi','delivered') RETURNING id",
                            (inbound_from, agent)).fetchone()[0]
            t = root / f"t-{agent}-{mid}.jsonl"
            now = "2026-10-11T00:00:00Z"
            t.write_text("\n".join(json.dumps(e) for e in [
                {"type": "user", "timestamp": now, "message": {"role": "user", "content":
                    f'<channel source="astryx" from="owner" thread="wa:101@s.whatsapp.net" msg_id="{mid}">hi'
                    f'</channel>'}},
                {"type": "assistant", "timestamp": now, "message": {"id": f"m{mid}", "role": "assistant",
                 "content": [{"type": "text", "text": SENT}], "usage": {"input_tokens": 1, "output_tokens": 1}}},
            ]) + "\n")
            before = c.execute("SELECT coalesce(max(id),0) FROM messages").fetchone()[0]
            res = step.handle_stop(c.cursor(), agent, {"transcript_path": str(t), "session_id": "s"})
            c.commit()
            new = c.execute("SELECT from_agent, to_agent, thread, body, delivery FROM messages WHERE id > %s",
                            (before,)).fetchall()
            errs = c.execute("SELECT content FROM steps WHERE agent=%s AND kind='error' ORDER BY id DESC LIMIT 1",
                             (agent,)).fetchone()
        return res, new, errs

    res, new, errs = stop("member")
    check("a labelled member's forgotten reply → ONE row through the door, to the owner, as a marker",
          len(new) == 1 and new[0][1] == "owner" and str(new[0][3]).startswith("[released: "), f"{new} {errs}")
    check("…the sentinel never lands in messages (body, thread, delivery)", SENT not in json.dumps(
        [list(map(str, r)) for r in new]))
    os.environ.pop(R.MAC_KEY_ENV)
    res, new, errs = stop("member")
    check("NO KEY at the seat → NO messages row, and a metadata-only error step says why",
          new == [] and errs and "auto-deliver withheld" in errs[0] and SENT not in errs[0], f"{new} {errs}")
    os.environ[R.MAC_KEY_ENV] = KEY
    (root / "agents" / "canopus" / "member.md").rename(root / "member.md.moved")
    res, new, errs = stop("member")
    check("the member's charter MOVED away → its forgotten reply is WITHHELD (no row), never the raw INSERT",
          new == [] and errs and "auto-deliver withheld" in errs[0] and SENT not in errs[0], f"{new} {errs}")
    (root / "member.md.moved").rename(root / "agents" / "canopus" / "member.md")
    res, new, errs = stop("plain")
    check("CONTROL: an UNLABELLED agent's AUTO-DELIVER is today's row (the body, on the src thread)",
          len(new) == 1 and new[0][3] == SENT and new[0][2] == "wa:101@s.whatsapp.net", str(new)[:200])
finally:
    _fx.__exit__(None, None, None)

print(f"\n{'FAIL: ' + str(len(fails)) + ' arm(s)' if fails else 'ALL PASS'}")
sys.exit(1 if fails else 0)
