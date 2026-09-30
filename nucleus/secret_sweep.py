"""At-rest secret sweep (plan-5497 S2): find, and on request redact, declared secrets in the
copies nobody declared as holders: session transcripts and the turns table.

  venv/bin/python -m nucleus.secret_sweep                 # SCAN (default): counts by name, never a value
  venv/bin/python -m nucleus.secret_sweep --redact        # rewrite inactive files + UPDATE turns
  venv/bin/python -m nucleus.secret_sweep --json

DOMAINS (stated in every report, so a zero means what it says):
  transcripts   ~/.claude/projects/**/*.jsonl* (incl .bak) and **/archive/**, homes/*/.transcript-aside/*
  turns         turns.raw_payload + turns.input_prompt
  NOT searched  backups/ (by-design holders in the manifest: they age out and are made dead by
                rotation), compressed files, anything outside these roots.

REDACTION replaces only the secret's spellings with "[redacted:<name>]" (secretset.redact on the
decoded JSON for turns; the JSON-escaped form on transcript lines). The marker holds no quote or
backslash, so a line's JSON structure can't change; each rewritten line is RE-PARSED before the
file is replaced (atomically, mode kept), and a file where any line would stop parsing is skipped
and named. Nothing is kept: the only bytes removed are the secret, so there is no rollback copy
to become a new holder (BC-2).

ACTIVE SESSIONS are never rewritten: a resumed session re-reads its transcript. A *.jsonl that is
the newest in its project dir and was written in the last ACTIVE_DAYS is ACTIVE; it is reported
as "held for the next session refresh", never silently skipped.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from nucleus import secretset as ss  # noqa: E402

ACTIVE_DAYS = 7
PROJECTS = Path.home() / ".claude" / "projects"


def transcript_files() -> list[Path]:
    fs = [p for p in PROJECTS.rglob("*") if p.is_file() and (".jsonl" in p.name or "archive" in p.parts)]
    fs += [p for p in REPO.glob("homes/*/.transcript-aside/*") if p.is_file()]
    return sorted(fs)


def active(files: list[Path], now: float = None) -> set[Path]:
    now = now or time.time()
    newest = {}
    for f in files:
        if f.suffix == ".jsonl" and f.parent.parent == PROJECTS:
            if f.parent not in newest or f.stat().st_mtime > newest[f.parent].stat().st_mtime:
                newest[f.parent] = f
    return {f for f in newest.values() if now - f.stat().st_mtime < ACTIVE_DAYS * 86400}


def _parses(line: str) -> bool:
    try:
        json.loads(line)
        return True
    except ValueError:
        return False


def redact_file(f: Path, secrets) -> tuple[int, str]:
    """(occurrences removed, status). Status: 'redacted' | 'clean' | 'skipped: <why>'."""
    text = f.read_text(errors="surrogateescape")
    hits = ss.scan(text, secrets)
    if not hits:
        return 0, "clean"
    out = []
    for line in text.splitlines(keepends=True):
        new = ss.redact(line, secrets)
        if new != line and _parses(line.rstrip("\n")) and not _parses(new.rstrip("\n")):
            return 0, "skipped: a redacted line would stop parsing"
        out.append(new)
    new_text = "".join(out)
    if ss.scan(new_text, secrets):
        return 0, "skipped: a form survived redaction"
    tmp = f.with_name(f.name + ".sweep-tmp")
    mode = f.stat().st_mode & 0o777
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", errors="surrogateescape") as w:
        w.write(new_text)
        w.flush()
        os.fsync(w.fileno())
    os.replace(tmp, f)
    return sum(hits.values()), "redacted"


def sweep_turns(secrets, do_redact: bool, dsn: str = None) -> dict:
    import psycopg
    from psycopg.types.json import Jsonb
    dsn = dsn or next(l.split("=", 1)[1].strip() for l in (REPO / ".env").read_text().splitlines()
                      if l.startswith("ASTRYX_DSN="))
    out = {"rows": 0, "redacted": 0, "by_name": {}}
    with psycopg.connect(dsn) as c:
        forms = sorted({f for s in secrets for f in s.forms})
        ids = {r[0] for r in c.execute(
            "SELECT id FROM (SELECT id, raw_payload::text AS t, coalesce(input_prompt,'') AS p "
            "FROM turns) x WHERE EXISTS (SELECT 1 FROM unnest(%s::text[]) f "
            "WHERE position(f in x.t) > 0 OR position(f in x.p) > 0)", (forms,)).fetchall()}
        out["rows"] = len(ids)
        for tid in sorted(ids):
            payload, prompt = c.execute("SELECT raw_payload, input_prompt FROM turns WHERE id=%s",
                                        (tid,)).fetchone()
            for k, v in ss.scan(json.dumps(payload) + (prompt or ""), secrets).items():
                out["by_name"][k] = out["by_name"].get(k, 0) + v
            if do_redact:
                with c.transaction():
                    c.execute("UPDATE turns SET raw_payload=%s, input_prompt=%s WHERE id=%s",
                              (Jsonb(ss.redact(payload, secrets)), ss.redact(prompt, secrets), tid))
                out["redacted"] += 1
    return out


def sweep(do_redact: bool = False, secrets=None, files=None, turns: bool = True) -> dict:
    secrets = ss.secret_set() if secrets is None else secrets
    files = transcript_files() if files is None else files
    live = active(files)
    rep = {"domains": {"transcripts": [str(PROJECTS / "**"), "homes/*/.transcript-aside/*"],
                       "turns": "raw_payload + input_prompt",
                       "not_searched": ["backups/ (declared holders)", "compressed files"]},
           "files_scanned": len(files), "files": {}, "held_active": [], "skipped": {}}
    for f in files:
        try:
            hits = ss.scan(f.read_text(errors="replace"), secrets)
        except OSError as e:
            rep["skipped"][str(f)] = f"unreadable: {type(e).__name__}"
            continue
        if not hits:
            continue
        key = str(f).replace(str(Path.home()), "~")
        rep["files"][key] = hits
        if f in live:
            rep["held_active"].append(key)
        elif do_redact:
            n, status = redact_file(f, secrets)
            if status.startswith("skipped"):
                rep["skipped"][key] = status
    if turns:
        rep["turns"] = sweep_turns(secrets, do_redact)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redact", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = sweep(do_redact=a.redact)
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        print(f"domains: {rep['domains']}")
        print(f"{rep['files_scanned']} transcript files scanned; {len(rep['files'])} hold a secret; "
              f"{len(rep['held_active'])} ACTIVE (held for the next session refresh)")
        for k, v in rep["files"].items():
            print(f"  {'ACTIVE ' if k in rep['held_active'] else ''}{k}: {v}")
        for k, v in rep["skipped"].items():
            print(f"  SKIPPED {k}: {v}")
        t = rep.get("turns", {})
        print(f"turns: {t.get('rows')} rows hold a secret {t.get('by_name')}; redacted {t.get('redacted')}")
    if a.redact:
        after = sweep(do_redact=False)
        left = {k: v for k, v in after["files"].items()}
        print(f"AFTER: {len(left)} file(s) still hold a secret "
              f"({len(after['held_active'])} active, held for session refresh); "
              f"turns rows {after.get('turns', {}).get('rows')}")
        rep = after
    return 0 if not rep["files"] and not rep.get("turns", {}).get("rows") else 1

if __name__ == "__main__":
    sys.exit(main())
