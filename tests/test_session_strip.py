#!/usr/bin/env python3
"""Oracle for plan-9139 S1d, the session side: a TIER-LABELLED session's steps and turns carry metadata only, it can't
start a child session, and its auto-memory lives under tier/ (a1 F1/F2/F5, a2 G3, v4 D2/D2a/D4, seed #45086).

  STRIP    the REAL hooks/step.py, run as a subprocess from a temp repo tree whose agents/ holds fixture charters, on a
           sqlguard fixture DB: a sentinel in every text a session produces (a Bash description and command, a Write
           path, a tool error, the prompt, assistant text, thinking, a tool_use input staging it through a heredoc, a
           tool_result) is ABSENT from every steps and turns row of a labelled member, of an identity with no charter
           and of a malformed grant. The same input through an ORG identity FINDS it (anti-vacuity), and the org rows
           are BYTE-IDENTICAL to main's hook on the same input (live on merge: step.py has no deploy)
  KEEP     a stripped turn keeps session_id (spawn.sh resumes from it), input_msg_id, source, counts, tokens, model and
           the usage block; a stripped step keeps its kind, tool name and the tool-identity meta
  SPAWN    a labelled or unreadable-label session's Agent / Task / Workflow call and any Bash naming the CLI binary
           (spawn.sh's default, ASTRYX_CLI, a path to it) are DENIED at PreToolUse, decided before any DB work (a dead
           DSN still denies); an org identity's are allowed
  ONCE     the label is read per hook process, never cached: an identity whose charter appears between two events is
           stripped on the first and not on the second
  MEMORY   spawn.sh --render: a member's settings.json carries autoMemoryDirectory under tier/memory/<agent>; an org
           agent's doesn't; CLAUDE_CODE_DISABLE_AUTO_MEMORY appears in neither; render creates no tier/ dir
Exit 0 pass · 1 fail · 77 no fixture DB.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
SUBJECT = Path(os.environ.get("STEP_SRC") or REPO / "hooks" / "step.py")
SPAWN = Path(os.environ.get("SPAWN_SRC") or REPO / "scripts" / "spawn.sh")
PY = sys.executable
SENT = "S1D-SENTINEL-session-text-4b9e"
MARK = "tier-labelled session"
fails, roots = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{str(detail)[:400]}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


CHARTERS = {"member": "# member\nGrants: owner_private:career\n", "plain": "# plain\nGrants: gmail\n",
            "bad": "# bad\nGrants: owner_private:carrer\n"}


def tree(subject: Path, dsn: str) -> Path:
    from _astryx_skel import mirror
    t = Path(tempfile.mkdtemp(prefix="t_s1d_"))
    roots.append(t)
    (t / "hooks").mkdir()
    shutil.copy(subject, t / "hooks" / "step.py")
    (t / "nucleus").mkdir()
    mirror(t)
    (t / ".env").write_text(f"ASTRYX_DSN={dsn}\n")
    (t / "agents").mkdir()
    for name, body in CHARTERS.items():
        (t / "agents" / f"{name}.md").write_text(body)
    return t


def hook(root: Path, agent: str, payload: dict, env_extra=None):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "ASTRYX_AGENT": agent, **(env_extra or {})}
    return subprocess.run([PY, str(root / "hooks" / "step.py")], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, timeout=60)


def denied(r) -> bool:
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])["hookSpecificOutput"]["permissionDecision"] == "deny"
    except Exception:  # noqa: BLE001
        return False


from datetime import datetime as _dt, timezone as _tz  # noqa: E402
TS = _dt.now(_tz.utc).isoformat().replace("+00:00", "Z")   # ONE timestamp per run: the org and main runs must match


def transcript(d: Path, msg_id=None) -> Path:
    ts = TS
    prompt = (f'<channel source="astryx" from="seed" msg_id="{msg_id}">do {SENT}</channel>' if msg_id
              else f"do {SENT}")
    ev = [{"type": "user", "timestamp": ts, "message": {"role": "user", "content": prompt}},
          {"type": "assistant", "timestamp": ts, "message": {
              "id": "m1", "role": "assistant", "model": "fixture-model",
              "content": [{"type": "thinking", "thinking": f"weighing {SENT}"},
                          {"type": "tool_use", "id": "tu1", "name": "Bash",
                           "input": {"command": f"cat > /tmp/x <<'EOF'\n{SENT}\nEOF", "description": f"stage {SENT}"}}],
              "usage": {"input_tokens": 11, "output_tokens": 7}}},
          {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [
              {"type": "tool_result", "tool_use_id": "tu1", "content": f"wrote {SENT}"}]}},
          {"type": "assistant", "timestamp": ts, "message": {
              "id": "m2", "role": "assistant", "model": "fixture-model",
              "content": [{"type": "text", "text": f"done: {SENT}"}], "usage": {"input_tokens": 3, "output_tokens": 2}}}]
    p = d / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in ev) + "\n")
    return p


EVENTS = [
    {"hook_event_name": "PreToolUse", "tool_name": "Bash",
     "tool_input": {"command": f"echo {SENT}", "description": f"say {SENT}"}},
    {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": f"/tmp/{SENT}.md",
                                                                             "content": SENT}},
    {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "x"},
     "tool_response": {"error": f"stderr {SENT}"}},
]

try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: no fixture DB ({type(e).__name__}: {e}); nothing was verified")
    sys.exit(77)

try:
    db = psycopg.connect(fx["dsn"], autocommit=True)
    root = tree(SUBJECT, fx["dsn"])

    def run_session(r, agent, sid, mid=None):
        for ev in EVENTS:
            hook(r, agent, dict(ev, session_id=sid))
        td = Path(tempfile.mkdtemp(prefix="t_s1d_tx_"))
        roots.append(td)
        mid = mid or db.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body) "
                         "VALUES ('seed','local',%s,'local','t-s1d','chat','x') RETURNING id", (agent,)).fetchone()[0]
        hook(r, agent, {"hook_event_name": "Stop", "session_id": sid, "transcript_path": str(transcript(td, mid))})
        return mid

    def rows(agent):
        st = db.execute("SELECT kind, content, meta, s::text FROM steps s WHERE agent=%s ORDER BY id", (agent,)).fetchall()
        tu = db.execute("SELECT session_id, input_msg_id, source, num_tools, tokens_in, tokens_out, model, raw_payload, "
                        "input_prompt, t::text FROM turns t WHERE agent=%s ORDER BY id", (agent,)).fetchall()
        return st, tu

    print("strip:")
    for agent, why in (("member", "a labelled member"), ("ghost", "an identity with NO charter"),
                       ("bad", "a MALFORMED grant")):
        mid = run_session(root, agent, f"sid-{agent}")
        st, tu = rows(agent)
        blob = " ".join(r[3] for r in st) + " ".join(r[9] for r in tu)
        check(f"{why}: the sentinel is ABSENT from every steps and turns row ({len(st)} steps, {len(tu)} turn)",
              st and tu and SENT not in blob, blob[blob.find(SENT) - 80:blob.find(SENT) + 20] if SENT in blob else "")
        if agent == "member":
            kinds = [(r[0], r[1]) for r in st]
            check("…each step keeps its kind and tool name, the text becomes the marker",
                  ("tool", f"Bash: [{MARK}]") in kinds and ("tool", f"Write: [{MARK}]") in kinds
                  and ("error", "Bash: failed") in kinds and any(k == "response" and MARK in c for k, c in kinds), kinds)
            t = tu[0]
            check("…the turn keeps session_id, input_msg_id, source, counts, tokens, model and the usage block",
                  t[0] == "sid-member" and t[1] == mid and t[2] == "wire" and t[3] == 1 and t[4] and t[6] == "fixture-model"
                  and isinstance(t[7], dict) and t[7].get("usage", {}).get("tokens_out") == t[5]
                  and set(t[7]) == {"withheld", "usage"} and t[8] == f"[{MARK}]", t[:9])
    print("org control:")
    mid = run_session(root, "plain", "sid-plain")
    st, tu = rows("plain")
    blob = " ".join(r[3] for r in st) + " ".join(r[9] for r in tu)
    check("an ORG identity: the same sentinel is FOUND in its steps and its turn (anti-vacuity)",
          SENT in " ".join(r[3] for r in st) and SENT in " ".join(r[9] for r in tu))
    base = os.environ.get("STEP_BASE_SRC")
    if not base:
        g = subprocess.run(["git", "-C", str(REPO), "show", "origin/main:hooks/step.py"], capture_output=True, text=True)
        if g.returncode == 0:
            bp = Path(tempfile.mkdtemp(prefix="t_s1d_base_")) / "step.py"
            roots.append(bp.parent)
            bp.write_text(g.stdout)
            base = str(bp)
    if base:
        broot = tree(Path(base), fx["dsn"])
        db.execute("UPDATE steps SET agent='plain-new' WHERE agent='plain'")
        db.execute("UPDATE turns SET agent='plain-new' WHERE agent='plain'")
        run_session(broot, "plain", "sid-plain", mid)          # the SAME message: the prompt embeds its id
        bst, btu = rows("plain")
        nst = db.execute("SELECT kind, content, meta FROM steps WHERE agent='plain-new' ORDER BY id").fetchall()
        ntu = db.execute("SELECT session_id, source, num_tools, tokens_in, tokens_out, model, raw_payload, input_prompt "
                         "FROM turns WHERE agent='plain-new' ORDER BY id").fetchall()
        check("…and its rows are BYTE-IDENTICAL to main's hook on the same input (step.py is live on merge)",
              [r[:3] for r in bst] == nst and [(t[0], t[2], t[3], t[4], t[5], t[6], t[7], t[8]) for t in btu]
              == [(t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7]) for t in ntu],
              [("steps", [r[:3] for r in bst if r[:3] not in nst], [r for r in nst if r not in [b[:3] for b in bst]]),
               ("turns", [k for k in ("raw_payload",) if btu and ntu and btu[0][7] != ntu[0][6]])])
    else:
        check("…main's hook is readable for the byte-identical control", False, "no origin/main:hooks/step.py")

    print("spawn:")
    for agent, cmd, want in (("member", None, True), ("member", "claude -p hi", True),
                             ("member", "/opt/bin/claude --resume x", True), ("member", "cd x && claude", True),
                             ("member", "ls -la", False), ("ghost", None, True), ("bad", "claude -p hi", True),
                             ("plain", None, False), ("plain", "claude -p hi", False)):
        p = ({"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {"prompt": "x"}} if cmd is None
             else {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}})
        r = hook(root, agent, p)
        what = "an Agent call" if cmd is None else f"Bash {cmd!r}"
        check(f"{agent}: {what} → {'DENIED' if want else 'allowed'}", denied(r) == want, r.stdout[-300:])
    for tool in ("Task", "Workflow"):
        r = hook(root, "member", {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {}})
        check(f"member: the {tool} tool → DENIED", denied(r), r.stdout[-200:])
    r = hook(root, "member", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                              "tool_input": {"command": "mycli -p hi"}}, {"ASTRYX_CLI": "mycli --flag"})
    check("member: ASTRYX_CLI's binary (here 'mycli') → DENIED (the names are derived, not typed)", denied(r))
    dead = tree(SUBJECT, "postgresql://nobody@127.0.0.1:1/none")
    r = hook(dead, "member", {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {}})
    check("the deny is decided before any DB work: a DEAD DSN still denies a member's Agent call", denied(r),
          r.stdout[-200:])

    print("once:")
    (root / "agents" / "late.md").unlink(missing_ok=True)
    hook(root, "late", dict(EVENTS[0], session_id="sid-late"))
    (root / "agents" / "late.md").write_text("# late\nGrants: gmail\n")
    hook(root, "late", dict(EVENTS[0], session_id="sid-late"))
    late = [r[1] for r in db.execute("SELECT kind, content FROM steps WHERE agent='late' ORDER BY id").fetchall()]
    check("the label is read PER hook process: no charter → stripped; the charter appears → the next event is not",
          len(late) == 2 and MARK in late[0] and SENT in late[1], late)
finally:
    _fx.__exit__(None, None, None)

print("memory (spawn.sh --render):")
rt = Path(tempfile.mkdtemp(prefix="t_s1d_render_"))
roots.append(rt)
from _astryx_skel import mirror  # noqa: E402
(rt / "scripts").mkdir()
shutil.copy(SPAWN, rt / "scripts" / "spawn.sh")
(rt / "nucleus").mkdir()
mirror(rt, copy=("src/astryx/core/charter.py", "src/astryx/core/runtime_env.py"), skip=("scripts/spawn.sh",))
(rt / "venv").symlink_to(Path(sys.prefix))
(rt / ".env").write_text("ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/none\n")
(rt / "local.md").write_text("# fixture law\n")
(rt / "homes").mkdir()
for name in ("member", "plain", "bad"):
    (rt / "agents" / name).mkdir(parents=True)
    (rt / "agents" / name / f"{name}.md").write_text(CHARTERS[name])
shims = rt / "shims"
shims.mkdir()
for tool in ("tmux", "psql", "claude", "pgrep"):
    (shims / tool).write_text("#!/bin/bash\n[ \"$1\" = has-session ] && exit 1\n" + ("exit 1\n" if tool == "pgrep" else "exit 0\n"))
    (shims / tool).chmod(0o755)
outs = Path(tempfile.mkdtemp(prefix="t_s1d_out_"))
roots.append(outs)
got = {}
for name in ("member", "plain", "bad"):
    r = subprocess.run(["bash", str(rt / "scripts" / "spawn.sh"), "--render", name, str(outs / name)],
                       env={"PATH": f"{shims}:/usr/bin:/bin", "HOME": str(rt), "ASTRYX_NODE": "/N/node"},
                       capture_output=True, text=True, timeout=60)
    sp = outs / name / ".claude" / "settings.json"
    got[name] = (r.returncode, sp.read_text() if sp.exists() else None, (r.stdout + r.stderr)[-300:])
m_rc, m_txt, m_log = got["member"]
p_rc, p_txt, p_log = got["plain"]
mj = json.loads(m_txt) if m_txt else {}
pj = json.loads(p_txt) if p_txt else {}
check("a member's rendered settings carry autoMemoryDirectory under tier/memory/<agent>",
      m_rc == 0 and mj.get("autoMemoryDirectory") == f"{rt}/tier/memory/member", m_log)
check("an org agent's don't", p_rc == 0 and "autoMemoryDirectory" not in pj, p_log)
b_rc, b_txt, b_log = got["bad"]
check("a MALFORMED grant's carry it too (a label that can't be read is private)",
      b_rc == 0 and b_txt and json.loads(b_txt).get("autoMemoryDirectory") == f"{rt}/tier/memory/bad", b_log)
check("CLAUDE_CODE_DISABLE_AUTO_MEMORY appears in neither (it would force memory back on)",
      m_txt and p_txt and "CLAUDE_CODE_DISABLE_AUTO_MEMORY" not in m_txt + p_txt)
check("render creates no tier/ dir (no side effect)", not (rt / "tier").exists())

for d in roots:
    shutil.rmtree(d, ignore_errors=True)
print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
