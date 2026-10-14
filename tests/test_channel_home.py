"""channel/server.mjs serves an org that lives ELSEWHERE: ASTRYX_HOME (and ASTRYX_DSN) instead of `..`.

The Claude Code plugin installs channel/ into Claude Code's plugin cache, far from the org's checkout, so the server
and its sibling modules must find .env, venv/bin/python, nucleus/ and triggers/ under ASTRYX_HOME. The existing
channel oracles (ear survival, wake recovery, the step doorbell, tombstones) run the default `..` layout and prove it
unchanged; this file proves the other one, and it DISCRIMINATES: the staged channel dir has no .env beside it and no
ASTRYX_DSN in its env, so a server still reading `../.env` cannot start, and a `send` that still resolved
../venv/bin/python could not reach the stub address checker that only exists under the home.

Also here, because they are the plugin's mode of the same server:
  * dormant: ASTRYX_JOIN_DIR set and no join marker for the project -> no tools and NO database connection
    (its DSN points at a port nothing listens on, and it still answers);
  * joined: a marker written by the plugin's own join script (hooks/astryx_hook.py) is read by join.mjs, so the
    two agree on the project key;
  * one body: with ASTRYX_ONE_BODY=1 a second server for the same agent refuses to start, loudly; another agent
    and the repo's mode (no ASTRYX_ONE_BODY) are unaffected.

Needs node, channel/node_modules and a fixture database, else 77. Run: venv/bin/python tests/test_channel_home.py
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from _stage_channel import stage_server  # noqa: E402

SERVER = Path(os.environ.get("CHANNEL_SERVER_SRC", REPO / "channel" / "server.mjs"))
HOOK = REPO / "plugin" / "hooks" / "astryx_hook.py"
fails = 0


def arm(name: str, ok: bool, detail: str = "") -> None:
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    fails += not ok


def skip(why: str) -> None:
    print(f"SKIP: {why}. Nothing was verified here.")
    sys.exit(77)


def node_bin() -> str | None:
    spawn = REPO / "scripts" / "spawn.sh"
    m = re.search(r"^NODE=(\S+)", spawn.read_text(), re.M) if spawn.exists() else None
    if m and Path(m.group(1)).is_file():
        return m.group(1)
    return shutil.which("node")


NODE = node_bin()
if not NODE:
    skip("no node binary")
if not (REPO / "channel" / "node_modules" / "pg").is_dir():
    skip("channel/node_modules is absent (run npm ci in channel/)")
try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db, FixtureUnavailable, url
except ModuleNotFoundError:
    skip("psycopg not importable (run with venv/bin/python)")


class Mcp:
    """A channel server on stdio: newline-delimited JSON-RPC."""

    def __init__(self, server: Path, env: dict, cwd: Path, log: Path):
        self.err = open(log, "wb")
        self.p = subprocess.Popen([NODE, str(server)], cwd=cwd, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=self.err)
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.n = 0

    def _read(self):
        for line in self.p.stdout:
            try:
                self.q.put(json.loads(line))
            except ValueError:
                pass

    def call(self, method: str, params: dict | None = None, timeout: float = 20) -> dict | None:
        self.n += 1
        mid = self.n
        try:
            self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
                                + "\n").encode())
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):          # the server died: no answer, and the arm reads RED
            return None
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                m = self.q.get(timeout=max(0.05, end - time.monotonic()))
            except queue.Empty:
                break
            if m.get("id") == mid:
                return m
        return None

    def init(self) -> dict | None:
        r = self.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "probe", "version": "0"}})
        if r:
            try:
                self.p.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                self.p.stdin.flush()
            except (BrokenPipeError, OSError):
                return None
        return r

    def close(self):
        if self.p.poll() is None:
            self.p.kill()
            self.p.wait(timeout=10)
        try:
            self.p.stdin.close()
        except OSError:
            pass
        self.err.close()


def wait_exit(p: subprocess.Popen, timeout: float) -> int | None:
    try:
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def base_env(**kw) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("ASTRYX_DSN", "ASTRYX_HOME", "ASTRYX_JOIN_DIR", "ASTRYX_ONE_BODY", "CLAUDE_PROJECT_DIR",
                        "CLAUDE_PLUGIN_DATA")}
    env.update(kw)
    return env


tmp = Path(tempfile.mkdtemp(prefix="channel-home-"))
servers: list[Mcp] = []
try:
    try:
        fxcm = fixture_db()
        fx = fxcm.__enter__()
    except FixtureUnavailable as e:
        skip(f"no fixture database ({e})")
    try:
        # ── the layout: the server staged ALONE (no .env beside it); the org's home somewhere else ──
        stage = tmp / "pluginroot"
        server = stage_server(stage / "channel", SERVER)
        home = tmp / "org home"                                    # a space: paths must stay one argument
        (home / "venv" / "bin").mkdir(parents=True)
        (home / "nucleus").mkdir()
        for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
            (home / _d).mkdir(parents=True, exist_ok=True)
        NODE_DSN = url(fx["dsn"])                         # node-pg takes a URL, not key=value conninfo
        (home / ".env").write_text(f"ASTRYX_DSN={NODE_DSN}\n")
        probe = tmp / "address-called"
        py = home / "venv" / "bin" / "python"
        py.write_text(f"#!/bin/sh\necho \"$@\" > '{probe}'\nexit 0\n")    # the stub python: proves WHICH python ran
        py.chmod(0o755)
        (home / "nucleus" / "address.py").write_text("# stub: the stub python above records that it was asked\n")
        arm("layout: the staged channel dir has no .env beside it", not (stage / ".env").exists())

        # ── 1. ASTRYX_HOME: DSN from <home>/.env, python and nucleus/ from <home> ──
        env = base_env(ASTRYX_AGENT="homeprobe", ASTRYX_HOME=str(home))
        s = Mcp(server, env, tmp, tmp / "home.err")
        servers.append(s)
        r = s.init()
        arm("ASTRYX_HOME: the server starts and answers initialize with no ../.env and no ASTRYX_DSN", bool(r),
            (tmp / "home.err").read_text(errors="replace")[-300:])
        instr = ((r or {}).get("result") or {}).get("instructions", "")
        arm('repo mode: the instructions name <channel source="astryx" …> (what spawn.sh residents receive)',
            'Org messages arrive as <channel source="astryx" from=' in instr, instr[:200])
        r = s.call("tools/call", {"name": "send", "arguments": {"to": "someone", "body": "hello from elsewhere"}})
        text = json.dumps(r or {})
        arm("ASTRYX_HOME: send consulted <home>/venv/bin/python <home>/nucleus/address.py (channel/ reaches it through the stub, by design)",
            probe.exists() and str(home / "nucleus" / "address.py") in probe.read_text(), text[-300:])
        with psycopg.connect(fx["dsn"], autocommit=True) as db:
            row = db.execute("SELECT from_agent, to_agent, body FROM messages WHERE from_agent='homeprobe' "
                             "ORDER BY id DESC LIMIT 1").fetchone()
        arm("ASTRYX_HOME: the row landed in the database <home>/.env names",
            row == ("homeprobe", "someone", "hello from elsewhere"), repr(row))

        # ── 2. ASTRYX_DSN wins over <home>/.env; an empty one is "unset" (the plugin's blank option) ──
        bad_home = tmp / "bad home"
        shutil.copytree(home, bad_home)
        (bad_home / ".env").write_text("ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/nowhere\n")
        s2 = Mcp(server, base_env(ASTRYX_AGENT="dsnprobe", ASTRYX_HOME=str(bad_home), ASTRYX_DSN=NODE_DSN),
                 tmp, tmp / "dsn.err")
        servers.append(s2)
        s2.init()
        r = s2.call("tools/call", {"name": "query_steps", "arguments": {"agent": "dsnprobe"}})
        arm("ASTRYX_DSN in the env wins over <home>/.env",
            r is not None and not (r.get("result") or {}).get("isError"), json.dumps(r)[-300:])
        s3 = Mcp(server, base_env(ASTRYX_AGENT="emptyprobe", ASTRYX_HOME=str(home), ASTRYX_DSN=""),
                 tmp, tmp / "empty.err")
        servers.append(s3)
        s3.init()
        r = s3.call("tools/call", {"name": "query_steps", "arguments": {"agent": "emptyprobe"}})
        arm("an empty ASTRYX_DSN counts as unset: <home>/.env is used",
            r is not None and not (r.get("result") or {}).get("isError"), json.dumps(r)[-300:])
        r = subprocess.run([NODE, "--input-type=module", "-e",
                            f"import {{ HOME }} from {json.dumps((REPO / 'channel' / 'home.mjs').as_uri())};"
                            "console.log(HOME)"], capture_output=True, text=True, env=base_env(), timeout=30)
        arm("no ASTRYX_HOME: the home is the checkout above channel/ (the residents' layout, unchanged)",
            r.stdout.strip() == str(REPO), r.stdout + r.stderr)

        # ── 3. dormant: the plugin's mode, no join marker -> no tools, no database ──
        data = tmp / "plugin data"
        project = tmp / "some project"
        project.mkdir()
        dormant_env = base_env(ASTRYX_AGENT="dormantprobe", ASTRYX_HOME=str(bad_home),
                               ASTRYX_JOIN_DIR=str(data / "projects"), CLAUDE_PROJECT_DIR=str(project))
        s4 = Mcp(server, dormant_env, project, tmp / "dormant.err")
        servers.append(s4)
        r = s4.init()
        tools = s4.call("tools/list")
        arm("dormant: unjoined project -> the server answers with NO tools (and its DSN is unreachable)",
            bool(r) and tools is not None and tools.get("result", {}).get("tools") == [], json.dumps(tools))
        arm("dormant: its instructions say how to join",
            "/astryx:join" in json.dumps(r or {}), json.dumps(r)[-200:])
        time.sleep(0.5)
        arm("dormant: and it stays up (no exit, no DB error)", s4.p.poll() is None,
            (tmp / "dormant.err").read_text(errors="replace")[-300:])

        # ── 4. joined: the plugin's join script writes the marker the server reads ──
        r = subprocess.run([sys.executable, str(HOOK), "join", "joinprobe", "--data", str(data),
                            "--home", str(home), "--project", str(project)],
                           capture_output=True, text=True, env=base_env(), timeout=30)
        arm("join: the plugin's join script marks the project", r.returncode == 0, r.stdout + r.stderr)
        joined_env = {**dormant_env, "ASTRYX_HOME": str(home), "ASTRYX_AGENT": "ignored-default"}
        s5 = Mcp(server, joined_env, project, tmp / "joined.err")
        servers.append(s5)
        instr = (((s5.init() or {}).get("result") or {}).get("instructions", ""))
        arm('joined mode: the instructions name the plugin\'s channel tag, source="plugin:astryx:astryx"',
            'arrive as <channel source="plugin:astryx:astryx" from=' in instr, instr[:200])
        tools = s5.call("tools/list")
        names = [t["name"] for t in (tools or {}).get("result", {}).get("tools", [])]
        arm("joined: the server reads the hook's marker (same project key) and serves the wire tools",
            "send" in names, json.dumps(tools)[-300:])
        s5.call("tools/call", {"name": "send", "arguments": {"to": "someone", "body": "as joined"}})
        with psycopg.connect(fx["dsn"], autocommit=True) as db:
            who = db.execute("SELECT from_agent FROM messages WHERE body='as joined'").fetchone()
        arm("joined: it speaks as the marker's agent, not the default option", who == ("joinprobe",), repr(who))
        s5.close()

        # ── 5. one body per agent ──
        one = base_env(ASTRYX_AGENT="bodyprobe", ASTRYX_HOME=str(home), ASTRYX_ONE_BODY="1")
        first = Mcp(server, one, tmp, tmp / "body1.err")
        servers.append(first)
        arm("one body: the first server for an agent starts", bool(first.init()),
            (tmp / "body1.err").read_text(errors="replace")[-300:])
        second = Mcp(server, one, tmp, tmp / "body2.err")
        servers.append(second)
        rc = wait_exit(second.p, 20)
        err = (tmp / "body2.err").read_text(errors="replace")
        arm("one body: a SECOND server for the same agent exits 1, loudly",
            rc == 1 and "ANOTHER BODY" in err, f"rc={rc} {err[-300:]}")
        other = Mcp(server, {**one, "ASTRYX_AGENT": "bodyprobe2"}, tmp, tmp / "body3.err")
        servers.append(other)
        arm("one body: another agent's server is unaffected", bool(other.init()) and other.p.poll() is None)
        legacy = Mcp(server, base_env(ASTRYX_AGENT="bodyprobe", ASTRYX_HOME=str(home)), tmp, tmp / "body4.err")
        servers.append(legacy)
        arm("one body: without ASTRYX_ONE_BODY (the repo's residents) a second server still starts",
            bool(legacy.init()) and legacy.p.poll() is None)
        first.close()
        third = Mcp(server, one, tmp, tmp / "body5.err")
        servers.append(third)
        ok = False
        end = time.monotonic() + 20
        while time.monotonic() < end and not ok:              # the lock frees when the first body's backend ends
            ok = bool(third.init()) and third.p.poll() is None
            if not ok and third.p.poll() is not None:
                third = Mcp(server, one, tmp, tmp / "body5.err")
                servers.append(third)
                time.sleep(0.5)
        arm("one body: once the first body is gone, a new one starts", ok,
            (tmp / "body5.err").read_text(errors="replace")[-300:])

        # ── 6. the lock survives its connection dying: A takes it again, so B is still refused ──
        # A postgres restart or an idle-killer ends the lock's backend; the session lock goes with it. Kill exactly
        # A's lock backend (its application_name), then start B. Whichever wins, never two live bodies: A retakes
        # and B is refused, or B won the race and A exits loudly on its retake.
        rearm = base_env(ASTRYX_AGENT="rearmprobe", ASTRYX_HOME=str(home), ASTRYX_ONE_BODY="1")
        a = Mcp(server, rearm, tmp, tmp / "rearmA.err")
        servers.append(a)
        a.init()
        lock_sql = ("SELECT a.pid FROM pg_stat_activity a JOIN pg_locks l ON l.pid = a.pid "
                    "WHERE a.application_name = 'astryx-body:rearmprobe' AND l.locktype = 'advisory' AND l.granted")
        with psycopg.connect(fx["dsn"], autocommit=True) as db:
            held = [p for (p,) in db.execute(lock_sql).fetchall()]
            arm("re-arm: body A holds the lock on a backend named astryx-body:<agent>", len(held) == 1, repr(held))
            killed = db.execute("SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                                "WHERE application_name = 'astryx-body:rearmprobe'").fetchone()[0]
            retaken = []
            end = time.monotonic() + 20
            while time.monotonic() < end and not retaken:
                time.sleep(0.3)
                retaken = [p for (p,) in db.execute(lock_sql).fetchall() if p not in held]
        arm("re-arm: after its lock backend is killed, A takes the lock again on a new backend",
            killed >= 1 and len(retaken) == 1 and a.p.poll() is None,
            f"killed={killed} retaken={retaken} {(tmp / 'rearmA.err').read_text(errors='replace')[-300:]}")
        b = Mcp(server, rearm, tmp, tmp / "rearmB.err")
        servers.append(b)
        b.init()
        wait_exit(b.p, 8)
        time.sleep(4)                                   # A's re-arm delay is 3s: let a late retake decide too
        live = [x for x in (a, b) if x.p.poll() is None]
        arm("re-arm: never two live bodies (B refused, or A exits loudly)",
            len(live) == 1 and ("ANOTHER BODY" in (tmp / "rearmB.err").read_text(errors="replace")
                                or "ANOTHER BODY" in (tmp / "rearmA.err").read_text(errors="replace")),
            f"live={len(live)} A={(tmp / 'rearmA.err').read_text(errors='replace')[-200:]} "
            f"B={(tmp / 'rearmB.err').read_text(errors='replace')[-200:]}")
    finally:
        for s in servers:
            try:
                s.close()
            except Exception:                                   # noqa: BLE001
                pass
        fxcm.__exit__(None, None, None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PASS" if not fails else f"FAIL: {fails} arm(s)")
sys.exit(1 if fails else 0)
