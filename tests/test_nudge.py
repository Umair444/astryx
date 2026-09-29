#!/usr/bin/env python3
"""Oracle O5: the tool nudge can never block a prompt, never leaks one, and nudges only on
RECURRENCE (goal 4227, S4).

    venv/bin/python tests/test_nudge.py          (also run by nucleus/check.sh)
    NUDGE_SRC=<path> …                           (the subject; mutation_probe sets it)

The REAL hook runs as a subprocess from a temp repo tree (it derives REPO from its own path),
with its .env written per case, so the axis under test (the endpoint) is set EXPLICITLY for
each case and never inherited. The DB side runs in a throwaway schema via PGOPTIONS
search_path, with no public fallback. The classifier is a fake loopback server whose behaviour
each case picks.

  N1 STATIC: no exit/sys.exit/os._exit/SystemExit with a non-zero code anywhere in the file
     (read from the AST, so a comment can neither pass nor fail it). Exit 2 on UserPromptSubmit
     BLOCKS the prompt.
  N2 every behavioural case exits 0.
  N3 endpoint unset, down, hung, or DRIPPING (a byte every 0.4s, which beats any per-socket
     timeout): silent, and done within the hard deadline. The drip case is the one only the
     whole-hook deadline can end.
  N4 a non-loopback endpoint (a hostname, even "localhost"; a routable IP) is refused WITHOUT
     a connection attempt and logged once; the owner flag lifts it.
  N5 a content-private agent is never classified: the endpoint gets zero hits.
  N6 recurring family → the registry nudge; complex novel → decompose; trivial/simple novel
     → nothing.
  N7 no prompt text persisted: a secret in the prompt appears in no classifications row and no
     step, and a classifier that echoes the prompt as its label writes no row.
"""
import ast
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
SUBJECT = Path(os.environ.get("NUDGE_SRC") or REPO / "hooks" / "nudge.py")
ENV = REPO / ".env"
PY = sys.executable
HARD_BOUND = 1.5 + 1.0          # the hook's deadline + interpreter start-up slack
SECRET = "SEKRET-nudge-7c1"

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


if not SUBJECT.exists():
    print(f"SKIP: {SUBJECT} absent — nothing verified.")
    sys.exit(EXIT_SKIP)

# ── N1: static, from the AST ─────────────────────────────────────────────────────────────
tree_ = ast.parse(SUBJECT.read_text())
bad = []
for node in ast.walk(tree_):
    if isinstance(node, ast.Call):
        f = node.func
        name = (f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else "")
        if name in ("exit", "_exit", "SystemExit", "quit"):
            args = node.args
            code = args[0].value if args and isinstance(args[0], ast.Constant) else (
                None if not args else "expr")
            if code not in (0, None):
                bad.append(f"line {node.lineno}: {name}({ast.unparse(args[0]) if args else ''})")
    if isinstance(node, ast.Raise) and node.exc is not None:
        e = node.exc
        if (isinstance(e, ast.Call) and getattr(e.func, "id", "") == "SystemExit") or \
                getattr(e, "id", "") == "SystemExit":
            bad.append(f"line {node.lineno}: raise SystemExit")
check("N1 no non-zero exit anywhere in the hook (exit 2 blocks the prompt)", not bad,
      "; ".join(bad))

if not ENV.exists():
    print("SKIP: .env absent — static arm only; nothing behavioural verified.")
    sys.exit(EXIT_SKIP if not fails else 1)
try:
    import psycopg
    DSN = next(l.split("=", 1)[1].strip() for l in ENV.read_text().splitlines()
               if l.startswith("ASTRYX_DSN="))
    admin = psycopg.connect(DSN, autocommit=True, connect_timeout=5)
except Exception as e:  # noqa: BLE001
    print(f"SKIP: no reachable DB ({type(e).__name__}) — static arm only.")
    sys.exit(EXIT_SKIP if not fails else 1)


# ── the fake classifier ──────────────────────────────────────────────────────────────────
class Fake:
    mode = "ok"
    reply = {"family": "build.tool", "tier": "complex", "model": "fake-1"}
    hits = 0


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        Fake.hits += 1
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if Fake.mode == "hang":
            time.sleep(6)
            return
        if Fake.mode == "drip":
            self.send_response(200)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            for _ in range(30):
                try:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                except Exception:
                    return
                time.sleep(0.4)
            return
        out = ({"family": body.get("text", ""), "tier": "complex"} if Fake.mode == "echo"
               else b"not json" if Fake.mode == "garbage" else Fake.reply)
        data = out if isinstance(out, bytes) else json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
