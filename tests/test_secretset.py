"""Oracle for plan-5497 S0 + S1a: one derived secret set, and a turn writer that never copies one.

S0 (nucleus/secretset.py): the set is DERIVED from the holders (.env, ~/.pgpass), fail-safe (a key
nobody classified is secret), URL-aware (a DSN's password, a capability URL's query value; never
its host), and reports what it can't guard instead of dropping it.
S1a (hooks/step.py): turns.raw_payload is the one transcript copy we own, and every pg_dump
inherits it. Every declared secret is replaced by a marker before the row is written; when the
set can't be derived, the copies are WITHHELD, never written raw.

Each arm can ALONE go red. Fixture holders carry FAKE secrets; the live arm (L) reads the real
holders and prints counts and key NAMES only, never a value.

Run: venv/bin/python tests/test_secretset.py
"""
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

fails = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


try:
    from nucleus import secretset as ss
except Exception as exc:                                    # noqa: BLE001 — RED on a tree without S0
    ss = None
    check("nucleus.secretset imports", False, f"{type(exc).__name__}: {exc}")

# ------------------------------------------------------------------ fixtures (all FAKE)
TOK = "tok_FAKE_9f3a1c77e0b24d6a"                 # opaque key
NEW = "new_FAKE_c1d2e3f4a5b6c7d8"                 # a key nobody classified yet
PW = "p@ss:w/rd FAKE+9=%"                          # needs URL-encoding; has a space
APP = "abcd efgh ijkl mnop"                        # app-password shape (spaces) — a1 F5 missed it
CAP = "capFAKE0123456789abcdef"                    # a capability URL's key=
PGPW = "pg:FAKE\\secret77"                         # pgpass escapes ':' and '\'
SHORT = "abc12"
HOOKTOK = "hookFAKE7d8e9f0a1b2c"                    # a2 #28956 B1: a token in a URL PATH
USERTOK = "ghpFAKE3c4d5e6f7a8b9"                    # … and in the userinfo USERNAME
ENV = f"""# comment
ASTRYX_DSN=postgresql://genesis:{__import__('urllib.parse').parse.quote(PW, safe='')}@127.0.0.1:5432/astryx
GEOLOC_DSN=postgresql://genesis:{__import__('urllib.parse').parse.quote(PW, safe='')}@127.0.0.1:5432/geo
OBSERVER_DSN=postgresql://genesis@localhost:5432/genesis
PLAIN_DSN=postgresql://genesis@localhost:5432/astryx
NEW_HOOK=https://hooks.example.invalid/services/T0AAA/B0BBB/{HOOKTOK}
TOKEN_AS_USER=https://{USERTOK}@git.example.invalid/x.git
OPENAI_API_KEY={TOK}
BRAND_NEW_KEY={NEW}
GMAIL_APP_PASSWORD="{APP}"
AUTOREMOTE_GETLOC_URL=https://example.invalid/sendmessage?key={CAP}&message=getlocation
ASTRYX_ORG=example-org
ASTRYX_URL=http://203.0.113.9:8845
TINY_PIN={SHORT}
"""
PGPASS = "localhost:5432:*:genesis:" + PGPW.replace("\\", "\\\\").replace(":", "\\:") + "\n"
ALL_FAKE = (TOK, NEW, PW, APP, CAP, PGPW)


def fixture(tmp: Path, env=ENV, pgpass=PGPASS):
    (tmp / ".env").write_text(env)
    (tmp / "pgpass").write_text(pgpass)
    return tmp / ".env", tmp / "pgpass"


def leaks(blob: str) -> list[str]:
    """Which fake secrets (by position) appear in blob, in ANY form secretset would redact."""
    import urllib.parse as up
    # the JSON-escaped spelling too: the blob is json.dumps'd, and a backslash in a secret is
    # doubled there, so matching only the raw spelling would be blind to it (PGPW was, at first)
    forms = lambda v: {v, up.quote(v, safe=""), up.quote_plus(v), json.dumps(v)[1:-1]}
    return [f"#{i}" for i, v in enumerate(ALL_FAKE) if any(f in blob for f in forms(v))]


