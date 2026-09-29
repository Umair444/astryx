#!/usr/bin/env python3
"""Oracle: the tool ledger (goal 4227, S0) — the REAL step hook, run as a subprocess against a
throwaway schema, stamps each call with the registry id and nothing else.

    venv/bin/python tests/test_tool_ledger.py        (also run by nucleus/check.sh)
    STEP_SRC=<path> / TOOLREG_SRC=<path> …           (the two subjects; mutation_probe sets one)

WHAT IT HOLDS
  L1 a call of a registered tool carries {registry_id} on its `tool` row and
     {registry_id, result_bytes} on its tool_done row — those keys EXACTLY, so a later field
     (a command, an argument, a result excerpt) turns this red instead of riding along.
  L2 I5, privacy: a secret planted in the command, the arguments AND the tool result never
     appears in any meta, byte for byte.
  L3 a Write/Edit of a tool's source is authorship evidence ({edits}), never a call; its
     tool_done row carries no meta, so a call count can't include it.
  L4 anything unregistered (Read, an unknown MCP server, a tier/ path, a `..` escape) carries
     no meta, and the door's untrusted id is validated.
  L5 a toolreg failure still writes the step row, just without meta. Telemetry never costs
     the row it rides on.
  L6 Stop claims the nudge's classification row for the turn, and Stop against a DB WITHOUT
     the classifications table still writes the turn (the savepoint arm).
  L7 authorship from the ledger: first Write = author, later writers = contributors, an
     Edit-first path = 'unknown', no record = 'unknown'. Both the legacy content form and the
     meta form count.
  L8 the classifications table refuses a prompt-shaped label (I5 against an untrusted
     classifier that echoes its input).
  L10 a heredoc BODY is data, not commands: a body line naming a script is not a call, and
     an apostrophe in a body doesn't drop the real call in front of it (abstractor-4's review).
     `bash -n` is a syntax check, not a run.
  L11 the PUBLIC WALL never carries a raw command: a description-less Bash call's content is
     its registry id or its program name, never its arguments or a VAR=value prefix, and an
     error row doesn't carry the error text. A secret planted across the WHOLE run must appear
     in no steps.content (steps feed memory's nightly RAG compile).
  L6b Stop never claims a classification from a DIFFERENT session.
  L9 a script that is only NAMED (git add x.py, grep … x.py, cat x.py) is not a call. Only
     an execution position counts. The ledger's first live minutes counted every mention,
     which inflated usage with every review and commit.

BOTH SUBJECTS RUN FROM ONE TEMP REPO TREE: hooks/step.py and nucleus/toolreg.py are copies of
the subjects, and everything else is symlinked in. Both files derive REPO from their own path,
so every absolute path this oracle builds is under that tree, never the real REPO.

WHY A SUBPROCESS, AND WHY PGOPTIONS. The hook opens its own connection from .env, so the only
way to test the REAL file, rather than an import of pieces of it, is to run it. libpq honours
PGOPTIONS, so `-c search_path=<temp schema>` sends every unqualified statement the hook makes
into the throwaway schema. There's no public fallback, so a prod table can't be written.

Exits 77 when there's no .env/DSN/psycopg: that means nothing was verified, not that it passed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
SUBJECT = Path(os.environ.get("STEP_SRC") or REPO / "hooks" / "step.py")
TOOLREG = Path(os.environ.get("TOOLREG_SRC") or REPO / "nucleus" / "toolreg.py")
ENV = REPO / ".env"
PY = sys.executable

if not ENV.exists() or not SUBJECT.exists() or not TOOLREG.exists():
    print("SKIP: .env or the step hook is absent (bare clone) — nothing verified.")
    sys.exit(EXIT_SKIP)
try:
    import psycopg
    DSN = next(l.split("=", 1)[1].strip() for l in ENV.read_text().splitlines()
               if l.startswith("ASTRYX_DSN="))
    admin = psycopg.connect(DSN, autocommit=True, connect_timeout=5)
except Exception as e:  # noqa: BLE001
    print(f"SKIP: no reachable DB ({type(e).__name__}) — nothing verified.")
    sys.exit(EXIT_SKIP)

fails = []
SECRET = "SEKRET-4227-xq9"          # planted everywhere a leak could come from


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def ddl(name):
    text = (REPO / "nucleus" / "schema.sql").read_text()
    # The table's own closing ");" starts a line. A bare ");" search would also stop inside a
    # column comment, and turns has one.
    i = text.index(f"CREATE TABLE IF NOT EXISTS {name} (")
    return text[i:text.index("\n);", i) + 3]


def tree(broken_toolreg=False):
    """A temp repo root: the two subjects copied in, everything else symlinked."""
    t = Path(tempfile.mkdtemp(prefix="t_ledger_"))
    (t / "hooks").mkdir()
    shutil.copy(SUBJECT, t / "hooks" / "step.py")
    (t / ".env").write_text(f"ASTRYX_DSN={DSN}\n")
    (t / "nucleus").mkdir()
    for e in (REPO / "nucleus").iterdir():
        if e.name not in ("toolreg.py", "__pycache__"):
            (t / "nucleus" / e.name).symlink_to(e)
    if broken_toolreg:
        (t / "nucleus" / "toolreg.py").write_text("raise RuntimeError('toolreg broken')\n")
    else:
        shutil.copy(TOOLREG, t / "nucleus" / "toolreg.py")
    for d in ("mcp", "skills", "tests"):
        (t / d).symlink_to(REPO / d)
    return t


def hook(root, sch, payload, agent="alice"):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "ASTRYX_AGENT": agent,
           "PGOPTIONS": f"-c search_path={sch}"}
    r = subprocess.run([PY, str(root / "hooks" / "step.py")], input=json.dumps(payload),
                       text=True, capture_output=True, env=env, timeout=30)
    return r


def schema(conn, sch, tables):
    conn.execute(f"DROP SCHEMA IF EXISTS {sch} CASCADE")
    conn.execute(f"CREATE SCHEMA {sch}")
    conn.execute(f"SET search_path TO {sch}")
    for t in tables:
        conn.execute(ddl(t))
    # A recent usage snapshot keeps the Stop hook's throttled usage poll from reaching out to
    # the network during the test.
    conn.execute("INSERT INTO turns (agent, source, input_prompt, ended_at, usage_snapshot) "
                 "VALUES ('fixture','user','x', now(), '{}'::jsonb)")


def metas(conn):
    return conn.execute("SELECT id, kind, content, meta FROM steps ORDER BY id").fetchall()


SCH = f"t_ledger_{os.getpid()}"
SCH2 = f"t_ledger_nocls_{os.getpid()}"
roots = []
try:
    schema(admin, SCH, ("turns", "steps", "messages", "classifications"))
    root = tree(); roots.append(root)
    sys.path.insert(0, str(root))
    from nucleus import toolreg  # noqa: E402  — the SUBJECT's copy, from the temp tree

    def pre(tool, ti, agent="alice"):
        return hook(root, SCH, {"hook_event_name": "PreToolUse", "tool_name": tool,
                                "tool_input": ti}, agent)

    def post(tool, ti, resp, agent="alice"):
        return hook(root, SCH, {"hook_event_name": "PostToolUse", "tool_name": tool,
                                "tool_input": ti, "tool_response": resp}, agent)

    def last(n=1):
        return metas(admin)[-n:]

    # ── L1 + L2: a Bash call of a registered script, secrets in every input ────────────────
    cmd = f"cd {root} && ASTRYX_TOKEN={SECRET} bash nucleus/smoke.sh --key '{SECRET}' | nucleus/wall.sh"
    bi = {"command": cmd, "description": "run smoke"}
    resp = {"stdout": f"ok {SECRET} " + "x" * 500, "stderr": "", "interrupted": False}
    pre("Bash", bi)
    post("Bash", bi, resp)
    (_, k1, _, m1), (_, k2, _, m2) = last(2)
    check("L1 tool row meta == {registry_id, also} for a two-script pipeline",
          k1 == "tool" and m1 == {"registry_id": "script:nucleus/smoke.sh", "v": toolreg.LEDGER_V,
                                  "also": ["script:nucleus/wall.sh"]}, f"{k1} {m1}")
    want_bytes = len(json.dumps(resp, default=str).encode())
    check("L1 tool_done meta == {registry_id, result_bytes} exactly, bytes measured",
          k2 == "tool_done" and m2 == {"registry_id": "script:nucleus/smoke.sh", "v": toolreg.LEDGER_V,
                                       "result_bytes": want_bytes}, f"{k2} {m2} want {want_bytes}")
    check("L1 every ledger row carries the call-semantics version (v)",
          all(m.get("v") == toolreg.LEDGER_V for *_, m in metas(admin) if m), "")
    all_meta = json.dumps([m for *_, m in metas(admin)])
    check("L2 no secret from command/args/result in ANY meta (I5)", SECRET not in all_meta,
          all_meta[:300])

    # ── MCP calls ──────────────────────────────────────────────────────────────────────────
    pre("mcp__org__economy", {"agent": SECRET})
    check("L1 registered MCP tool → mcp:<server>/<tool>, args dropped",
          last()[0][3] == {"registry_id": "mcp:org/economy", "v": toolreg.LEDGER_V}, str(last()[0][3]))
    pre("mcp__astryx__send", {"to": "bob", "body": SECRET})
    check("L1 core wire tool is registered (mcp:astryx/send)",
          last()[0][3] == {"registry_id": "mcp:astryx/send", "v": toolreg.LEDGER_V}, str(last()[0][3]))

    # ── L3: writing a tool's source is authorship, not a call ─────────────────────────────
    wi = {"file_path": f"{root}/skills/zz_ledger_probe/tool.py", "content": SECRET}
    pre("Write", wi)
    check("L3 Write of a tool source → {edits} only (content dropped)",
          last()[0][3] == {"edits": "script:skills/zz_ledger_probe/tool.py", "v": toolreg.LEDGER_V},
          str(last()[0][3]))
    post("Write", wi, {"type": "create", "filePath": wi["file_path"]})
    check("L3 Write's tool_done carries NO meta (never counted as a call)",
          last()[0][3] is None, str(last()[0][3]))

    # ── L4: unregistered → no meta; the door's id is validated ────────────────────────────
    for tool, ti, why in (
            ("Read", {"file_path": f"{root}/nucleus/econ.py"}, "Read of a tool is not a call"),
            ("mcp__not_a_server__x", {}, "unregistered MCP server"),
            ("Bash", {"command": "cat tier/secret.py"}, "tier/ is never a tool root"),
            ("Bash", {"command": "python3 nucleus/../tests/test_tool_ledger.py"},
             "a .. escape out of a root (to a file that EXISTS)"),
            ("Bash", {"command": "ls -la"}, "a plain command")):
        pre(tool, ti)
        check(f"L4 no meta: {why}", last()[0][3] is None, str(last()[0][3]))
    pre("mcp__tools__run", {"id": "script:nucleus/smoke.sh", "args": [SECRET]})
    check("L4 the door records the UNDERLYING id",
          last()[0][3] == {"registry_id": "script:nucleus/smoke.sh", "v": toolreg.LEDGER_V},
          str(last()[0][3]))
    pre("mcp__tools__run", {"id": "script:tier/x.py"})
    check("L4 an invalid door id is not trusted (recorded as the door itself)",
          last()[0][3] == {"registry_id": "mcp:tools/run", "v": toolreg.LEDGER_V}, str(last()[0][3]))

    # ── L9: a named script is not a called script ──────────────────────────────────────────
    for c in ("git add hooks/step.py nucleus/check.sh nucleus/smoke.sh",
              "grep -n x nucleus/econ.py; sed -n 1,5p nucleus/pulse.py | head -3",
              "cat nucleus/smoke.sh && git diff nucleus/wall.sh",
              "python3 -c 'print(1)' nucleus/econ.py"):
        pre("Bash", {"command": c})
        check(f"L9 mention is not a call: {c[:48]!r}", last()[0][3] is None, str(last()[0][3]))
    for c, want in (("timeout 60 venv/bin/python -u -m nucleus.econ", "script:nucleus/econ.py"),
                    ("FOO=1 nucleus/smoke.sh", "script:nucleus/smoke.sh"),
                    (f"{root}/nucleus/check.sh --fast", "script:nucleus/check.sh")):
        pre("Bash", {"command": c})
        check(f"L9 execution position IS a call: {c[:48]!r}",
              (last()[0][3] or {}).get("registry_id") == want, str(last()[0][3]))

    # ── L10: heredoc bodies are data ───────────────────────────────────────────────────────
    for c, want, why in (
            ("cat > /tmp/n.md <<'EOF'\nnucleus/check.sh is the gate runner\nEOF", None,
             "a heredoc body naming a script is not a call"),
            ("venv/bin/python - <<'EOF'\nnucleus/econ.py\nEOF", None,
             "stdin-fed python whose body names a script"),
            ("venv/bin/python nucleus/econ.py <<'EOF'\nit's here\nEOF", "script:nucleus/econ.py",
             "an apostrophe in the body doesn't drop the REAL call"),
            ("bash -n nucleus/smoke.sh", None, "bash -n is a syntax check")):
        pre("Bash", {"command": c})
        got = (last()[0][3] or {}).get("registry_id")
        check(f"L10 {why}", got == want, f"got {got} want {want}")

    # ── L11: the wall never carries a raw command ─────────────────────────────────────────
    for c, want in ((f"psql postgres://u:{SECRET}@h/db -c 'select 1'", "Bash: psql"),
                    (f"PGPASSWORD={SECRET} psql -h h", "Bash: psql"),
                    (f"PGPASSWORD={SECRET} nucleus/smoke.sh --dsn postgres://u:{SECRET}@h",
                     "Bash: script:nucleus/smoke.sh"),
                    (f"'{SECRET}'", "Bash: (command)"),
                    (f"echo 'unbalanced {SECRET}", "Bash: (command)")):
        pre("Bash", {"command": c})
        check(f"L11 wall label for {want!r}", last()[0][2] == want, repr(last()[0][2]))
    post("Bash", {"command": f"psql -c x"}, {"error": f"FATAL: password {SECRET} rejected"})
    check("L11 an error row carries no error text", last()[0][2] == "Bash: failed",
          repr(last()[0][2]))

    # ── L5: a broken toolreg never costs the row ──────────────────────────────────────────
    broken = tree(broken_toolreg=True); roots.append(broken)
    n0 = len(metas(admin))
    hook(broken, SCH, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": bi})
    rows = metas(admin)
    check("L5 toolreg raising → the step row is STILL written, without meta",
          len(rows) == n0 + 1 and rows[-1][1] == "tool" and rows[-1][3] is None,
          f"rows {n0}->{len(rows)} last={rows[-1] if rows else None}")
    hook(broken, SCH, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": f"psql postgres://u:{SECRET}@h"}})
    check("L5 toolreg raising + no description → '(command)', never the command",
          metas(admin)[-1][2] == "Bash: (command)", repr(metas(admin)[-1][2]))

    wall = " ".join(c for _, _, c, _ in metas(admin))
    check("L11 the planted secret appears in NO steps.content across the whole run",
          SECRET not in wall, wall[wall.find(SECRET) - 60:wall.find(SECRET) + 20]
          if SECRET in wall else "")

    # ── L6: Stop claims the classification; a DB without the table still gets its turn ───
    def transcript(d):
        p = Path(d) / "t.jsonl"
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        p.write_text("\n".join(json.dumps(e) for e in (
            {"type": "user", "timestamp": ts, "message": {"role": "user", "content": "do x"}},
            {"type": "assistant", "timestamp": ts, "message": {
                "id": "m1", "role": "assistant", "model": "m",
                "content": [{"type": "text", "text": "done"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}})) + "\n")
        return p

    admin.execute("INSERT INTO classifications (agent, family, tier, classifier, session_id) "
                  "VALUES ('alice','build.tool','complex','test','s')")
    admin.execute("INSERT INTO classifications (agent, family, tier, classifier, session_id) "
                  "VALUES ('alice','other.session','simple','test','ANOTHER')")
    tdir = tempfile.mkdtemp(prefix="t_ledger_tx_"); roots.append(Path(tdir))
    hook(root, SCH, {"hook_event_name": "Stop", "session_id": "s",
                     "transcript_path": str(transcript(tdir))})
    t_new = admin.execute("SELECT max(id) FROM turns WHERE agent='alice'").fetchone()[0]
    claimed = admin.execute("SELECT turn_id FROM classifications WHERE agent='alice' "
                            "AND session_id='s'").fetchone()[0]
    check("L6 Stop claims the nudge's classification for the turn",
          t_new is not None and claimed == t_new, f"turn={t_new} claimed={claimed}")
    other = admin.execute("SELECT turn_id FROM classifications "
                          "WHERE session_id='ANOTHER'").fetchone()[0]
    check("L6b a classification from ANOTHER session is not claimed", other is None,
          f"claimed by turn {other}")

    schema(admin, SCH2, ("turns", "steps", "messages"))       # NO classifications table
    hook(root, SCH2, {"hook_event_name": "Stop", "session_id": "s",
                      "transcript_path": str(transcript(tdir))})
    admin.execute(f"SET search_path TO {SCH2}")
    got = admin.execute("SELECT count(*) FROM turns WHERE agent='alice'").fetchone()[0]
    check("L6 Stop without the classifications table still writes the turn (savepoint)",
          got == 1, f"turns written: {got}")
    admin.execute(f"SET search_path TO {SCH}")

    # ── L7: authorship from the ledger ────────────────────────────────────────────────────
    admin.execute("DELETE FROM steps")
    rows = [
        ("alice", f"Write: {root}/nucleus/zz_probe_a.py", None),          # legacy form
        ("bob", f"Edit: {root}/nucleus/zz_probe_a.py", None),
        ("alice", f"Edit: {root}/nucleus/zz_probe_a.py", None),
        ("carol", "Write: (described)", {"edits": "script:skills/zz_probe_b/t.py"}),  # meta form
        ("erin", "Edit: (described)", {"edits": "script:skills/zz_probe_b/t.py"}),
        ("dave", f"Edit: {root}/nucleus/zz_probe_c.py", None),           # predates the record
        ("frank", f"Write: {root}/nucleus/zz_probe_c.py", None),
    ]
    for agent, content, meta in rows:
        admin.execute("INSERT INTO steps (agent, kind, content, meta) VALUES (%s,'tool',%s,%s)",
                      (agent, content, json.dumps(meta) if meta else None))
    ids = ["script:nucleus/zz_probe_a.py", "script:skills/zz_probe_b/t.py",
           "script:nucleus/zz_probe_c.py", "script:nucleus/zz_probe_none.py"]
    au = toolreg.authorship(admin.cursor(), ids)
    check("L7 first Write = author; later other writers = contributors; self excluded",
          au[ids[0]] == {"author": "alice", "contributors": ["bob"], "provenance": "ledger"},
          str(au[ids[0]]))
    check("L7 meta-form edits count the same as legacy content",
          au[ids[1]] == {"author": "carol", "contributors": ["erin"], "provenance": "ledger"},
          str(au[ids[1]]))
    check("L7 Edit-first path → author 'unknown' (a later Write is not authorship)",
          au[ids[2]]["author"] == "unknown" and au[ids[2]]["provenance"] == "unknown",
          str(au[ids[2]]))
    check("L7 no record → 'unknown', never guessed",
          au[ids[3]] == {"author": "unknown", "contributors": [], "provenance": "unknown"},
          str(au[ids[3]]))

    # ── L8: the classifications table refuses a prompt-shaped label ───────────────────────
    for fam, tier, why in (("please fix the failing build in nucleus", "complex", "prompt as family"),
                           ("build.tool", "urgent: " + SECRET, "free text as tier"),
                           ("X" * 49, "simple", "over-long family")):
        try:
            with admin.transaction():
                admin.execute("INSERT INTO classifications (agent, family, tier) "
                              "VALUES ('alice',%s,%s)", (fam, tier))
            ok = False
        except psycopg.errors.CheckViolation:
            ok = True
        check(f"L8 CHECK refuses {why}", ok)
finally:
    try:
        admin.execute(f"DROP SCHEMA IF EXISTS {SCH} CASCADE")
        admin.execute(f"DROP SCHEMA IF EXISTS {SCH2} CASCADE")
    finally:
        for r in roots:
            shutil.rmtree(r, ignore_errors=True)

if fails:
    print(f"\nFAIL: {len(fails)} tool-ledger invariant(s) broken")
    sys.exit(1)
print("\nPASS: the tool ledger stamps ids and nothing else; authorship is ledger-derived")