s = socket.socket(); s.bind(("127.0.0.1", 0)); DOWN = s.getsockname()[1]; s.close()


def make_tree():
    """The hook plus FIXTURE charters, so the tier arm doesn't depend on the org's real (and
    gitignored) agents/: zzpub holds no grant, so its content is public, and zzpriv holds
    gmail, so its content is private. charter.py resolves symlinks to find agents/, so it and
    tier.py are COPIED into the tree; everything else in nucleus/ is a symlink."""
    t = Path(tempfile.mkdtemp(prefix="t_nudge_"))
    (t / "hooks").mkdir()
    shutil.copy(SUBJECT, t / "hooks" / "nudge.py")
    (t / "nucleus").mkdir()
    for e in (REPO / "nucleus").iterdir():
        if e.name in ("charter.py", "tier.py"):
            shutil.copy(e, t / "nucleus" / e.name)
        elif e.name != "__pycache__":
            (t / "nucleus" / e.name).symlink_to(e)
    for name, grants in (("zzpub", ""), ("zzpriv", "Grants: gmail\n")):
        (t / "agents" / name).mkdir(parents=True)
        (t / "agents" / name / f"{name}.md").write_text(f"# {name}\n{grants}")
    return t


def run(root, sch, url=None, prompt="refactor the ledger", agent="zzpub", extra=""):
    lines = [f"ASTRYX_DSN={DSN}"] + ([f"ASTRYX_CLASSIFIER_URL={url}"] if url else [])
    (root / ".env").write_text("\n".join(lines) + "\n" + extra)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "ASTRYX_AGENT": agent,
           "PGOPTIONS": f"-c search_path={sch}"}
    t0 = time.monotonic()
    r = subprocess.run([PY, str(root / "hooks" / "nudge.py")],
                       input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                         "session_id": "s1", "prompt": prompt}),
                       text=True, capture_output=True, env=env, timeout=20)
    return r, time.monotonic() - t0


def ddl(name):
    text = (REPO / "nucleus" / "schema.sql").read_text()
    i = text.index(f"CREATE TABLE IF NOT EXISTS {name} (")
    return text[i:text.index("\n);", i) + 3]