def arms_s0(tmp):
    envf, ppf = fixture(tmp)
    S = ss.secret_set(envf, ppf)
    vals = {s.value for s in S}
    names = {s.name for s in S}
    check("S0.1 an opaque key is secret", TOK in vals)
    check("S0.2 POLARITY: a key nobody classified is secret (fail-safe)", NEW in vals)
    check("S0.3 NOT_SECRET keys are not in the set",
          "example-org" not in vals and not any("203.0.113.9" in v for v in vals))
    check("S0.4 a DSN contributes its PASSWORD, decoded, never the host",
          PW in vals and not any("127.0.0.1" in v for v in vals), f"names={sorted(names)}")
    check("S0.5 a URL_CONFIG DSN without a password contributes nothing (post-S1c shape)",
          not any(n.startswith("OBSERVER_DSN") for n in names), f"names={sorted(names)}")
    check("S0.5b URL_CONFIG gives up WHOLE-URL guarding only: its password is still guarded",
          PW in vals and not any(v.startswith("postgresql://genesis:") for v in vals))
    check("S0.5c B1 POLARITY: an UNCLASSIFIED URL with no password and no query is guarded WHOLE",
          any(HOOKTOK in v for v in vals) and any(n == "PLAIN_DSN" for n in names),
          f"names={sorted(names)}")
    check("S0.5d B1: a token in the userinfo USERNAME is guarded, whole and alone",
          USERTOK in vals and any(USERTOK in v and v != USERTOK for v in vals),
          f"names={sorted(names)}")
    check("S0.6 a capability URL's query value is secret", CAP in vals)
    check("S0.6b a query param declared NOT_SECRET ('<KEY>:<param>') is not",
          "getlocation" not in vals, f"names={sorted(names)}")
    check("S0.7 a value with spaces is secret (quoted in .env)", APP in vals)
    check("S0.8 a ~/.pgpass password is secret, escapes decoded", PGPW in vals)
    check("S0.9 one value under two keys is kept once",
          sum(1 for s in S if s.value == PW) == 1)
    check("S0.10 a too-short value is REPORTED, not silently dropped",
          SHORT not in vals and "TINY_PIN" in ss.unguardable(envf, ppf))
    pw = next(s for s in S if s.value == PW)
    check("S0.11 the URL-encoded spelling is a guarded form",
          __import__("urllib.parse").parse.quote(PW, safe="") in pw.forms)

    nested = {"a": [f"x {TOK} y", {"k": ENV}], f"key-{CAP}": (APP,), "n": 7}
    red = ss.redact(nested, S)
    blob = json.dumps(red)
    check("S0.12 redact walks str/list/tuple/dict KEYS and removes every fake form",
          not leaks(blob), f"left={leaks(blob)}")
    check("S0.13 redact leaves a named marker and non-strings intact",
          "[redacted:OPENAI_API_KEY]" in blob and red["n"] == 7)
    check("S0.14 scan counts by NAME and never returns a value",
          ss.scan(f"{TOK} {TOK}", S) == {"OPENAI_API_KEY": 2})

    # longest-first: a secret that CONTAINS another must redact whole, not leave a tail
    envf2, ppf2 = fixture(tmp, env=f"OUTER_KEY=zz{TOK}zz\nINNER_KEY={TOK}\n", pgpass="")
    S2 = ss.secret_set(envf2, ppf2)
    out = ss.redact(f"[zz{TOK}zz]", S2)
    check("S0.15 a secret containing another redacts whole (longest first)",
          out == "[[redacted:OUTER_KEY]]", out)


class FakeCur:
    """Answers step.py's reads; records every write's params."""

    def __init__(self):
        self.writes = []
        self.connection = self

    def transaction(self):
        import contextlib
        return contextlib.nullcontext()

    def execute(self, sql, params=()):
        self.last = sql
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE")):
            self.writes.append((sql, params))
        return self

    def fetchone(self):
        if "ended_at FROM turns" in self.last:
            return (datetime.now(timezone.utc),)        # usage throttle: no network read
        if "RETURNING id" in self.last:
            return (4242,)
        return None


