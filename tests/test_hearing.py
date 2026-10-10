#!/usr/bin/env python3
"""Oracle: hearing S2 (plan-8674, a4 #42048 D3 + D5): hear() workers, the dispatcher's validation, the POINTER, the
wake, span-fetch and fence redaction. Each arm has its RED control.

  WORKER    a `while True` hear() is killed at its deadline and the next utterance still reaches the other agents;
            three overruns in a row bench it. A hear() that print()s its utterance puts 0 bytes of it on the
            parent's stdout/stderr (RED control: the same hear() run in-process prints it). The worker's env has
            no DSN although the parent's does; it can't see /home or open a socket to postgres.
  VALIDATE  a pass naming another agent, or a name not in the utterance, is rejected; a span is clamped to 30 words
            from the name; without bwrap nothing runs at all.
  POINTER   (fixture DB) `hearings` has no text column; speaker_verified=true and a 31-word span are refused.
            A recorded hearing wakes its agent with a body holding NO word of the utterance (RED control: the words
            are in the utterance row). Over the hourly cap: a pointer row with woke=false and no message.
  FETCH     the owner of the hearing gets exactly the fenced span; another agent gets nothing (2); after the day's
            partition is dropped the hearing is expired (3); fetched_at is stamped.
  FENCE     hooks/step.py's cleaner drops the fenced words and keeps the pointer (RED control: the secret
            redaction alone keeps the words).
Needs bwrap for WORKER, and a DSN that can CREATE DATABASE (the sqlguard fixture) for POINTER/FETCH, else 77.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

if not shutil.which("bwrap"):
    print("SKIP: no bwrap on this host; VERIFIED NOTHING")
    sys.exit(77)
from nucleus import ear_fence as F  # noqa: E402
from nucleus import hear_pool as H  # noqa: E402

fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


HEARS = {
    "seed": 'def hear(u):\n    return {"decision": "pass", "matched_name": "seed"} if "seed" in u["text"].lower() '
            'else {"decision": "ignore"}\n',
    "loopy": "def hear(u):\n    while True:\n        pass\n",
    "chatty": 'import sys\ndef hear(u):\n    print("LEAK", u["text"])\n    print("LEAK", u["text"], file=sys.stderr)\n'
              '    return {"decision": "ignore"}\n',
    "probe": 'import os, socket\ndef hear(u):\n    r = {"env": sorted(os.environ), "home": os.path.exists("/home")}\n'
             '    try:\n        socket.create_connection(("127.0.0.1", 5432), 1); r["net"] = "open"\n'
             '    except OSError as e:\n        r["net"] = type(e).__name__\n    return {"decision": "ignore", "probe": r}\n',
}
tmp = Path(tempfile.mkdtemp(prefix="hearing-"))
for a, src in HEARS.items():
    (tmp / a).mkdir()
    (tmp / a / "hear.py").write_text(src)
SECRET = "zebra quantum marmalade"

print("WORKER")
os.environ["ASTRYX_DSN"] = "postgresql://planted@127.0.0.1/never"        # the parent HAS a DSN; the worker must not
w = H.Worker("probe", tmp / "probe" / "hear.py")
pr = w.ask({"id": 1, "ts": "t", "text": "x", "view": "v"}, 3.0).get("probe", {})
w.stop()
want("RED control: the parent's env carries ASTRYX_DSN", "ASTRYX_DSN" in os.environ)
want("the worker's env is PATH, LANG (and bwrap's PWD) only: no DSN", set(pr.get("env", ["?"])) <= {"PATH", "LANG", "PWD"},
     str(pr))
want("the worker can't see /home (no .env, no repo)", pr.get("home") is False, str(pr))
want("the worker can't reach postgres", pr.get("net") not in (None, "open"), str(pr))

pool = H.Pool(tmp, 200)
want("every hear.py is attending", pool.attending() == ["chatty", "loopy", "probe", "seed"], str(pool.attending()))
t0 = time.monotonic()
got = pool.hear({"id": 1, "ts": "t", "text": "seed, can you hear me", "view": "v"})
want("seed passes although loopy never returns", [a for a, _ in got] == ["seed"], str(got))
want("loopy was killed at its deadline (counted as an overrun)", pool.counts()["loopy"]["overrun"] == 1, str(pool.counts()))
for _ in range(2):
    pool.hear({"id": 2, "ts": "t", "text": "seed again", "view": "v"})
c = pool.counts()["loopy"]
want("three overruns in a row bench it", c["overrun"] == 3 and c["benched_now"], str(c))
t0 = time.monotonic()
got = pool.hear({"id": 3, "ts": "t", "text": "seed once more", "view": "v"})
want("a benched worker costs nothing and seed still passes", [a for a, _ in got] == ["seed"]
     and pool.counts()["loopy"]["benched"] == 1, str(pool.counts()))
pool.close()

leak = subprocess.run([sys.executable, "-c", (
    "import sys; sys.path.insert(0, %r)\nfrom pathlib import Path\nfrom nucleus import hear_pool as H\n"
    "p = H.Pool(Path(%r), 2000); p.hear({'id': 1, 'ts': 't', 'text': %r, 'view': 'v'}); p.close()")
    % (str(REPO), str(tmp), SECRET)], capture_output=True, text=True, timeout=60)
want("a hear() that prints: 0 bytes of the utterance on the parent's stdout/stderr",
     SECRET not in leak.stdout + leak.stderr and leak.returncode == 0, (leak.stdout + leak.stderr)[-300:])
red = subprocess.run([sys.executable, "-c", HEARS["chatty"] + f"hear({{'text': {SECRET!r}}})"],
                     capture_output=True, text=True, timeout=30)
want("RED control: the same hear() in-process prints the utterance", SECRET in red.stdout + red.stderr)

print("VALIDATE")
text = "ok so seed " + " ".join(f"w{i}" for i in range(60))
p, why = H.validate("seed", text, {"decision": "pass", "matched_name": "seed", "span": [0, 99]})
want("a span is moved to the name and clamped to 30 words", p == {"matched_name": "seed", "span_start": 2,
     "span_end": 32}, str(p))
want("a pass naming another agent is rejected",
     H.validate("seed", text, {"decision": "pass", "matched_name": "painter"})[1] == "not its name")
want("a name the utterance doesn't contain is rejected",
     H.validate("seed", "hello there", {"decision": "pass", "matched_name": "seed"})[1] == "name not in utterance")
want("punctuation around the name still matches", H.validate("seed", "Seed, hi", {"decision": "pass",
     "matched_name": "seed"})[0] == {"matched_name": "seed", "span_start": 0, "span_end": 2})
want("gist (S3) and junk read as no pass", H.validate("seed", text, {"decision": "gist"})[0] is None
     and H.validate("seed", text, ["pass"])[0] is None)
nob = H.Pool(tmp, 200)
nob.sandbox = False
want("without bwrap no hear() runs and nobody is attending",
     nob.hear({"id": 1, "ts": "t", "text": "seed", "view": "v"}) == [] and nob.attending() == [])

print("FENCE")
fenced = "before " + F.wrap(7, f"seed {SECRET}") + " after"
sys.path.insert(0, str(REPO / "hooks"))
import step  # noqa: E402

clean, ok = step.cleaner()
out = clean({"messages": [{"content": fenced}]})
want("the step hook's cleaner drops the fenced words", SECRET not in str(out), str(out))
want("…and keeps the pointer", (not ok) or "{{ear h7 redacted}}" in str(out), str(out))
if ok:
    from nucleus.secretset import redact, secret_set
    want("RED control: the secret redaction alone keeps the words", SECRET in str(redact(fenced, secret_set())))
want("an unterminated (truncated) fence fails closed", SECRET not in F.redact(fenced[:30]))

try:
    import psycopg
    from psycopg import sql
    from nucleus.sqlguard.fixture import FixtureUnavailable, fixture_db
    os.environ.setdefault("OBS_KEY", "test")
    from bridges import ear as EAR
    from nucleus import ear_fetch as X
    from nucleus import ear_store as S
except Exception as e:                                              # noqa: BLE001
    print(f"SKIP POINTER/FETCH: {type(e).__name__}: {e}; VERIFIED ONLY THE ARMS ABOVE")
    shutil.rmtree(tmp)
    sys.exit(1 if fails else 77)

try:
    with fixture_db() as fx, psycopg.connect(fx["dsn"], autocommit=True) as c:
        print("POINTER")
        cols = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'hearings'")]
        want("hearings has no text column", cols and not {"text", "body", "span", "words", "content"} & set(cols), str(cols))
        S.maintain(c, ttl=3)
        uts, uid = c.execute("INSERT INTO utterances (text) VALUES (%s) RETURNING ts, id",
                             (f"hey seed {SECRET} please",)).fetchone()
        for bad, label in (("true, 0, 5", "speaker_verified=true is refused"), ("false, 0, 31", "a 31-word span is refused")):
            try:
                c.execute(f"INSERT INTO hearings (agent, utterance_ts, utterance_id, matched_name, speaker_verified, "
                          f"span_start, span_end) VALUES ('seed', %s, %s, 'seed', {bad})", (uts, uid))
                refused = False
            except psycopg.errors.CheckViolation:
                refused = True
            want(label, refused)
        hr = EAR.Hearing(fx["dsn"])
        hr.cap = 2
        utt = {"id": uid, "ts": uts.isoformat(), "ts_raw": uts, "text": f"hey seed {SECRET} please", "view": "v"}
        for _ in range(3):
            hr.record(utt, "seed", {"matched_name": "seed", "span_start": 1, "span_end": 6})
        rows = c.execute("SELECT id, woke, msg_id FROM hearings WHERE agent = 'seed' ORDER BY id").fetchall()
        msgs = c.execute("SELECT from_agent, to_agent, intent, body FROM messages WHERE intent = 'hearing'").fetchall()
        want("three pointers recorded; two woke, the third is over the cap", [r[1] for r in rows] == [True, True, False]
             and rows[2][2] is None and hr.capped == 1, str(rows))
        want("each wake is from ear to seed, intent hearing", len(msgs) == 2 and all(m[:3] == ("ear", "seed", "hearing")
             for m in msgs), str(msgs))
        words = [w for w in SECRET.split()] + ["please", "hey"]
        want("no word of the utterance is in any wake body", not any(w in m[3] for m in msgs for w in words), str(msgs))
        want("RED control: the words are in the utterance row", SECRET in c.execute(
            "SELECT text FROM utterances WHERE id = %s", (uid,)).fetchone()[0])
        want("caught names the agent and a time, never the words", hr.caught and hr.caught["agent"] == "seed"
             and SECRET not in str(hr.caught), str(hr.caught))

        print("FETCH")
        hid = rows[0][0]
        code, out = X.fetch(c, hid, "seed")
        want("the owner gets exactly the fenced span", code == 0 and F.wrap(hid, f"seed {SECRET} please") in out, out)
        want("…marked unverified", "UNVERIFIED" in out)
        code2, out2 = X.fetch(c, hid, "painter")
        want("another agent gets nothing (2)", code2 == 2 and SECRET not in out2, out2)
        want("fetched_at is stamped", c.execute("SELECT fetched_at IS NOT NULL FROM hearings WHERE id = %s",
                                               (hid,)).fetchone()[0])
        part = c.execute("SELECT tableoid::regclass::text FROM utterances WHERE id = %s", (uid,)).fetchone()[0]
        c.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(part)))
        code3, out3 = X.fetch(c, hid, "seed")
        want("after the day is dropped the hearing is expired (3), the pointer outlives it", code3 == 3, out3)
except FixtureUnavailable as e:
    print(f"SKIP POINTER/FETCH: {e}; VERIFIED ONLY THE ARMS ABOVE")
    shutil.rmtree(tmp)
    sys.exit(1 if fails else 77)

shutil.rmtree(tmp)
print(f"\n{'FAIL: ' + '; '.join(fails) if fails else 'PASS'}")
sys.exit(1 if fails else 0)
