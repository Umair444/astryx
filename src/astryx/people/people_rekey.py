#!/usr/bin/env python
"""astryx · people_rekey — move people ids from the salt the old .env line order picked to the one _salt() picks now.

Before the salt-order fix, people._salt() returned whichever of PEOPLE_SALT / ASTRYX_ORG the .env named FIRST, so an
install whose ASTRYX_ORG line sits above PEOPLE_SALT hashed every id with the public org name. With the fix the ids
change (PEOPLE_SALT wins), and every row keyed by the old ids would stop matching: social_relation is not rebuilt by
the nightly sweep, so its details would orphan. This re-keys them in place.

An id is a hash of a channel id (jid) that is never stored, so the map is rebuilt from the channel: every chat, and
every sender in every group's messages. Each jid gives (old id, new id); a row is re-keyed by lookup.

  Dry run (the default) prints COUNTS only, never an id or a jid, and changes nothing.
  --apply does it in ONE transaction: social_person.id, social_edge.src/dst, social_relation.pid, for this org only
  (works with or without a tenant column). It refuses and changes nothing when any id is neither old nor new (the
  channel walk didn't reach that person: raise --msgs) or a moved row would land on a key that already exists.
  A second run finds nothing to move and changes nothing.
  The people store's files (<people dir>/*.jsonl: the owner's asks and answers, a `pid` per line) move with the tables:
  their ids count toward the same refusal, and they are rewritten only AFTER the transaction commits, each one atomically
  (temp + rename) beside a .bak of what it held. A file that fails to write is named loudly (exit 1); its .bak stays.

Derived copies are not touched here: rebuild the graph afterwards (venv/bin/python src/astryx/memory/social_age.py).

Run: venv/bin/python src/astryx/people/people_rekey.py [--apply] [--msgs N]
Exit: 0 done or nothing to do · 1 refused, nothing changed · 77 the channel or the database is unreachable.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx import config, paths  # noqa: E402
from astryx.people import people  # noqa: E402

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

_ID = re.compile(r"^(p[0-9a-f]{14}|g[0-9a-f]{12})$")
# (table, column) pairs that hold a social_person.id; each table's rows are scoped by its org column
KEYED = (("social_person", "id"), ("social_edge", "src"), ("social_edge", "dst"), ("social_relation", "pid"))


def ids(salt: str, jid: str) -> str:
    """people.pid() for a person, scan()'s gid for a group, under an explicit salt."""
    h = hashlib.sha256((salt + "|" + jid).encode()).hexdigest()
    return "g" + h[:12] if jid.endswith("@g.us") else "p" + h[:14]


def old_salt(env: dict, environ: dict | None = None) -> str:
    """The salt _salt() returned before the fix: an environment value first (unchanged by the fix), then whichever of
    PEOPLE_SALT / ASTRYX_ORG the .env names FIRST."""
    for k in ("PEOPLE_SALT", "ASTRYX_ORG"):
        v = config.org_env(k, environ=environ)
        if v:
            return v
    salt, org = env.get("PEOPLE_SALT"), env.get("ASTRYX_ORG")
    if salt is not None and org is not None:
        return salt if list(env).index("PEOPLE_SALT") < list(env).index("ASTRYX_ORG") else org
    if salt is not None or org is not None:
        return salt if salt is not None else org
    return "astryx-unsalted"


def channel_jids(msgs: int) -> set[str] | None:
    """Every jid the sweep could have hashed: each chat, and each sender in each group's last `msgs` messages."""
    chats = people._wa("chats", "list", "--limit", "100000")
    if chats is None:
        return None
    if isinstance(chats, dict):
        chats = chats.get("chats") or chats.get("items") or []
    out = {str(c.get("jid")) for c in chats if c.get("jid")}
    for gj in [j for j in out if j.endswith("@g.us")]:
        ms = people._wa("messages", "list", "--chat", gj, "--limit", str(msgs))
        if isinstance(ms, dict):
            ms = ms.get("messages") or ms.get("items") or []
        out |= {m["SenderJID"] for m in ms or [] if m.get("SenderJID")}
    return out


def people_dir() -> Path:
    """Where the observatory keeps the people store's files (its _PEOPLE_DIR)."""
    return Path(os.environ.get("ASTRYX_PEOPLE_DIR") or paths.estate(people.__file__) / "homes" / "memory" / ".people")


def file_ids(d: Path | None) -> dict[Path, list]:
    """Each *.jsonl's lines, parsed (None for a line that isn't a JSON object, kept verbatim)."""
    out = {}
    for f in sorted(d.glob("*.jsonl")) if d and d.is_dir() else []:
        lines = []
        for raw in f.read_text().splitlines():
            try:
                o = json.loads(raw)
            except ValueError:
                o = None
            lines.append((raw, o if isinstance(o, dict) else None))
        out[f] = lines
    return out


