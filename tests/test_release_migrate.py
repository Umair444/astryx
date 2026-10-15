#!/usr/bin/env python3
"""Oracle for plan-9139 S1e (a3 BC-2, ruled #55033): src/astryx/security/release_migrate.py moves a labelled identity's
history into the tier store, and its census counts what is left.

  CENSUS   counts only, content-blind AND identifier-blind (D3): the output never carries a body, a chat, a thread or a
           handle. A row passes only on an EXACT anchored marker (D2); a migrated marker needs its pointer; a delivery
           key outside the door's set is text (D1); S1d's write-time step forms pass; residuals outside the database
           are counted and keep "history clean" false
  MOVE     on a sqlguard fixture DB: the route's rows (its thread, and its handle on any other thread), its chat's poll,
           the agent's steps and turns lose every text; a career member resolves each through read_for; the metadata
           the org runs on stays (message_id, toolreg meta, session_id, usage); rows of another agent or another
           thread keep their text (anti-vacuity); a door-era row (ingress, a release, an S1d step) is untouched; a
           second run moves nothing
  CLI      the default is the census only; --apply without a release key refuses before any write; route_of refuses
           0 or 2 routes and another tier
Exit 0 pass · 1 fail · 77 no fixture DB.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import importlib.util  # noqa: E402

if os.environ.get("RELEASE_MIGRATE_SRC"):
    import astryx.security  # noqa: E402
    from astryx.security import release as R  # noqa: E402
    spec = importlib.util.spec_from_file_location("astryx.security.release_migrate", os.environ["RELEASE_MIGRATE_SRC"])
    M = importlib.util.module_from_spec(spec)
    sys.modules["astryx.security.release_migrate"] = M
    spec.loader.exec_module(M)
else:
    from astryx.security import release as R  # noqa: E402
    from astryx.security import release_migrate as M  # noqa: E402

SENT = "S1E-SENTINEL-historic-career-text-61c0"
KEY = "m" * 40
CHAT = "20202@s.whatsapp.net"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{str(detail)[:300]}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


root = Path(tempfile.mkdtemp(prefix="relmig."))
home = Path(tempfile.mkdtemp(prefix="relmig_home."))
(root / "bridges").mkdir()
(root / "bridges" / "routes-whatsapp.json").write_text(json.dumps(
    [{"chat": CHAT, "agent": "member", "enabled": True},
     {"chat": "30303@g.us", "agent": "other", "enabled": True}]))
R.REPO = root
M.R.REPO = root
# the residual transcript lives under $HOME; the org's DSN authenticates through ~/.pgpass, so pin that file first
os.environ.setdefault("PGPASSFILE", str(Path.home() / ".pgpass"))
os.environ["HOME"] = str(home)
os.environ[R.MAC_KEY_ENV] = KEY
K = KEY.encode()

print("pure:")
check("an exact migrated marker WITH its pointer is clean",
      M.route_clean(M.marker("career", 12), {"migrated": {"pointer": "career/x"}, "message_id": "1"}))
check("D2: a marker with text after it is NOT clean", not M.route_clean(M.marker("career", 12) + f" {SENT}",
                                                                         {"migrated": {"pointer": "career/x"}}))
check("D2: a migrated marker WITHOUT a pointer is NOT clean", not M.route_clean(M.marker("career", 12), {}))
check("D1: a door marker body with a delivery key outside the door's set (a caption) is NOT clean",
      not M.route_clean("[tier-routed: 9 bytes, career]", {"caption": SENT}))
check("a released receipt (rendered = its marker, error classified) is clean",
      M.route_clean("[released: 9 bytes, career]", {"release": {}, "rendered": "[released: 9 bytes, career]",
                                                     "error": "text: RuntimeError", "door": "released"}))
check("…but a receipt whose rendered or error carries text is NOT", not M.route_clean(
    "[released: 9 bytes, career]", {"rendered": SENT}) and not M.route_clean(
    "[released: 9 bytes, career]", {"error": f"text: RuntimeError: {SENT}"}))
check("S1d's write-time step forms are clean; a migrated step needs its pointer",
      M.step_clean("Bash: [tier-labelled session]", None) and M.step_clean("[tier-labelled session: 9 bytes]", None)
      and M.step_clean("Bash done", None) and not M.step_clean(M.marker("career", 3), {})
      and not M.step_clean(f"Bash: {SENT}", None))
def _refuses(fn):
    try:
        fn()
    except R.Refused:
        return True
    return False


ROUTED = [("whatsapp", {"chat": CHAT, "agent": "member", "enabled": True, "tier": "career", "counterpart": "owner"},
           None)]
check("route_of: the one route of the agent on the channel, one already declaring THIS tier included",
      M.route_of("member", "whatsapp", "career", ROUTED)["chat"] == CHAT
      and M.route_of("member", "whatsapp", "career")["chat"] == CHAT)
check("route_of: 0 routes, 2 routes and a route declaring ANOTHER tier all refuse",
      _refuses(lambda: M.route_of("nobody", "whatsapp", "career"))
      and _refuses(lambda: M.route_of("member", "whatsapp", "career", ROUTED * 2))
      and _refuses(lambda: M.route_of("member", "whatsapp", "family", ROUTED)))

try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  db arms: {type(e).__name__}: {e}")
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)
    print(f"\n{'FAIL' if fails else 'SKIP (partial)'}")
    sys.exit(1 if fails else 77)

try:
    os.environ["ASTRYX_DSN"] = fx["dsn"]
    db = psycopg.connect(fx["dsn"], autocommit=True)
    J = json.dumps

    def msg(thread, body, delivery, frm="member"):
        return db.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, status, "
                          "delivery) VALUES (%s,'local','owner','local',%s,'chat',%s,'delivered',%s) RETURNING id",
                          (frm, thread, body, J(delivery) if delivery is not None else None)).fetchone()[0]
    receipt = {"ok": True, "handle": f"whatsapp:{CHAT}", "message_id": "w1", "rendered": SENT, "error": None}
    hist = [msg(f"wa:{CHAT}", f"career brief {i} {SENT}", receipt) for i in range(3)]
    bell = msg("t-x", f"doorbell {SENT}", receipt)                         # delivered TO the chat on another thread
    ingress = msg(f"wa:{CHAT}", "[tier-routed: 9 bytes, career]",
                  {"sender_jid": CHAT, "ingress": {"pointer": "career/abc", "body_mac": "m", "tier": "career"}})
    released = msg(f"wa:{CHAT}", "[released: 9 bytes, career]",
                   {"release": {"pointer": "career/def"}, "ok": True, "handle": "whatsapp:release",
                    "rendered": "[released: 9 bytes, career]", "error": None, "door": "released"})
    ctrl_thread = msg("wa:30303@g.us", f"another chat {SENT}", {"ok": True, "handle": "whatsapp:30303@g.us",
                                                                 "rendered": SENT})
    db.execute("INSERT INTO polls (msg_id, chat, agent, question, options, multi, votes) VALUES "
               "('p1', %s, 'member', %s, %s, 1, %s)", (CHAT, f"which {SENT}?", J([f"a {SENT}", "b"]), J({SENT: 1})))
    for c in (f"Bash: run {SENT}", f"Write: /tmp/{SENT}.md", "Bash: [tier-labelled session]"):
        db.execute("INSERT INTO steps (agent, kind, content, meta) VALUES ('member','tool',%s,%s)",
                   (c, J({"registry_id": "script:x", "v": 1})))
    db.execute("INSERT INTO steps (agent, kind, content) VALUES ('other','tool',%s)", (f"Bash: {SENT}",))
    for i in range(2):
        db.execute("INSERT INTO turns (agent, session_id, input_prompt, raw_payload) VALUES ('member',%s,%s,%s)",
                   (f"sid-{i}", f"do {SENT}", J({"messages": [SENT], "usage": {"tokens_in": 5}})))
    db.execute("INSERT INTO turns (agent, session_id, input_prompt, raw_payload) VALUES ('other','sid-o',%s,%s)",
               (f"do {SENT}", J({"messages": [SENT]})))
    td = home / ".claude" / "projects" / __import__("re").sub(r"[^A-Za-z0-9]", "-", str((root / "homes" / "member").resolve()))
    td.mkdir(parents=True)
    (td / "s.jsonl").write_text(SENT)

    print("census:")
    with db.cursor() as cur:
        before = M.census(cur, "member", "whatsapp", CHAT, "career")
    check("before: the route's 4 text rows of 6 (thread + handle), its poll, 2 of 3 steps, 2 turns are counted",
          before["messages"] == [6, 4] and before["polls"] == [1, 1] and before["steps"] == [3, 2]
          and before["turns"] == [2, 2] and not before["database_clean"], before)
    check("…the residuals outside the database are counted (a transcript file) and keep history unclean",
          before["residuals"]["transcript_files"] == 1 and before["residuals"]["transcript_bytes"] == len(SENT)
          and not before["history_clean"], before["residuals"])
    blob = J(before)
    check("…and the census is content-blind AND identifier-blind (no body, chat, thread or handle in it)",
          SENT not in blob and CHAT not in blob and "20202" not in blob and "wa:" not in blob, blob)

    print("cli:")
    import io
    from contextlib import redirect_stdout
    os.environ.pop(R.MAC_KEY_ENV)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_nokey = M.main(["--agent", "member", "--channel", "whatsapp", "--tier", "career", "--apply"])
    os.environ[R.MAC_KEY_ENV] = KEY
    still = db.execute("SELECT count(*) FROM messages WHERE body LIKE %s", (f"%{SENT}%",)).fetchone()[0]
    check("--apply with NO release key refuses before any write", rc_nokey == 1 and still == 5, (rc_nokey, still))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_dry = M.main(["--agent", "member", "--channel", "whatsapp", "--tier", "career"])
    check("the default is the census only: it prints census_before and writes nothing",
          rc_dry == 0 and "census_before" in buf.getvalue() and db.execute(
              "SELECT count(*) FROM messages WHERE body LIKE %s", (f"%{SENT}%",)).fetchone()[0] == 5, buf.getvalue())
    real_migrate = M.migrate
    M.migrate = lambda *a, **k: {"messages": 0, "polls": 0, "steps": 0, "turns": 0}     # a move that moved nothing
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_noop = M.main(["--agent", "member", "--channel", "whatsapp", "--tier", "career", "--apply"])
    M.migrate = real_migrate
    check("a move that leaves the database census non-zero is ROLLED BACK, rc 1",
          rc_noop == 1 and "rolled back" in buf.getvalue(), buf.getvalue()[-200:])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_apply = M.main(["--agent", "member", "--channel", "whatsapp", "--tier", "career", "--apply"])
    out = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.startswith("{")]
    moved = next((o["moved"] for o in out if "moved" in o), {})
    after = next((o["census_after"] for o in out if "census_after" in o), {})
    check("--apply moves the 4 route rows, the poll, 2 steps and 2 turns, and the database census reads 0",
          rc_apply == 0 and moved == {"messages": 4, "polls": 1, "steps": 2, "turns": 2}
          and after.get("database_clean") is True, (rc_apply, moved, after))
    check("…while the residual transcript keeps history_clean FALSE (the owner's call)",
          after.get("history_clean") is False, after)

    print("after the move:")
    mine = " ".join(r[0] for r in db.execute(
        "SELECT m::text FROM messages m WHERE id = ANY(%s)", (hist + [bell, ingress, released],)).fetchall())
    mine += " ".join(r[0] for r in db.execute("SELECT p::text FROM polls p WHERE chat=%s", (CHAT,)).fetchall())
    mine += " ".join(r[0] for r in db.execute("SELECT s::text FROM steps s WHERE agent='member'").fetchall())
    mine += " ".join(r[0] for r in db.execute("SELECT t::text FROM turns t WHERE agent='member'").fetchall())
    check("the sentinel is ABSENT from every migrated row (route, poll, steps, turns)", SENT not in mine,
          mine[mine.find(SENT) - 80:mine.find(SENT) + 20] if SENT in mine else "")
    ctrl = " ".join(r[0] for r in db.execute("SELECT m::text FROM messages m WHERE id=%s", (ctrl_thread,)).fetchall())
    ctrl += " ".join(r[0] for r in db.execute("SELECT s::text FROM steps s WHERE agent='other'").fetchall())
    ctrl += " ".join(r[0] for r in db.execute("SELECT t::text FROM turns t WHERE agent='other'").fetchall())
    check("…and PRESENT in another thread's and another agent's rows (anti-vacuity)", ctrl.count(SENT) >= 3, ctrl)
    d = db.execute("SELECT body, delivery FROM messages WHERE id=%s", (hist[0],)).fetchone()
    check("a migrated row: an exact marker, delivery = exactly the KEEP keys it had + migrated (message_id kept)",
          M.MIGRATED_RX.fullmatch(d[0]) and set(d[1]) <= M.KEEP and d[1].get("message_id") == "w1"
          and d[1]["migrated"]["tier"] == "career", d)
    rel = d[1]["migrated"]
    body = R.TierStore().get(rel["pointer"], R.label(["career"]))
    check("…its pointer resolves to the original body AND the receipt's rendered text, under the MAC",
          SENT in body and json.loads(body)["delivery"].get("rendered") == SENT
          and R.body_mac(K, body) == rel["body_mac"], body[:120])
    untouched = db.execute("SELECT body, delivery FROM messages WHERE id=%s", (ingress,)).fetchone()
    check("a door-era ingress row is untouched", untouched[0] == "[tier-routed: 9 bytes, career]"
          and "ingress" in untouched[1] and "migrated" not in untouched[1], untouched)
    st = db.execute("SELECT content, meta FROM steps WHERE agent='member' ORDER BY id").fetchall()
    check("steps: the toolreg meta stays beside migrated; S1d's form is untouched",
          all(m.get("registry_id") == "script:x" for _, m in st) and st[2][0] == "Bash: [tier-labelled session]"
          and "migrated" not in st[2][1] and all("migrated" in m for _, m in st[:2]), st)
    tu = db.execute("SELECT session_id, raw_payload FROM turns WHERE agent='member' ORDER BY id").fetchall()
    check("turns: session_id (spawn.sh resumes from it) and the usage block stay",
          [t[0] for t in tu] == ["sid-0", "sid-1"] and all(t[1].get("usage") == {"tokens_in": 5} for t in tu), tu)
    pl = db.execute("SELECT question, options, votes FROM polls WHERE chat=%s", (CHAT,)).fetchone()
    check("the poll: question an exact marker, options = its migrated pointer, votes emptied",
          M.MIGRATED_RX.fullmatch(pl[0]) and "pointer" in pl[1].get("migrated", {}) and pl[2] == {}, pl)

    print("idempotent:")
    with db.cursor() as cur:
        again = M.migrate(cur, "member", "whatsapp", CHAT, "career", key=K, store=R.TierStore())
    check("a second run moves NOTHING", again == {"messages": 0, "polls": 0, "steps": 0, "turns": 0}, again)
    print("the 0-row side of each WHERE (sqlguard's W), through the subject itself:")
    with db.cursor() as cur:
        empty = M.census(cur, "nobody", "whatsapp", "99999@s.whatsapp.net", "career")
    check("a census of an identity and chat with no history reads all zeros",
          all(v == [0, 0] for k, v in empty.items() if isinstance(v, list)), empty)
    with db.cursor() as cur:
        none_moved = M.migrate(cur, "nobody", "whatsapp", "99999@s.whatsapp.net", "career", key=K, store=R.TierStore())
    check("…and a move of it moves nothing", none_moved == {"messages": 0, "polls": 0, "steps": 0, "turns": 0},
          none_moved)
    GONE = "40404@s.whatsapp.net"
    msg(f"wa:{GONE}", f"gone {SENT}", {"ok": True}, frm="gone")
    db.execute("INSERT INTO polls (msg_id, chat, agent, question, options, multi, votes) VALUES "
               "('p2', %s, 'gone', %s, '[]', 1, '{}')", (GONE, f"q {SENT}"))
    db.execute("INSERT INTO steps (agent, kind, content) VALUES ('gone','tool',%s)", (f"Bash: {SENT}",))
    db.execute("INSERT INTO turns (agent, session_id, input_prompt, raw_payload) VALUES ('gone','sid-g',%s,'{}')",
               (f"do {SENT}",))

    class Vanishing:                    # an operator's cleanup lands while the move runs: every UPDATE then matches 0
        def __init__(self, cur):          # migrate() puts one blob per row, table by table, in this order
            self.cur, self.store = cur, R.TierStore()
            self.next = [("messages", "from_agent"), ("polls", "agent"), ("steps", "agent"), ("turns", "agent")]

        def put(self, lbl, blob):
            t, col = self.next.pop(0)            # the row being moved vanishes before its own UPDATE
            self.cur.execute(f"DELETE FROM {t} WHERE {col} = 'gone'")
            return self.store.put(lbl, blob)
    with db.cursor() as cur:
        gone = M.migrate(cur, "gone", "whatsapp", GONE, "career", key=K, store=Vanishing(cur))
    check("rows deleted mid-move: each was selected, its UPDATE matched nothing, nothing raised",
          gone == {"messages": 1, "polls": 1, "steps": 1, "turns": 1} and db.execute(
              "SELECT count(*) FROM steps WHERE agent='gone'").fetchone()[0] == 0, gone)
    db.close()
finally:
    _fx.__exit__(None, None, None)
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)
print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
