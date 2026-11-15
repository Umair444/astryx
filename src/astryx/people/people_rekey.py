#!/usr/bin/env python
"""astryx · people_rekey — move people ids hashed under a salt _salt() no longer picks onto the one it picks now.

An id is `p`+sha256(salt|jid)[:14] (groups `g`+…[:12]). Two changes moved the salt under existing rows:
  - single-org: _salt() used to return whichever of PEOPLE_SALT / ASTRYX_ORG the .env named FIRST, so an ASTRYX_ORG line
    above PEOPLE_SALT hashed with the public org name; the salt-order fix made PEOPLE_SALT win;
  - multi-org (cog) hosts: the split began earlier, when people.py started reading the salt through config.org_env.
The nightly sweep rewrites social_person/social_edge under the current salt, but social_relation (the details) and the
people store's files are never rebuilt, so their rows keyed by a superseded id match nobody.

So ids are ATTRIBUTED, not derived from a rule: each held id is classified by which candidate salt explains it (the
.env's PEOPLE_SALT, its ASTRYX_ORG, the last-resort unsalted value), and anything a non-current candidate explains is
re-keyed to the id the current _salt() gives the same jid. The jid is never stored, so the map is rebuilt from the
channel: every chat, and every sender in every group's messages (`--msgs` deep).

  Dry run (the default) prints COUNTS only (never an id, jid or salt) and changes nothing.
  --apply does it in ONE transaction, for this org only, with or without a tenant column:
    social_person.id   moved; an old row whose new twin already exists is a duplicate the sweep re-made: dropped
    social_edge        src/dst moved; an old edge whose (src, dst, rel) twin already exists is a duplicate: dropped
    social_relation    moved; where BOTH old and new ids hold details it is a clash: reported by count and kind
                       (same / different / one side empty) and left untouched under its old id. How to merge two
                       sets of the owner's details is not this tool's call.
  It refuses, changing nothing, only when a held id matches no channel jid under any candidate (raise --msgs), or when
  two superseded ids collapse onto one new id. A second run moves nothing.
  The people store's files (<people dir>/*.jsonl, a `pid` per line) move with the tables: their ids count toward the
  same refusal, and they are rewritten only AFTER the transaction commits, each atomically (temp + rename) beside a .bak.
  A file that fails to write is named loudly (exit 1) and a rerun moves only the files.

Derived copies are not touched here: rebuild the graph afterwards (venv/bin/python src/astryx/memory/social_age.py).

Run: venv/bin/python src/astryx/people/people_rekey.py [--apply] [--msgs N]
Exit: 0 done or nothing to do · 1 refused or a file write failed · 77 the channel or the database is unreachable.
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
UNSALTED = "astryx-unsalted"        # people._salt()'s last resort


def ids(salt: str, jid: str) -> str:
    """people.pid() for a person, scan()'s gid for a group, under an explicit salt."""
    h = hashlib.sha256((salt + "|" + jid).encode()).hexdigest()
    return "g" + h[:12] if jid.endswith("@g.us") else "p" + h[:14]


def env_path() -> Path:
    return paths.estate(people.__file__) / ".env"


def candidates(env: dict) -> dict[str, str]:
    """Every salt this org's ids could have been hashed under, read from its .env FILE only (never the environment
    routing _salt() itself uses: on a multi-org host that routing is the post-change answer, so deriving the old salt
    through it returns the new one)."""
    out = {}
    for k in ("PEOPLE_SALT", "ASTRYX_ORG"):
        v = (env.get(k) or "").strip()
        if v:
            out[k] = v
    out["unsalted"] = UNSALTED
    return out


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


