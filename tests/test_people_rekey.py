#!/usr/bin/env python3
"""Oracle: src/astryx/people/people_rekey.py on a fixture database (schema.sql applied whole).

Seeds rows the way the sweep wrote them under the OLD salt (the public org name the .env named first), then:
  S1  old_salt() is the pre-fix rule (file order), _salt() the fixed one, and ids() is people.pid() byte for byte.
  D1  the dry run's plan counts every id to move and changes nothing; its report holds no id and no jid.
  A1  --apply re-keys social_person, social_edge (src and dst) and social_relation to the NEW ids, row counts unchanged,
      another org's rows untouched.
  I1  a second run moves nothing and changes nothing.
  R1  an id no channel jid explains → refused, nothing changed.  R2  a move onto an existing key → refused.
  T1  the same re-key with a tenant column leading the keys.
Needs a reachable DSN that can CREATE DATABASE (sqlguard fixture), else 77.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import psycopg
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
except Exception as e:                                              # noqa: BLE001
    print(f"SKIP: {type(e).__name__}: {e}")
    sys.exit(77)
from astryx.people import people  # noqa: E402
from astryx.people import people_rekey as R  # noqa: E402

fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


OLD, NEW, ORG = "fixture-org", "fixture-secret-salt", "fixture-org"
P1, P2, P3 = "111@s.whatsapp.net", "222@s.whatsapp.net", "333@s.whatsapp.net"
G1 = "999-1@g.us"
JIDS = {P1, P2, P3, G1}

# S1: the two rules and the hash
env = {"ASTRYX_ORG": OLD, "PEOPLE_SALT": NEW}                       # ASTRYX_ORG named first: the bug's layout
want("S1 old_salt() follows the old file-order rule (ASTRYX_ORG first → the org name)", R.old_salt(env, environ={}) == OLD)
want("S1 ...and a PEOPLE_SALT named first was the salt then too",
     R.old_salt({"PEOPLE_SALT": NEW, "ASTRYX_ORG": OLD}, environ={}) == NEW)
saved = {k: os.environ.pop(k, None) for k in ("PEOPLE_SALT", "ASTRYX_ORG")}
os.environ["PEOPLE_SALT"] = NEW
want("S1 ids() is people.pid() byte for byte", R.ids(NEW, P1) == people.pid(P1))
for k, v in saved.items():
    os.environ.pop(k, None)
    if v is not None:
        os.environ[k] = v


def seed(cur, org, salt):
    o = lambda j: R.ids(salt, j)                                    # noqa: E731
    for j in (P1, P2, P3):
        cur.execute("INSERT INTO social_person (org, id, label) VALUES (%s, %s, 'someone')", (org, o(j)))
    cur.execute("INSERT INTO social_person (org, id, kind, label) VALUES (%s, %s, 'group', 'a group')", (org, o(G1)))
    for j in (P1, P2):
        cur.execute("INSERT INTO social_edge (org, src, dst, rel) VALUES (%s, %s, %s, 'member-of')", (org, o(j), o(G1)))
    cur.execute("INSERT INTO social_edge (org, src, dst, rel) VALUES (%s, 'owner', %s, 'dm')", (org, o(P3)))
    for j in (P1, P3):
        cur.execute("INSERT INTO social_relation (org, pid, kind) VALUES (%s, %s, 'friend')", (org, o(j)))


def snap(cur):
    out = []
    for t, c in R.KEYED:
        cur.execute(f"SELECT org, {c} FROM {t} ORDER BY 1, 2")
        out.append((t, c, cur.fetchall()))
    return out


def keyset(cur, org):
    return {(t, c): sorted(v for o, v in rows if o == org) for t, c, rows in snap(cur)}


def expect(salt):
    o = lambda j: R.ids(salt, j)                                    # noqa: E731
    return {("social_person", "id"): sorted(o(j) for j in JIDS),
            ("social_edge", "src"): sorted([o(P1), o(P2), "owner"]),
            ("social_edge", "dst"): sorted([o(G1), o(G1), o(P3)]),
            ("social_relation", "pid"): sorted([o(P1), o(P3)])}


def run(conn, label, tenant=False):
    cur = conn.cursor()
    p = R.plan(cur, ORG, OLD, NEW, JIDS)
    want(f"{label} D1 the plan finds every held id to move (4) and none unmapped",
         p["to_move"] == 4 and p["unmapped"] == 0 and p["clashes"] == 0, str({k: v for k, v in p.items() if k != "map"}))
    before = snap(cur)
    text = R.report(p)
    leaks = [x for x in list(p["map"]) + list(p["map"].values()) + [j.split("@")[0] for j in JIDS] if x in text]
    want(f"{label} D1 the report names no id and no jid", not leaks, f"{len(leaks)} leaked")
    want(f"{label} D1 planning changed nothing", snap(cur) == before)
    r = R.apply(conn, ORG, p)
    want(f"{label} A1 every keyed column now holds the NEW ids", keyset(cur, ORG) == expect(NEW))
    want(f"{label} A1 row counts unchanged", r["rows"] == p["rows"], f"{r['rows']} vs {p['rows']}")
    want(f"{label} A1 another org's rows untouched", keyset(cur, "other-org") == expect(OLD))
    after = snap(cur)
    p2 = R.plan(cur, ORG, OLD, NEW, JIDS)
    want(f"{label} I1 a second run finds nothing to move", p2["to_move"] == 0 and p2["already_new"] == 4
         and p2["unmapped"] == 0, str({k: v for k, v in p2.items() if k != "map"}))
    R.apply(conn, ORG, p2)
    want(f"{label} I1 ...and applying it changes nothing", snap(cur) == after)


try:
    with fixture_db() as fx:
        with psycopg.connect(fx["dsn"], autocommit=True) as conn:
            cur = conn.cursor()
            seed(cur, ORG, OLD)
            seed(cur, "other-org", OLD)
            run(conn, "plain")

            # R1: an id that no channel jid explains
            cur.execute("DELETE FROM social_edge; DELETE FROM social_relation; DELETE FROM social_person")
            seed(cur, ORG, OLD)
            cur.execute("INSERT INTO social_person (org, id) VALUES (%s, %s)", (ORG, R.ids(OLD, "444@s.whatsapp.net")))
            before = snap(cur)
            p = R.plan(cur, ORG, OLD, NEW, JIDS)
            want("R1 an id no channel jid explains is counted unmapped", p["unmapped"] == 1)
            R.channel_jids = lambda msgs: JIDS                     # main()'s seams: this fixture, these salts
            R.old_salt = lambda env, environ=None: OLD
            people._salt, people._org, people._dsn = (lambda: NEW), (lambda: ORG), (lambda: fx["dsn"])
            rc = R.main(["--apply"])
            want("R1 main(--apply) refuses it (exit 1) and changes nothing", rc == 1 and snap(cur) == before, f"rc={rc}")

            # R2: the new id already exists beside the old one (a post-fix sweep ran first and kept old details)
            cur.execute("DELETE FROM social_person WHERE id = %s", (R.ids(OLD, "444@s.whatsapp.net"),))
            cur.execute("INSERT INTO social_relation (org, pid, kind) VALUES (%s, %s, 'colleague')", (ORG, R.ids(NEW, P1)))
            want("R2 a move onto an existing key is a clash", R.plan(cur, ORG, OLD, NEW, JIDS)["clashes"] >= 1)

            # T1: the tenant column leading every key
            cur.execute("DELETE FROM social_edge; DELETE FROM social_relation; DELETE FROM social_person")
            for t, pk in (("social_person", "org, id"), ("social_edge", "org, src, dst, rel"),
                          ("social_relation", "org, pid")):
                cur.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS tenant text NOT NULL DEFAULT 't1'")
                cur.execute(f"ALTER TABLE {t} DROP CONSTRAINT {t}_pkey")
                cur.execute(f"ALTER TABLE {t} ADD PRIMARY KEY (tenant, {pk})")
            seed(cur, ORG, OLD)
            seed(cur, "other-org", OLD)
            run(conn, "tenant")
except FixtureUnavailable as e:
    print(f"SKIP: {e}")
    sys.exit(77)

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
