"""Oracle for plan-5497 S1b: the PreToolUse guard keeps declared secrets out of context.

a2's probe arms (#27600), RED-first, plus the shapes the org's own transcripts show. Fixture
holders carry FAKE secrets. Each arm can ALONE go red.

  G1  Read of a declared holder is DENIED with a named reason.
  G2  An inline literal (a secret in any tool input) is DENIED, naming the secret, never its value.
  G3  The silent idiom `X=$(grep … .env | cut …)` is ALLOWED (false-positive control).
  G4  POLARITY: an unevaluable guard ALLOWS, and step.py writes an error step saying so.
  G5  The read-back shapes the transcripts show are DENIED: cat/grep/sed/head on .env, a python
      heredoc opening '.env', Read of ~/.pgpass, anything in the quarantine dir, cp of .env.
  G6  Silent operations on holders are ALLOWED: ln -s (the worktree method), ls/stat/test, chmod,
      sha256sum; a NON-holder that merely looks similar (.env.example, venv/) is never denied.
  G7  End to end through hooks/step.py: a denied call prints Claude Code's deny JSON on stdout
      BEFORE any DB work (a down DB can't open the guard); an allowed call prints nothing.

Run: venv/bin/python tests/test_secret_guard.py
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
fails = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


try:
    from nucleus import secret_guard as sg
    from nucleus import secretset as ss
except Exception as exc:                                    # noqa: BLE001 — RED without S1b
    check("nucleus.secret_guard imports", False, f"{type(exc).__name__}: {exc}")
    print(f"\nFAIL: {len(fails)} arm(s) red")
    sys.exit(1)

TOK = "tok_FAKE_71c0de5ab9f2e4d3"
PGPW = "pgFAKE_0a9b8c7d6e5f"


def setup(tmp: Path):
    # a password-less DSN: step.py's dsn() needs the line, and it contributes no secret
    (tmp / ".env").write_text(f"ASTRYX_DSN=postgresql://genesis@localhost:5432/astryx\n"
                              f"OPENAI_API_KEY={TOK}\nASTRYX_ORG=example-org\n")
    (tmp / ".env.example").write_text("OPENAI_API_KEY=\n")
    (tmp / "pgpass").write_text(f"localhost:5432:*:genesis:{PGPW}\n")
    (tmp / "svc").mkdir()
    (tmp / "svc" / "observer.env").write_text(f"X={TOK}\n")
    (tmp / "q").mkdir()
    (tmp / "q" / "dead.env").write_text(f"X={TOK}\n")
    manifest = {"scan_roots": [], "expiring": [], "holders": [
        {"path": str(tmp / "svc" / "observer.env"), "fate": "keep"},
        {"path": "docker:genesis-pg:env:POSTGRES_PASSWORD", "fate": "keep"},
        {"path": "review/branch_check worktree .env", "fate": "keep"}]}
    (tmp / "holders.json").write_text(json.dumps(manifest))
    ss.ENV_FILE, ss.PGPASS_FILE, ss.HOLDERS_FILE = tmp / ".env", tmp / "pgpass", tmp / "holders.json"
    sg.QUARANTINE = tmp / "q"


def bash(cmd):
    return sg.decide("Bash", {"command": cmd, "description": "x"})


def arms(tmp: Path):
    env = str(tmp / ".env")
    r = sg.decide("Read", {"file_path": env})
    check("G1 Read of .env is DENIED with a named reason", bool(r) and ".env" in r, str(r))
    r = sg.decide("Read", {"file_path": str(tmp / "svc" / "observer.env")})
    check("G1b Read of a MANIFEST-declared holder is DENIED", bool(r), str(r))

    r = bash(f"curl -H 'Authorization: Bearer {TOK}' https://example.invalid")
    check("G2 an inline literal is DENIED, naming the secret and never its value",
          bool(r) and "OPENAI_API_KEY" in r and TOK not in r, str(r))
    r = sg.decide("Agent", {"prompt": f"use key {TOK}"})
    check("G2b the value deny covers every tool, not just Bash", bool(r), str(r))

    for cmd in (f"KEY=$(grep ^OPENAI_API_KEY= {env} | cut -d= -f2-); curl -H \"x: $KEY\" u",
                f'DSN="$(grep ^ASTRYX_DSN= {env} | cut -d= -f2-)"; psql "$DSN" -c "select 1"'):
        r = bash(cmd)
        check(f"G3 silent idiom ALLOWED: {cmd[:48]}…", r is None, str(r))

    for cmd in (f"cat {env}", f"grep DSN {env}", f"sed -n 1,5p {env}", "head .env",
                f"cat {tmp}/pgpass ~/.pgpass", f"cat {tmp}/q/dead.env", f"cp {env} /tmp/x.env",
                f"ls {env} && cat {env}", f"diff {env} {tmp}/.env.example",
                'grep "ASTRYX_DSN" .env 2>/dev/null', "grep -n DSN .env", "grep -oE '@[^/]+/' ~/astryx/.env",
                "cp ~/astryx/.env .env", "sudo -u x cat .env", "timeout 5 grep DSN .env",
                "env X=1 cat .env", "LC_ALL=C sort .env", "cat <.env"):
        r = bash(cmd)
        check(f"G5 read-back DENIED: {cmd.splitlines()[0][:52]}", bool(r), "allowed")
    for cmd in ("cat /proc/1234/environ", 'tr "\\0" "\\n" < /proc/$pid/environ',
                "strings /proc/self/environ", "xargs -0 -n1 < /proc/77/task/78/environ"):
        check(f"G5 B2 process environ DENIED: {cmd[:44]}", bool(bash(cmd)), "allowed")
    check("G5 B2 Read of /proc/self/environ DENIED",
          bool(sg.decide("Read", {"file_path": "/proc/self/environ"})))
    check("G6 /proc/<pid>/status (not an environ) ALLOWED", bash("cat /proc/1/status") is None)
    for tool, p in (("Read", "~/.pgpass"), ("Read", str(tmp / "pgpass")),
                    ("Read", str(tmp / "q" / "dead.env")), ("Grep", env)):
        check(f"G5 {tool} {Path(p).name} DENIED", bool(sg.decide(tool, {"file_path": p, "path": p})))

    for cmd in (f"ln -s {env} wt/.env", f"ls -l {env}", f"test -f {env} && echo yes",
                f"[ -f {env} ] || exit 1", f"chmod 600 {env}", f"sha256sum {env}",
                f"cat {tmp}/.env.example", "ls venv/bin", "echo hello", "grep -rn dsn nucleus/"):
        r = bash(cmd)
        check(f"G6 ALLOWED: {cmd[:52]}", r is None, str(r))
    for cmd in (f'psql "$(grep ^ASTRYX_DSN= {env} | cut -d= -f2-)" -c "select 1"',
                "set -a; . ./.env; set +a", "for x in .env venv local.md; do ln -s ../$x w/$x; done",
                "echo 'the token stays in .env, only its key'",
                "grep -q '^WA_CLI=' .env", "grep -c ASTRYX_DSN .env", "grep -rl DSN .env nucleus",
                "sed -i '/^TEST_TOKEN=dummy$/d' .env", "grep -nE '(\\.env|venv)' nucleus/check.sh"):
        r = bash(cmd)
        check(f"G6 silent use ALLOWED (measured false positives): {cmd[:44]}", r is None, str(r))
    # KNOWN GAPS, pinned ALLOWED so the PARTIAL grade stays visible: if one of these ever turns
    # DENIED, update the grade in the module doc, don't just delete the arm.
    for cmd in ("venv/bin/python - <<'EOF'\nfor l in open('.env'):\n    print(l)\nEOF",
                "echo $(cat .env)", "printenv", "docker inspect genesis-pg"):
        r = bash(cmd)
        check(f"GAP (accident-grade, allowed by design): {cmd.splitlines()[0][:40]}", r is None, str(r))
    check("G6 Read of .env.example ALLOWED",
          sg.decide("Read", {"file_path": str(tmp / ".env.example")}) is None)


class FakeCur:
    def __init__(self):
        self.writes = []

    def execute(self, sql, params=()):
        self.writes.append((sql, params))
        return self


def run_step(step, event, tool, ti, connect_ok=True):
    import psycopg
    cur = FakeCur()

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return cur

    def connect(*a, **k):
        if not connect_ok:
            raise psycopg.OperationalError("db down")
        return Conn()

    real, real_in, real_out = psycopg.connect, sys.stdin, sys.stdout
    out = io.StringIO()
    try:
        psycopg.connect = connect
        sys.stdin = io.StringIO(json.dumps({"hook_event_name": event, "tool_name": tool,
                                            "tool_input": ti}))
        sys.stdout = out
        try:
            step.main()
        except Exception:                                  # step.py's own __main__ swallows these
            pass
    finally:
        psycopg.connect, sys.stdin, sys.stdout = real, real_in, real_out
    return out.getvalue(), cur.writes


def arms_step(tmp: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("step_s1b", REPO / "hooks/step.py")
    step = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(step)
    step.DSN_FILE = str(tmp / ".env")
    os.environ["ASTRYX_AGENT"] = "abstractor-1"

    out, writes = run_step(step, "PreToolUse", "Read", {"file_path": str(tmp / ".env")},
                           connect_ok=False)
    try:
        d = json.loads(out)["hookSpecificOutput"]
    except Exception:                                      # noqa: BLE001
        d = {}
    check("G7 step.py prints the DENY decision even with the DB down",
          d.get("permissionDecision") == "deny" and d.get("hookEventName") == "PreToolUse"
          and "plan-5497" in d.get("permissionDecisionReason", ""), repr(out[:200]))
    out, writes = run_step(step, "PreToolUse", "Bash", {"command": "echo hi", "description": "d"})
    check("G7b an allowed call prints NOTHING on stdout (no accidental decision)", out == "",
          repr(out[:120]))
    out, writes = run_step(step, "PreToolUse", "Read", {"file_path": str(tmp / ".env")})
    check("G7c a denied call is still logged, marked DENIED",
          any("DENIED" in str(p) for s, p in writes if "steps" in s), str(writes)[:200])

    saved = ss.holders
    ss.holders = lambda path=None: (_ for _ in ()).throw(RuntimeError("manifest unreadable"))
    try:
        out, writes = run_step(step, "PreToolUse", "Read", {"file_path": str(tmp / ".env")})
    finally:
        ss.holders = saved
    check("G4 POLARITY: an unevaluable guard ALLOWS (no deny on stdout)", out == "", repr(out[:120]))
    check("G4b … and writes an error step saying it allowed",
          any("unevaluable" in str(p) for s, p in writes if "'error'" in s), str(writes)[:200])


def main():
    saved = (ss.ENV_FILE, ss.PGPASS_FILE, ss.HOLDERS_FILE, sg.QUARANTINE)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        try:
            setup(tmp)
            arms(tmp)
            arms_step(tmp)
        finally:
            ss.ENV_FILE, ss.PGPASS_FILE, ss.HOLDERS_FILE, sg.QUARANTINE = saved
    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    print("\nPASS: declared secrets stay out of context (plan-5497 S1b; accident-grade, see G-docs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