def plan(cur, org: str, old: str, new: str, jids, files: dict | None = None) -> dict:
    """Counts, and the old → new map for the ids this org's rows (and the people files) actually hold."""
    pairs = {ids(old, j): ids(new, j) for j in jids}
    news = set(pairs.values())
    held = set()
    rows = {}
    for t, c in KEYED:
        cur.execute(f"SELECT {c} FROM {t} WHERE org = %s", (org,))
        vals = [r[0] for r in cur.fetchall()]
        rows[f"{t}.{c}"] = len(vals)
        held |= {v for v in vals if _ID.match(v)}
    for f, lines in (files or {}).items():
        vals = [o.get("pid") for _, o in lines if o and isinstance(o.get("pid"), str)]
        rows[f"file {f.name}"] = len(vals)
        held |= {v for v in vals if _ID.match(v)}
    move = {i: pairs[i] for i in held if i in pairs and pairs[i] != i}
    already = {i for i in held if i in news and i not in move}
    unmapped = held - set(move) - already
    clash = 0
    for t, key in (("social_person", "id"), ("social_relation", "pid")):
        cur.execute(f"SELECT {key} FROM {t} WHERE org = %s", (org,))
        have = {r[0] for r in cur.fetchall()}
        clash += sum(1 for o, n in move.items() if o in have and n in have)
    cur.execute("SELECT src, dst, rel FROM social_edge WHERE org = %s", (org,))
    edges = cur.fetchall()
    have = set(edges)
    clash += sum(1 for s, d, r in edges if (s in move or d in move)
                 and (move.get(s, s), move.get(d, d), r) in have)
    return {"jids": len(set(jids)), "rows": rows, "ids_held": len(held), "to_move": len(move),
            "already_new": len(already), "unmapped": len(unmapped), "clashes": clash, "map": move}


def apply(conn, org: str, p: dict) -> dict:
    """Re-key in ONE transaction; any count that doesn't hold afterwards rolls it all back."""
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("CREATE TEMP TABLE _rekey (old text PRIMARY KEY, new text NOT NULL) ON COMMIT DROP")
        cur.executemany("INSERT INTO _rekey VALUES (%s, %s)", list(p["map"].items()))
        moved = 0
        for t, c in KEYED:
            cur.execute(f"UPDATE {t} x SET {c} = m.new FROM _rekey m WHERE x.org = %s AND x.{c} = m.old", (org,))
            moved += cur.rowcount
        after = {}
        for t, c in KEYED:
            cur.execute(f"SELECT count(*), count(*) FILTER (WHERE {c} IN (SELECT old FROM _rekey)) "
                        f"FROM {t} WHERE org = %s", (org,))
            n, left = cur.fetchone()
            after[f"{t}.{c}"] = n
            if left:
                raise RuntimeError(f"{t}.{c}: {left} old id(s) still present after the update")
        if after != {k: v for k, v in p["rows"].items() if not k.startswith("file ")}:
            raise RuntimeError("row counts changed during the re-key")
    return {"rows_updated": moved, "rows": after}


def apply_files(files: dict, move: dict) -> tuple[int, list[str]]:
    """After the commit: rewrite each file whose pids move, atomically, beside a .bak. Returns (lines moved, failures)."""
    n, failed = 0, []
    for f, lines in files.items():
        out, k = [], 0
        for raw, o in lines:
            if o and o.get("pid") in move:
                o = dict(o, pid=move[o["pid"]])
                raw, k = json.dumps(o, ensure_ascii=False), k + 1
            out.append(raw)
        if not k:
            continue
        tmp = f.with_name(f".{f.name}.rekey-tmp")
        try:
            shutil.copy2(f, f.with_name(f.name + ".bak"))
            tmp.write_text("\n".join(out) + "\n")
            os.replace(tmp, f)
            n += k
        except OSError as e:
            failed.append(f"{f.name}: {type(e).__name__}")
            tmp.unlink(missing_ok=True)
    return n, failed


def report(p: dict) -> str:
    """Counts only: never an id, never a jid."""
    rows = ", ".join(f"{k} {v}" for k, v in p["rows"].items())
    return (f"channel ids walked: {p['jids']}\nrows: {rows}\ndistinct ids held: {p['ids_held']}: "
            f"to move {p['to_move']}, already new {p['already_new']}, unmapped {p['unmapped']}; "
            f"key clashes {p['clashes']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="re-key, in one transaction (default: dry run, counts only)")
    ap.add_argument("--msgs", type=int, default=5000, help="messages read per group to find its senders")
    a = ap.parse_args(argv)
    old = old_salt(config.read_env(paths.estate(people.__file__) / ".env"))
    new = people._salt()
    if old == new:
        print("old and new salt are the same here: nothing to re-key")
        return 0
    dsn = people._dsn()
    jids = channel_jids(a.msgs)
    if not dsn or jids is None:
        print("UNVERIFIED: " + ("no database DSN" if not dsn else "whatsapp channel unreachable") + "; nothing changed")
        return 77
    import psycopg
    org = people._org()
    files = file_ids(people_dir())
    with psycopg.connect(dsn) as conn:
        p = plan(conn.cursor(), org, old, new, jids, files)
        conn.rollback()
        print(report(p))
        if p["unmapped"] or p["clashes"]:
            print("REFUSED: " + (f"{p['unmapped']} id(s) match no channel id under either salt (raise --msgs)"
                                 if p["unmapped"] else f"{p['clashes']} moved row(s) would land on an existing key")
                  + "; nothing changed")
            return 1
        if not p["to_move"]:
            print("nothing to move")
            return 0
        if not a.apply:
            print("dry run: nothing changed (--apply to re-key)")
            return 0
        r = apply(conn, org, p)
        print(f"re-keyed: {r['rows_updated']} row value(s) in one transaction; row counts unchanged. "
              "Rebuild the graph: venv/bin/python src/astryx/memory/social_age.py")
    n, failed = apply_files(files, p["map"])                    # only now: the transaction above has committed
    print(f"people files: {n} line(s) re-keyed (each rewritten file keeps a .bak beside it)")
    if failed:
        print(f"FILE WRITE FAILED: {'; '.join(failed)}. The database IS re-keyed; these files are untouched and still hold the OLD ids "
              "(any .bak written holds the same). Fix the cause and rerun: the tables are a no-op now, the files move.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