def plan(cur, org: str, cands: dict, target: str, jids, files: dict | None = None) -> dict:
    """Attribution counts per keyed column and file, the old → new map, and the row operations --apply would do."""
    jids = set(jids)
    explains = {label: {ids(salt, j): j for j in jids} for label, salt in cands.items()}
    cur_ids = {ids(target, j) for j in jids}
    pairs = {}
    for label, salt in cands.items():
        if salt != target:
            for i, j in explains[label].items():
                if i not in cur_ids:
                    pairs.setdefault(i, ids(target, j))
    held_by = {}
    for t, c in KEYED:
        cur.execute(f"SELECT {c} FROM {t} WHERE org = %s", (org,))
        held_by[f"{t}.{c}"] = [r[0] for r in cur.fetchall()]
    for f, lines in (files or {}).items():
        held_by[f"file {f.name}"] = [o.get("pid") for _, o in lines if o and isinstance(o.get("pid"), str)]
    attribution, held = {}, set()
    for k, vals in held_by.items():
        h = {v for v in vals if _ID.match(v)}
        held |= h
        a = {"rows": len(vals), "ids": len(h), "current": len(h & cur_ids)}
        for label in cands:
            if cands[label] != target:
                a[label] = len(h & set(explains[label]) - cur_ids)
        a["none"] = len(h - cur_ids - set(pairs))
        attribution[k] = a
    move = {i: pairs[i] for i in held if i in pairs}
    unmapped = held - cur_ids - set(move)
    collapse = len(move) - len(set(move.values()))              # two superseded ids onto one new id

    persons = set(held_by["social_person.id"])
    ops = {"person_update": 0, "person_drop": 0, "edge_update": 0, "edge_drop": 0,
           "relation_update": 0, "relation_kept_same": 0, "relation_kept_different": 0, "relation_kept_one_empty": 0,
           "file_lines": 0}
    for i in held_by["social_person.id"]:
        if i in move:
            ops["person_drop" if move[i] in persons else "person_update"] += 1
    cur.execute("SELECT src, dst, rel FROM social_edge WHERE org = %s", (org,))
    edges = cur.fetchall()
    have = set(edges)
    for s, d, r in edges:
        if s in move or d in move:
            ops["edge_drop" if (move.get(s, s), move.get(d, d), r) in have else "edge_update"] += 1
    cur.execute("SELECT pid, kind FROM social_relation WHERE org = %s", (org,))
    rel = dict(cur.fetchall())
    for i, kind in rel.items():
        if i in move:
            if move[i] not in rel:
                ops["relation_update"] += 1
            else:
                k2 = rel[move[i]]
                ops["relation_kept_one_empty" if not kind or not k2 else
                    "relation_kept_same" if kind == k2 else "relation_kept_different"] += 1
    for f, lines in (files or {}).items():
        ops["file_lines"] += sum(1 for _, o in lines if o and o.get("pid") in move)
    kept = ops["relation_kept_same"] + ops["relation_kept_different"] + ops["relation_kept_one_empty"]
    work = sum(v for k, v in ops.items() if not k.startswith("relation_kept"))
    return {"jids": len(jids), "attribution": attribution, "unmapped": len(unmapped), "collapse": collapse,
            "ops": ops, "kept": kept, "work": work, "map": move,
            "rows": {k: len(v) for k, v in held_by.items() if not k.startswith("file ")}}


