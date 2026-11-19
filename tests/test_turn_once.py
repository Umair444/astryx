#!/usr/bin/env python3
"""Oracle: a turn that a Stop hook's block made go on is ONE turn (hooks/step.py handle_stop; medic 12441).
A fixture database (this tree's schema.sql) and a synthetic transcript; hooks/step.py is loaded by path, its usage
reader stubbed (no network).
  T1 the second Stop of the same turn (stop_hook_active) rewrites the turn's row: one row, the whole turn's figures,
     the same id the first Stop stamped
  T2 the first Stop auto-delivers the forgotten reply to the person who asked; the continuation's Stop delivers
     NOTHING (its last words answer the hook, not the person)
  T5 that delivery is ONE rule for every surface (address.SURFACES' persons): the web chat's owner and a signed-in
     member get their forgotten reply as a WhatsApp sender does; an agent's message gets none, nor a federated peer's
     'owner' or 'wa-<n>' (medic 12607)
Exit 0 · 1 · 77 (no database)."""
# synthetic numbers, built rather than written whole so no phone or JID shape sits in the source (devtools/privacy_gate.sh (c))
GROUP = "120363" + "000000000000"
N000 = "92" + "3000000000"
N223 = "92" + "3001112223"

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_turn_once", REPO, deps=("psycopg",), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

