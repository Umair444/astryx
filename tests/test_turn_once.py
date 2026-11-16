#!/usr/bin/env python3
"""Oracle: a turn that a Stop hook's block made go on is ONE turn (hooks/step.py handle_stop; medic 12441).
A fixture database (this tree's schema.sql) and a synthetic transcript; hooks/step.py is loaded by path, its usage
reader stubbed (no network).
  T1 the second Stop of the same turn (stop_hook_active) rewrites the turn's row: one row, the whole turn's figures,
     the same id the first Stop stamped
  T2 the first Stop auto-delivers the forgotten reply to the person who asked; the continuation's Stop delivers
     NOTHING (its last words answer the hook, not the person)
Exit 0 · 1 · 77 (no database)."""
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
        cur.execute("""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, status, delivered_at)
                       VALUES ('wa-923000000000', 'whatsapp', 'seed', 'wa:923000000000@s.whatsapp.net', 'chat', 'hi', 'delivered', now())
                       RETURNING id""")
        mid = cur.fetchone()[0]
        u = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "t.jsonl"
            prompt = f'<channel source="astryx" from="wa-923000000000" thread="wa:923000000000@s.whatsapp.net" intent="chat" msg_id="{mid}">hi</channel>'
            tp.write_text(line("user", prompt, "2026-11-16T05:00:00Z") + line("assistant", [{"type": "text", "text": "Here is the answer."}], "2026-11-16T05:00:05Z", "a1", u))
            h = {"transcript_path": str(tp), "session_id": "s1"}
            r1 = S.handle_stop(cur, "seed", h)
            tp.write_text(tp.read_text() + line("assistant", [{"type": "text", "text": "That message needs no answer from me."}], "2026-11-16T05:00:09Z", "a2", u))
            r2 = S.handle_stop(cur, "seed", {**h, "stop_hook_active": True})
            cur.execute("SELECT id, tokens_out FROM turns WHERE agent='seed'")
            rows = cur.fetchall()
            arm("T1 one turn row, the same id both Stops returned, with the whole turn's output", len(rows) == 1 and r1[0] == r2[0] == rows[0][0] and rows[0][1] == 100, (rows, r1[0], r2[0]))
            cur.execute("SELECT body FROM messages WHERE from_agent='seed' ORDER BY id")
            sent = [b for (b,) in cur.fetchall()]
            arm("T2 the first Stop auto-delivers the forgotten reply; the continuation delivers nothing", sent == ["Here is the answer."], sent)
        conn.rollback()


try:
    main()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    fails.append(f"crashed: {type(e).__name__}")
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a continued turn is one turn and delivers nothing by itself")
sys.exit(1 if fails else 0)