def apply(conn, org: str, p: dict) -> dict:
    """Re-key in ONE transaction; any count that doesn't match the plan afterwards rolls it all back."""
    o = p["ops"]
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("CREATE TEMP TABLE _rekey (old text PRIMARY KEY, new text NOT NULL) ON COMMIT DROP")
        cur.executemany("INSERT INTO _rekey VALUES (%s, %s)", list(p["map"].items()))
        cur.execute("DELETE FROM social_person x USING _rekey m WHERE x.org = %s AND x.id = m.old AND EXISTS "
                    "(SELECT 1 FROM social_person y WHERE y.org = x.org AND y.id = m.new)", (org,))
        dropped_p = cur.rowcount
        cur.execute("UPDATE social_person x SET id = m.new FROM _rekey m WHERE x.org = %s AND x.id = m.old", (org,))
        moved_p = cur.rowcount
        new_of = "COALESCE((SELECT new FROM _rekey WHERE old = e.{c}), e.{c})"
        touches = "(e.src IN (SELECT old FROM _rekey) OR e.dst IN (SELECT old FROM _rekey))"
        cur.execute(f"DELETE FROM social_edge e WHERE e.org = %s AND {touches} AND EXISTS (SELECT 1 FROM social_edge t "
                    f"WHERE t.org = e.org AND t.rel = e.rel AND t.src = {new_of.format(c='src')} "
                    f"AND t.dst = {new_of.format(c='dst')})", (org,))
        dropped_e = cur.rowcount
        cur.execute(f"UPDATE social_edge e SET src = {new_of.format(c='src')}, dst = {new_of.format(c='dst')} "
                    f"WHERE e.org = %s AND {touches}", (org,))
        moved_e = cur.rowcount
        cur.execute("UPDATE social_relation x SET pid = m.new FROM _rekey m WHERE x.org = %s AND x.pid = m.old AND "
                    "NOT EXISTS (SELECT 1 FROM social_relation y WHERE y.org = x.org AND y.pid = m.new)", (org,))
        moved_r = cur.rowcount
        got = (dropped_p, moved_p, dropped_e, moved_e, moved_r)
        want = (o["person_drop"], o["person_update"], o["edge_drop"], o["edge_update"], o["relation_update"])
        if got != want:
            raise RuntimeError(f"the re-key did {got}, the plan said {want} (drop/move person, drop/move edge, "
                               "move relation): rolled back")
        left = {}
        for t, c in KEYED:
            cur.execute(f"SELECT count(*) FILTER (WHERE {c} IN (SELECT old FROM _rekey)), count(*) "
                        f"FROM {t} WHERE org = %s", (org,))
            left[f"{t}.{c}"] = cur.fetchone()
        if any(n for k, (n, _) in left.items() if k != "social_relation.pid") or \
                left["social_relation.pid"][0] != p["kept"]:
            raise RuntimeError("superseded ids remain beyond the reported relation clashes: rolled back")
        rows = {k: total for k, (_, total) in left.items()}
    return {"rows_updated": moved_p + moved_e + moved_r, "rows_dropped": dropped_p + dropped_e, "rows": rows}


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
    """Counts only: never an id, a jid or a salt."""
    lines = [f"channel ids walked: {p['jids']}"]
    for k, a in p["attribution"].items():
        lines.append(f"{k}: " + ", ".join(f"{n} {v}" for n, v in a.items()))
    o = p["ops"]
    lines.append("would: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in o.items()))
    lines.append(f"unmapped {p['unmapped']}, collapsed {p['collapse']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="re-key, in one transaction (default: dry run, counts only)")
    ap.add_argument("--msgs", type=int, default=5000, help="messages read per group to find its senders")
    a = ap.parse_args(argv)
    cands, target = candidates(config.read_env(env_path())), people._salt()
    dsn = people._dsn()
    jids = channel_jids(a.msgs)
    if not dsn or jids is None:
        print("UNVERIFIED: " + ("no database DSN" if not dsn else "whatsapp channel unreachable") + "; nothing changed")
        return 77
    import psycopg
    org = people._org()
    files = file_ids(people_dir())
    with psycopg.connect(dsn) as conn:
        p = plan(conn.cursor(), org, cands, target, jids, files)
        conn.rollback()
        print(report(p))
        if p["unmapped"] or p["collapse"]:
            print("REFUSED: " + (f"{p['unmapped']} held id(s) match no channel id under any candidate salt (raise --msgs)"
                                 if p["unmapped"] else f"{p['collapse']} superseded id(s) collapse onto one new id")
                  + "; nothing changed")
            return 1
        if p["kept"]:
            print(f"{p['kept']} relation clash(es) (old and new id both hold details) are KEPT untouched under the old id: "
                  "merging the owner's two sets of details is not this tool's call")
        if not p["work"]:
            print("nothing to move")
            return 0
        if not a.apply:
            print("dry run: nothing changed (--apply to re-key)")
            return 0
        r = apply(conn, org, p)
        print(f"re-keyed: {r['rows_updated']} row(s) moved, {r['rows_dropped']} duplicate row(s) dropped, in one "
              "transaction. Rebuild the graph: venv/bin/python src/astryx/memory/social_age.py")
    n, failed = apply_files(files, p["map"])                    # only now: the transaction above has committed
    print(f"people files: {n} line(s) re-keyed (each rewritten file keeps a .bak beside it)")
    if failed:
        print(f"FILE WRITE FAILED: {'; '.join(failed)}. The database IS re-keyed; these files are untouched and still hold "
              "the OLD ids (any .bak written holds the same). Fix the cause and rerun: the tables are a no-op now, "
              "the files move.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