def dump_writes(writes, *extra) -> str:
    """Every written param, UNWRAPPED: str() of psycopg's Jsonb hides its payload, so an arm that
    stringified params would never look inside raw_payload (it did, in this oracle's first draft)."""
    def val(p):
        return getattr(p, "obj", p)
    return json.dumps([[val(p) for p in (params or ())] for _, params in writes] + list(extra),
                      default=str)


def load_step():
    spec = importlib.util.spec_from_file_location("step_under_test", REPO / "hooks/step.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def transcript(tmp: Path) -> Path:
    t = tmp / "t.jsonl"
    now = "2026-09-30T00:00:00Z"
    ev = [
        {"type": "user", "timestamp": now, "message": {"role": "user",
                                                       "content": f"please use {TOK}"}},
        {"type": "assistant", "timestamp": now, "message": {"id": "m1", "role": "assistant",
         "content": [{"type": "tool_use", "id": "u1", "name": "Bash",
                      "input": {"command": f"psql 'postgresql://genesis:{PW}@h/db' -c {CAP}",
                                "description": f"query with {APP}"}}],
         "usage": {"input_tokens": 3, "output_tokens": 5}}},
        {"type": "user", "timestamp": now, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "u1", "content": f"{ENV}\n{PGPW}\n{NEW}"}]}},
        {"type": "assistant", "timestamp": now, "message": {"id": "m2", "role": "assistant",
         "content": [{"type": "text", "text": f"done; the key was {TOK}"}],
         "usage": {"input_tokens": 1, "output_tokens": 2}}},
    ]
    t.write_text("\n".join(json.dumps(e) for e in ev) + "\n")
    return t


def arms_s1a(tmp):
    envf, ppf = fixture(tmp)
    step = load_step()
    if not hasattr(step, "cleaner"):
        check("S1a step.py has a secret cleaner", False, "no cleaner(): the writer copies raw")
    ss.ENV_FILE, ss.PGPASS_FILE = envf, ppf
    cur = FakeCur()
    res = step.handle_stop(cur, "abstractor-1", {"transcript_path": str(transcript(tmp)),
                                                 "session_id": "s"})
    blob = dump_writes(cur.writes, str(res))
    turn_rows = [p for sql, p in cur.writes if "INSERT INTO turns" in sql]
    check("S1a.1 a turn row is still written", len(turn_rows) == 1)
    payload = getattr(turn_rows[0][14], "obj", None) if turn_rows else None
    check("S1a.1b the oracle SEES the payload (it is a dict with the transcript's messages)",
          isinstance(payload, dict) and len(payload.get("messages", [])) == 4,
          f"payload type={type(payload).__name__}")
    check("S1a.2 NO fake secret in any write (payload, prompt, tool input, tool_result, text)",
          not leaks(blob), f"left={leaks(blob)}")
    check("S1a.3 the returned reply text (response step, auto-deliver) is clean",
          res and not leaks(str(res[1])) and "[redacted:OPENAI_API_KEY]" in res[1], str(res and res[1]))
    check("S1a.4 usage stays exact (a cleaned turn still bills)",
          res and res[2] == 4 and res[3] == 7, str(res and res[2:]))

    # POLARITY: the set can't be derived -> the copies are withheld, never written raw
    ss.ENV_FILE = tmp / "missing.env"
    cur = FakeCur()
    res = step.handle_stop(cur, "abstractor-1", {"transcript_path": str(transcript(tmp)),
                                                 "session_id": "s"})
    blob = dump_writes(cur.writes, str(res))
    check("S1a.5 POLARITY: unreadable .env -> nothing written raw", not leaks(blob),
          f"left={leaks(blob)}")
    check("S1a.6 POLARITY: the turn row still lands, marked, and an error step says why",
          any("INSERT INTO turns" in s for s, _ in cur.writes)
          and any("redaction unavailable" in str(p) for s, p in cur.writes if "steps" in s),
          f"writes={[s.split('(')[0].strip() for s, _ in cur.writes]}")
    ss.ENV_FILE = envf

    # PreToolUse: a description quoting a secret never reaches the public steps row
    import io
    import psycopg
    real_connect, real_stdin = psycopg.connect, sys.stdin
    cur = FakeCur()

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return cur

    try:
        psycopg.connect = lambda *a, **k: Conn()
        step.DSN_FILE = str(envf)
        sys.stdin = io.StringIO(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                            "tool_input": {"command": "true",
                                                           "description": f"use {TOK}"}}))
        import os
        os.environ["ASTRYX_AGENT"] = "abstractor-1"
        step.main()
    finally:
        psycopg.connect, sys.stdin = real_connect, real_stdin
    blob = dump_writes(cur.writes)
    check("S1a.7 PreToolUse: a secret in a description never reaches steps.content",
          cur.writes and not leaks(blob), f"writes={len(cur.writes)} left={leaks(blob)}")