os.environ["ASTRYX_AGENT"] = "seed"
spec = importlib.util.spec_from_file_location("step_hook_once", REPO / "hooks" / "step.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
S.usage_snapshot = lambda cur, agent=None: None
S._label = lambda agent: (None, None)
S.TURN_CACHE = str(Path(tempfile.mkdtemp(prefix="turnonce.")) / "turn-{agent}.json")   # never the live agent's scope cache
S.cleaner = lambda: ((lambda o: o), True)          # no secrets in this fixture: a clean clone has no .env (medic 12455)
fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


def line(kind, content, ts, mid=None, usage=None):
    m = {"role": kind, "content": content}
    if usage:
        m.update(id=mid, model="claude-x", usage=usage)
    return json.dumps({"type": kind, "timestamp": ts, "message": m}) + "\n"


def main():
    import psycopg
    with fixture_db() as d, psycopg.connect(d["url"]) as conn:
        cur = conn.cursor()
        cur.execute(f"""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, status, delivered_at)
                       VALUES ('wa-{N000}', 'whatsapp', 'seed', 'wa:{N000}@s.whatsapp.net', 'chat', 'hi', 'delivered', now())
                       RETURNING id""")
        mid = cur.fetchone()[0]
        u = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "t.jsonl"
            prompt = f'<channel source="astryx" from="wa-{N000}" thread="wa:{N000}@s.whatsapp.net" intent="chat" msg_id="{mid}">hi</channel>'
            tp.write_text(line("user", prompt, "2026-11-16T05:00:00Z") + line("assistant", [{"type": "text", "text": "Here is the answer."}], "2026-11-16T05:00:05Z", "a1", u))
            h = {"transcript_path": str(tp), "session_id": "s1"}
            os.environ["ASTRYX_RUN_ON"] = "DeepSeek"          # spawn's stamp: the key this session runs on
            r1 = S.handle_stop(cur, "seed", h)
            tp.write_text(tp.read_text() + line("assistant", [{"type": "text", "text": "That message needs no answer from me."}], "2026-11-16T05:00:09Z", "a2", u))
            r2 = S.handle_stop(cur, "seed", {**h, "stop_hook_active": True})
            cur.execute("SELECT id, tokens_out FROM turns WHERE agent='seed'")
            rows = cur.fetchall()
            arm("T1 one turn row, the same id both Stops returned, with the whole turn's output", len(rows) == 1 and r1[0] == r2[0] == rows[0][0] and rows[0][1] == 100, (rows, r1[0], r2[0]))
            cur.execute("SELECT body FROM messages WHERE from_agent='seed' ORDER BY id")
            sent = [b for (b,) in cur.fetchall()]
            arm("T2 the first Stop auto-delivers the forgotten reply; the continuation delivers nothing", sent == ["Here is the answer."], sent)
            cur.execute("SELECT run_on FROM turns WHERE agent='seed'")
            arm("T3 the turn names the key its session ran on (turns.run_on, from ASTRYX_RUN_ON)", cur.fetchone() == ("DeepSeek",))
            os.environ.pop("ASTRYX_RUN_ON", None)
        conn.rollback()
        # T5 THE ONE RULE (owner 11-16: "a standard … we can't patch it by each channel"): a forgotten reply reaches any
        # PERSON (address.SURFACES), the web chat's owner and a signed-in member as WhatsApp did; an agent's message
        # opens a turn that auto-messages no one
        cur.execute("INSERT INTO peers (org, status) VALUES ('peer.example', 'introduced')")
        for who, org, thread, owed_ in (("owner", "local", "obs:seed", True), ("cv-pat.2", "local", "chat:20261116-t5", True),
                                        ("owner", "whatsapp", f"wa:{GROUP}@g.us", True), ("db", "local", "w:t5", False),
                                        # a federated peer names its own sender (gateway.py takes from_agent from its
                                        # envelope): 'owner' or 'wa-<number>' from a peer is not ours (medic 12607)
                                        ("owner", "peer.example", "t5-peer-owner", False), (f"wa-{N223}", "peer.example", "t5-peer-wa", False)):
            cur.execute("""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, status, delivered_at)
                           VALUES (%s, %s, 'seed', %s, 'chat', 'hi', 'delivered', now()) RETURNING id""", (who, org, thread))
            m5 = cur.fetchone()[0]
            with tempfile.TemporaryDirectory() as td:
                tp = Path(td) / "t.jsonl"
                tp.write_text(line("user", f'<channel source="astryx" from="{who}" thread="{thread}" intent="chat" msg_id="{m5}">hi</channel>', "2026-11-16T06:00:00Z")
                              + line("assistant", [{"type": "text", "text": f"answer for {who}"}], "2026-11-16T06:00:04Z", f"b{m5}", u))
                S.handle_stop(cur, "seed", {"transcript_path": str(tp), "session_id": f"t5-{m5}"})
            got = cur.execute("SELECT to_agent, thread, body FROM messages WHERE from_agent='seed' AND thread=%s", (thread,)).fetchall()
            arm(f"T5 {who} on {org} {thread.split(':')[0]}: " + ("its forgotten reply comes back to it on its thread" if owed_ else "auto-messages no one (an agent, or a peer's 'person')"),
                got == ([(who, thread, f"answer for {who}")] if owed_ else []), got)
        conn.rollback()
        # T6 a group member's message answered on its thread to the group ('owner', "@Ali …"), not to the member's own
        # name, is answered: the turn's last words are not posted to the group as a second message (owner 14225)
        cur.execute(f"""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, status, delivered_at)
                       VALUES ('wa-{N223}', 'whatsapp', 'seed', 'wa:{GROUP}@g.us', 'chat', 'how many?', 'delivered', now())
                       RETURNING id""")
        m6 = cur.fetchone()[0]
        cur.execute(f"""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body)
                       VALUES ('seed', 'local', 'owner', 'wa:{GROUP}@g.us', 'chat', '@Ali 334')""")
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "t.jsonl"
            tp.write_text(line("user", f'<channel source="astryx" from="wa-{N223}" thread="wa:{GROUP}@g.us" intent="chat" msg_id="{m6}">how many?</channel>', "2026-11-16T07:00:00Z")
                          + line("assistant", [{"type": "text", "text": "I have sent Ali the stats."}], "2026-11-16T07:00:04Z", "c1", u))
            S.handle_stop(cur, "seed", {"transcript_path": str(tp), "session_id": "t6"})
        got = [b for (b,) in cur.execute("SELECT body FROM messages WHERE from_agent='seed' ORDER BY id").fetchall()]
        arm("T6 a group reply to the group answers the member: no second post of the turn's last words", got == ["@Ali 334"], got)
        conn.rollback()
        # T7 a hand-off to an AGENT on the member's thread is no answer: the member still gets the forgotten reply
        # (medic 14233: merchant passing Saad's question to consumer on the group thread)
        cur.execute(f"""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, status, delivered_at)
                       VALUES ('wa-{N223}', 'whatsapp', 'seed', 'wa:{GROUP}@g.us', 'chat', 'active customers?', 'delivered', now())
                       RETURNING id""")
        m7 = cur.fetchone()[0]
        cur.execute(f"""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body)
                       VALUES ('seed', 'local', 'consumer', 'wa:{GROUP}@g.us', 'chat', 'over to you')""")
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "t.jsonl"
            tp.write_text(line("user", f'<channel source="astryx" from="wa-{N223}" thread="wa:{GROUP}@g.us" intent="chat" msg_id="{m7}">active customers?</channel>', "2026-11-16T08:00:00Z")
                          + line("assistant", [{"type": "text", "text": "Not my area; I have passed it to consumer."}], "2026-11-16T08:00:04Z", "d1", u))
            S.handle_stop(cur, "seed", {"transcript_path": str(tp), "session_id": "t7"})
        got = cur.execute("SELECT to_agent, body FROM messages WHERE from_agent='seed' ORDER BY id").fetchall()
        arm("T7 a hand-off to an agent on the member's thread is no answer: the member gets the forgotten reply",
            got == [("consumer", "over to you"), (f"wa-{N223}", "Not my area; I have passed it to consumer.")], got)
        conn.rollback()
        # T4 a turn that ends on a usage limit (StopFailure: no Stop runs) leaves one 'stopped' step in its own words,
        # in its turn's scope, so the chat's live line says why instead of a timer (owner 11-16)
        import io
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "t.jsonl"
            # the turn's own opening message, real and committed: the hook reads on its own connection, and a tag's id
            # counts only as a real message to this agent on the tag's thread (medic 13157 R3)
            mid = cur.execute("""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, status, delivered_at)
                                 VALUES ('owner', 'local', 'seed', 'obs:seed', 'chat', 'hi', 'delivered', now()) RETURNING id""").fetchone()[0]
            conn.commit()
            tp.write_text(line("user", f'<channel source="astryx" from="owner" thread="obs:seed" intent="chat" msg_id="{mid}">hi</channel>', "2026-11-16T09:50:00Z"))
            ev = {"hook_event_name": "StopFailure", "error": "rate_limit", "transcript_path": str(tp), "session_id": "s2",
                  "last_assistant_message": "You've hit your session limit · resets 2:50pm (Asia/Karachi)"}
            S.dsn, stdin = (lambda: d["url"]), sys.stdin
            sys.stdin = io.StringIO(json.dumps(ev))
            try:
                S.main()
            finally:
                sys.stdin = stdin
        with psycopg.connect(d["url"]) as c2:
            got = c2.execute("SELECT kind, content, meta->>'error', meta->'turn_msgs' FROM steps WHERE agent='seed' ORDER BY id DESC LIMIT 1").fetchone()
            arm("T4 StopFailure: one 'stopped' step, Claude Code's words, its error and its turn's opening message",
                got is not None and got[0] == "stopped" and got[1].startswith("You've hit your session limit") and got[2] == "rate_limit"
                and got[3] == [mid], got)


try:
    main()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    fails.append(f"crashed: {type(e).__name__}")
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a continued turn is one turn and delivers nothing by itself")
sys.exit(1 if fails else 0)
