"""Oracle for plan-5497 S2: the at-rest sweep finds, and redacts without corrupting, secret copies.

Fixture transcripts in a temp dir and a throwaway database (fixture_db); FAKE secrets only.
Each arm can ALONE go red:
  W1 SCAN finds every holding file (plain, .bak, archive/, aside) by NAME; the report holds no value.
  W2 REDACT: afterwards no form remains, every line that parsed still parses, the non-secret bytes
     are unchanged (the file equals a plain substring replacement), and the file mode is kept.
  W3 ACTIVE: the newest recent *.jsonl in a project is REPORTED as held and left byte-identical
     (a resumed session re-reads it).
  W4 a rewrite that would break a line's JSON is SKIPPED and named, the file left as it was.
  W5 turns (real DB): rows holding a secret in raw_payload or input_prompt are found; after
     redaction 0 remain, the payload keeps its structure and the usage numbers are untouched.
  W6 a re-scan after redaction reports only the ACTIVE file: S2's "re-scanned to 0" can't pass
     while a live transcript still holds the value.

Run: venv/bin/python tests/test_secret_sweep.py   (the turns arm SKIPs, loudly, without a DB)
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
fails = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


try:
    from nucleus import secret_sweep as sw
    from nucleus import secretset as ss
except Exception as exc:                                    # noqa: BLE001
    check("nucleus.secret_sweep imports", False, f"{type(exc).__name__}: {exc}")
    print(f"\nFAIL: {len(fails)} arm(s) red")
    sys.exit(1)

TOK = "tok_FAKE_5a6b7c8d9e0f1a2b"
BS = "bs_FAKE\\path\\secret99"                             # JSON doubles its backslashes


def secrets(tmp: Path):
    (tmp / ".env").write_text(f"OPENAI_API_KEY={TOK}\nODD_KEY={BS}\n")
    (tmp / "pgpass").write_text("")
    return ss.secret_set(tmp / ".env", tmp / "pgpass")


def jl(*objs) -> str:
    return "".join(json.dumps(o) + "\n" for o in objs)


def build(tmp: Path) -> dict:
    proj = tmp / "projects" / "-home-x-homes-a"
    (proj / "archive").mkdir(parents=True)
    old = proj / "old.jsonl"
    old.write_text(jl({"type": "user", "message": {"content": f"cat .env -> OPENAI_API_KEY={TOK}"}},
                      {"type": "assistant", "message": {"content": [{"type": "text", "text": BS}]}})
                   + "not json but has " + TOK + "\n")
    os.chmod(old, 0o600)
    os.utime(old, (time.time() - 30 * 86400,) * 2)
    bak = proj / "old.jsonl.presend-fix.bak"
    bak.write_text(jl({"k": TOK}))
    arch = proj / "archive" / "a.jsonl"
    arch.write_text(jl({"k": [TOK, {"n": 1}]}))
    live = proj / "live.jsonl"
    live.write_text(jl({"k": TOK}))
    clean = proj / "clean.jsonl"
    clean.write_text(jl({"k": "nothing"}))
    os.utime(clean, (time.time() - 40 * 86400,) * 2)
    aside = tmp / "homes" / "b" / ".transcript-aside"
    aside.mkdir(parents=True)
    ax = aside / "s.jsonl"
    ax.write_text(jl({"k": TOK}))
    return {"old": old, "bak": bak, "arch": arch, "live": live, "clean": clean, "aside": ax}


def arms_files(tmp: Path):
    S = secrets(tmp)
    f = build(tmp)
    sw.PROJECTS = tmp / "projects"
    files = sorted(f.values())
    before = {k: p.read_bytes() for k, p in f.items()}

    rep = sw.sweep(do_redact=False, secrets=S, files=files, turns=False)
    found = {Path(k.replace("~", str(Path.home()))).name for k in rep["files"]}
    check("W1 scan finds every holding file (plain, .bak, archive/, aside), not the clean one",
          found == {"old.jsonl", "old.jsonl.presend-fix.bak", "a.jsonl", "live.jsonl", "s.jsonl"},
          str(found))
    blob = json.dumps(rep)
    check("W1b the report names secrets, never holds a value",
          TOK not in blob and "secret99" not in blob and "OPENAI_API_KEY" in blob)

    rep = sw.sweep(do_redact=True, secrets=S, files=files, turns=False)
    after = {k: p.read_bytes() for k, p in f.items()}
    expect_old = before["old"].decode()
    for s in S:
        for form in sorted(s.forms, key=len, reverse=True):
            expect_old = expect_old.replace(form, ss.marker(s.name))
    still = [k for k in ("old", "bak", "arch", "aside") if ss.scan(after[k].decode(), S)]
    check("W2 no form remains in any inactive holder", not still, str(still))
    check("W2b non-secret bytes unchanged: the file equals a plain substring replacement",
          after["old"].decode() == expect_old)
    parsed_before = [ln for ln in before["old"].decode().splitlines() if sw._parses(ln)]
    parsed_after = [ln for ln in after["old"].decode().splitlines() if sw._parses(ln)]
    check("W2c every line that parsed still parses", len(parsed_before) == len(parsed_after) == 2)
    check("W2d the file mode is kept (0600)", oct(f["old"].stat().st_mode & 0o777) == "0o600")
    check("W2e a clean file is never rewritten", after["clean"] == before["clean"])

    check("W3 the ACTIVE transcript is reported as held and left byte-identical",
          after["live"] == before["live"] and any("live.jsonl" in k for k in rep["held_active"]),
          str(rep["held_active"]))

    rescan = sw.sweep(do_redact=False, secrets=S, files=files, turns=False)
    check("W6 the re-scan reports ONLY the active file",
          [Path(k).name for k in rescan["files"]] == ["live.jsonl"], str(list(rescan["files"])))

    # W4: a redaction that would break a line's JSON is skipped and named, file untouched
    victim = tmp / "projects" / "-home-x-homes-a" / "archive" / "v.jsonl"
    victim.write_text(jl({"k": TOK}))
    vb = victim.read_bytes()
    real = ss.redact
    try:
        ss.redact = lambda o, secrets=None: o.replace(TOK, '"broken') if isinstance(o, str) else o
        rep = sw.sweep(do_redact=True, secrets=S, files=[victim], turns=False)
    finally:
        ss.redact = real
    check("W4 a rewrite that would break JSON is SKIPPED, named, and the file left as it was",
          victim.read_bytes() == vb and any("stop parsing" in v for v in rep["skipped"].values()),
          str(rep["skipped"]))


def arm_turns(tmp: Path):
    try:
        from nucleus.sqlguard.fixture import fixture_db
        import psycopg
        from psycopg.types.json import Jsonb
    except Exception as e:                                  # noqa: BLE001
        print(f"  SKIP  W5 turns arm: {type(e).__name__}")
        return
    S = secrets(tmp)
    try:
        cm = fixture_db()
        db = cm.__enter__()
    except Exception as e:                                  # noqa: BLE001
        print(f"  SKIP  W5 turns arm: no fixture database ({type(e).__name__})")
        return
    try:
        payload = {"messages": [{"type": "user", "message": {"content": [
                       {"type": "tool_result", "content": f"OPENAI_API_KEY={TOK}"}]}},
                                {"type": "assistant", "message": {"content": [{"type": "text", "text": BS}]}}],
                   "usage": {"tokens_in": 11, "tokens_out": 7}}
        with psycopg.connect(db["dsn"], autocommit=True) as c:
            c.execute("INSERT INTO turns (agent, ended_at, raw_payload, input_prompt) VALUES "
                      "('a', now(), %s, %s), ('b', now(), %s, 'clean'), ('c', now(), %s, 'nothing')",
                      (Jsonb(payload), f"use {TOK}", Jsonb(payload), Jsonb({"messages": [], "usage": {}})))
        found = sw.sweep_turns(S, do_redact=False, dsn=db["dsn"])
        check("W5 turns: rows holding a secret (payload or prompt) are found, by name",
              found["rows"] == 2 and "OPENAI_API_KEY" in found["by_name"], str(found))
        sw.sweep_turns(S, do_redact=True, dsn=db["dsn"])
        again = sw.sweep_turns(S, do_redact=False, dsn=db["dsn"])
        with psycopg.connect(db["dsn"]) as c:
            p, prompt = c.execute("SELECT raw_payload, input_prompt FROM turns WHERE agent='a'").fetchone()
        check("W5b after redaction 0 rows remain; structure and usage are intact",
              again["rows"] == 0 and len(p["messages"]) == 2 and p["usage"] == payload["usage"]
              and "[redacted:OPENAI_API_KEY]" in json.dumps(p) and "[redacted:" in prompt,
              f"rows={again['rows']}")
    finally:
        cm.__exit__(None, None, None)


def main():
    with tempfile.TemporaryDirectory() as d:
        saved = sw.PROJECTS
        try:
            arms_files(Path(d))
            arm_turns(Path(d))
        finally:
            sw.PROJECTS = saved
    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    print("\nPASS: the at-rest sweep finds and redacts without corrupting (plan-5497 S2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