def arms_manifest(tmp):
    """L.4's instrument on a fixture estate: it must SEE an undeclared holder, and stop seeing it
    once declared (else an empty result would be vacuous)."""
    envf, ppf = fixture(tmp)
    S = ss.secret_set(envf, ppf)
    (tmp / "svc").mkdir(exist_ok=True)
    (tmp / "svc" / "a.env").write_text(f"X={TOK}\n")
    (tmp / "svc" / "clean.env").write_text("X=nothing-here\n")
    m = {"scan_roots": ["svc/*.env"], "holders": [], "expiring": []}
    u = ss.undeclared(S, m, root=tmp)
    check("M.1 an undeclared secret-bearing file is FOUND (names only)",
          list(u.values()) == [["OPENAI_API_KEY"]], str(u))
    m["holders"].append({"path": "svc/a.env", "fate": "keep"})
    check("M.2 once declared, it is not reported; a clean file never is",
          ss.undeclared(S, m, root=tmp) == {})
    m["holders"] = []
    m["expiring"].append({"path": "svc/a.env", "fate": "expire", "expires": "2026-10-07"})
    check("M.3 an EXPIRING holder counts as declared until it is deleted (BC-2)",
          ss.undeclared(S, m, root=tmp) == {})
    live = ss.holders()
    check("M.4 the live manifest parses and every entry names a fate",
          all(h.get("fate") in ("keep", "retire", "expire", "minimize")
              for h in live["holders"] + live["expiring"]))
    # B2(c): a unit whose EnvironmentFile holds a secret is a holder of its PROCESS ENVIRON
    ud = tmp / "units"
    ud.mkdir(exist_ok=True)
    (ud / "x-leaky.service").write_text(f"[Service]\nEnvironmentFile=-{tmp}/svc/a.env\n")
    (ud / "x-clean.service").write_text(f"[Service]\nEnvironmentFile={tmp}/svc/clean.env\n")
    saved = ss.UNIT_DIRS
    try:
        ss.UNIT_DIRS = (ud,)
        found = ss.env_file_units(S)
        m2 = {"holders": [], "expiring": [], "scan_roots": []}
        und = ss.undeclared_unit_envs(S, m2)
        m2["holders"].append({"path": "unit-env:x-leaky.service", "fate": "minimize"})
        und2 = ss.undeclared_unit_envs(S, m2)
    finally:
        ss.UNIT_DIRS = saved
    check("M.5 a unit whose EnvironmentFile holds a secret is FOUND, a clean one is not",
          list(found) == ["unit-env:x-leaky.service"], str(found))
    check("M.6 it is undeclared until the manifest names it", bool(und) and not und2)
    # a LINK to a holder under a scan root is not a copy; a real copy is
    (tmp / "scratch").mkdir(exist_ok=True)
    (tmp / "scratch" / ".env").symlink_to(tmp / "svc" / "a.env")
    (tmp / "scratch2").mkdir(exist_ok=True)
    (tmp / "scratch2" / ".env").write_text(f"X={TOK}\n")
    m3 = {"scan_roots": [str(tmp) + "/**/.env*"],
          "holders": [{"path": "svc/a.env", "fate": "keep"}, {"path": ".env", "fate": "keep"}],
          "expiring": []}
    u3 = ss.undeclared(S, m3, root=tmp)
    (tmp / "src.env").write_text(f"A_TOKEN={TOK}\nB_DSN=postgresql://u@h/d\nOTHER=x\n")
    (tmp / "copy.env").write_text(f"A_TOKEN={TOK}\nB_DSN=postgresql://u@h/d\n")
    md = {"holders": [{"path": "copy.env", "fate": "keep",
                       "derived_from": {"src.env": ["A_TOKEN", "B_DSN"]}}], "expiring": []}
    ok_before = ss.derived_drift(md, root=tmp)
    (tmp / "src.env").write_text(f"A_TOKEN=rotated_FAKE_000111222\nB_DSN=postgresql://u@h/d\n")
    drift = ss.derived_drift(md, root=tmp)
    check("M.8 a derived copy equal to its source is clean; a rotated source is DRIFT, named, "
          "never valued", ok_before == {} and drift == {"copy.env": ["A_TOKEN"]}
          and TOK not in json.dumps(drift), f"{ok_before} {drift}")
    check("M.7 a symlink to a holder is not reported; a real .env copy is",
          list(u3) == [str(tmp / "scratch2" / ".env")], str(list(u3)))