SCH = f"t_nudge_{os.getpid()}"
root = make_tree()
exits = []
try:
    admin.execute(f"DROP SCHEMA IF EXISTS {SCH} CASCADE")
    admin.execute(f"CREATE SCHEMA {SCH}")
    admin.execute(f"SET search_path TO {SCH}")
    for t in ("turns", "steps", "classifications"):
        admin.execute(ddl(t))
    rows = lambda: admin.execute("SELECT agent, family, tier, classifier, session_id "  # noqa: E731
                                 "FROM classifications ORDER BY id").fetchall()
    url = f"http://127.0.0.1:{PORT}/classify"

    # ── N3 silent + bounded, whatever the endpoint does ─────────────────────────────────
    for name, u, mode in (("unset", None, "ok"), ("down (closed port)", f"http://127.0.0.1:{DOWN}/c", "ok"),
                          ("hung (accepts, never answers)", url, "hang"),
                          ("DRIP (beats any per-socket timeout)", url, "drip"),
                          ("garbage body", url, "garbage")):
        Fake.mode = mode
        r, dt = run(root, SCH, u)
        exits.append(r.returncode)
        check(f"N3 {name}: silent, within {HARD_BOUND}s",
              r.stdout == "" and dt < HARD_BOUND, f"stdout={r.stdout[:80]!r} took {dt:.2f}s")
    check("N3 none of those wrote a label", rows() == [], str(rows()))

    # ── N4 non-loopback refused without a connection, logged once ───────────────────────
    Fake.mode, Fake.hits = "ok", 0
    for u in (f"http://localhost:{PORT}/classify", "http://10.255.255.1:9/c",
              f"http://127.0.0.1.nip.io:{PORT}/c"):
        r, dt = run(root, SCH, u)
        exits.append(r.returncode)
        check(f"N4 refused, fast, silent: {u.split('//')[1][:28]}",
              r.stdout == "" and dt < 1.2, f"{r.stdout[:60]!r} {dt:.2f}s")
    check("N4 the refused endpoints got ZERO requests", Fake.hits == 0, f"hits={Fake.hits}")
    logged = admin.execute("SELECT count(*), max(content) FROM steps WHERE kind='error' "
                           "AND content LIKE 'nudge:%'").fetchone()
    check("N4 the refusal is logged once (deduped), without the URL",
          logged[0] == 1 and "localhost" not in (logged[1] or ""), str(logged))
    r, _ = run(root, SCH, f"http://localhost:{PORT}/classify",
               extra="ASTRYX_CLASSIFIER_ALLOW_REMOTE=1\n")
    check("N4 the owner flag lifts the refusal (localhost reached)", Fake.hits == 1,
          f"hits={Fake.hits}")
    admin.execute("DELETE FROM classifications")

    # ── N5 a content-private agent is never classified ───────────────────────────────────
    Fake.hits = 0
    r, _ = run(root, SCH, url, agent="zzpriv", prompt=f"career {SECRET}")
    exits.append(r.returncode)
    check("N5 content-private agent (a gmail grant): zero requests, no row, silent",
          Fake.hits == 0 and rows() == [] and r.stdout == "", f"hits={Fake.hits} rows={rows()}")

    # ── N6 recurrence gates the nudge, not difficulty ────────────────────────────────────
    Fake.reply = {"family": "build.tool", "tier": "complex", "model": "fake-1"}
    r, _ = run(root, SCH, url, prompt=f"write a new poller {SECRET}")
    exits.append(r.returncode)
    check("N6 complex + novel → the decompose nudge", "[tools] Complex task" in r.stdout,
          r.stdout[:120])
    Fake.reply = {"family": "build.tool", "tier": "simple"}
    for _ in range(2):
        r, _ = run(root, SCH, url)
    check("N6 simple + not yet recurring (2 prior) → nothing", r.stdout == "", r.stdout[:120])
    r, _ = run(root, SCH, url)
    exits.append(r.returncode)
    check("N6 3 prior of the family → the registry nudge, naming the skill",
          "[tools] Recurring work" in r.stdout and "toolreg.py find" in r.stdout
          and "skills/tool-building/SKILL.md" in r.stdout, r.stdout[:160])
    Fake.reply = {"family": "build.tool", "tier": "trivial"}
    r, _ = run(root, SCH, url)
    check("N6 recurring but trivial → nothing", r.stdout == "", r.stdout[:120])
    Fake.reply = {"family": "one.off", "tier": "simple"}
    r, _ = run(root, SCH, url)
    check("N6 a different family doesn't inherit build.tool's recurrence", r.stdout == "",
          r.stdout[:120])

    # ── N7 no prompt text persisted ──────────────────────────────────────────────────────
    blob = json.dumps([list(x) for x in rows()]) + json.dumps(
        [list(x) for x in admin.execute("SELECT content FROM steps").fetchall()])
    check("N7 the prompt's secret is in no classification row and no step", SECRET not in blob)
    Fake.hits = 0
    r, _ = run(root, SCH, url, agent="zz-no-charter")
    check("N5 an agent with NO charter is treated as private (fail-closed)",
          Fake.hits == 0 and r.stdout == "", f"hits={Fake.hits}")
    check("N7 rows hold labels only (agent, family, tier, classifier, session)",
          all(len(x) == 5 and x[1] in ("build.tool", "one.off") for x in rows()), str(rows()[:3]))
    n = len(rows())
    Fake.mode = "echo"
    r, _ = run(root, SCH, url, prompt=f"echo {SECRET}")
    exits.append(r.returncode)
    check("N7 a classifier echoing the prompt as its label → no row, silent",
          len(rows()) == n and r.stdout == "", f"rows {n}->{len(rows())}")
    Fake.mode = "ok"

    check("N2 every behavioural case exited 0", set(exits) == {0}, str(exits))
finally:
    srv.shutdown()
    try:
        admin.execute(f"DROP SCHEMA IF EXISTS {SCH} CASCADE")
    finally:
        shutil.rmtree(root, ignore_errors=True)

if fails:
    print(f"\nFAIL: {len(fails)} nudge invariant(s) broken")
    sys.exit(1)
print("\nPASS: the nudge never blocks, never leaks a prompt, and nudges only on recurrence")