def arm_live():
    """The REAL holders: the set is non-empty (anti-vacuity) and every NOT_SECRET value is clean."""
    if not ss.ENV_FILE.exists():
        print(f"  skip  L (no {ss.ENV_FILE.name} in this tree)")
        return
    S = ss.secret_set()
    check("L.1 the live set is non-empty (a derivation that finds nothing is vacuous)",
          len(S) > 0, f"n={len(S)}")
    cfg = [(k, v) for k, v in ss._env_pairs(ss.ENV_FILE) if k in ss.NOT_SECRET]
    dirty = sorted(k for k, v in cfg if ss.scan(v, S))
    check("L.2 no NOT_SECRET value carries a secret (the allowlist hides nothing)", not dirty,
          f"keys={dirty}")
    # a live secret in a TRACKED file is either a committed leak or an over-broad rule (an ordinary
    # word classed as secret would be redacted from every transcript): RED either way
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                             text=True).stdout.split("\0")
    hits = {}
    for rel in filter(None, tracked):
        p = REPO / rel
        if p.is_file() and not p.is_symlink():
            try:
                r = ss.scan(p.read_text(errors="replace"), S)
            except OSError:
                continue
            if r:
                hits[rel] = sorted(r)
    check("L.3 no live secret appears in any tracked file (leak or over-broad rule)",
          len(tracked) > 50 and not hits, f"tracked={len(tracked)} hits={hits}")
    dd = ss.derived_drift()
    check("L.6 every hand-derived copy still equals its source (names only)", not dd, f"drift={dd}")
    uu = ss.undeclared_unit_envs(S)
    check("L.5 every unit whose EnvironmentFile holds a secret is a DECLARED holder", not uu,
          f"undeclared={uu}")
    und = ss.undeclared(S)
    check("L.4 every secret-bearing file under the scan roots is a DECLARED holder",
          not und, f"undeclared={ {k.replace(str(Path.home()), '~'): v for k, v in und.items()} }")
    print(f"        live: {len(S)} secrets; unguardable (too short): {ss.unguardable() or 'none'}")


def main():
    if ss is None:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        saved = (ss.ENV_FILE, ss.PGPASS_FILE)
        try:
            arms_s0(tmp)
            arms_s1a(tmp)
            arms_manifest(tmp)
        finally:
            ss.ENV_FILE, ss.PGPASS_FILE = saved
    arm_live()
    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    print("\nPASS: one derived secret set; the turn writer copies none (plan-5497 S0+S1a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
