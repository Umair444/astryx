#!/usr/bin/env python3
"""Oracle: src/astryx/people/people_rekey.py on a fixture database (schema.sql applied whole).

Seeds rows the way the sweep wrote them under a SUPERSEDED salt (the public org name), then:
  S1  candidates() reads the .env FILE only (an environment value never stands in for it); ids() is people.pid().
  M1  the multi-org false green: with _salt() routed the way a multi-org host routes it (org_env → the HOME's .env,
      so PEOPLE_SALT), main() still finds the org-name rows and moves them. RED control: the pre-fix derivation run
      through that same routing returns the NEW salt, i.e. "nothing to re-key".
  D1  the dry run counts by attribution and changes nothing; its report holds no id, no jid and no salt.
  A1  --apply moves social_person, social_edge (src, dst) and social_relation to the new ids, another org untouched.
  I1  a second run moves nothing and changes nothing.
  C1  clashes don't stop the run: an old person or edge whose new twin exists is dropped as the duplicate it is; a
      relation clash is counted by kind (same / different / one side empty) and KEPT untouched under its old id.
  R1  an id no channel jid explains → refused (exit 1), nothing changed.
  T1  D1/A1/I1 again with a tenant column leading the keys.
  F*  the people store's *.jsonl move with the tables, through main(): dry run touches nothing; a failed transaction
      leaves them alone; --apply rewrites them atomically after the commit beside a .bak; a rerun changes nothing; an
      unexplained file id refuses everything; a failed file write is loud (exit 1) and a rerun moves only the files.
Needs a reachable DSN that can CREATE DATABASE (sqlguard fixture), else 77.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import psycopg
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
except Exception as e:                                              # noqa: BLE001
    print(f"SKIP: {type(e).__name__}: {e}")
    sys.exit(77)
from astryx import config  # noqa: E402
from astryx.people import people  # noqa: E402
from astryx.people import people_rekey as R  # noqa: E402

fails = []
TMP = Path(tempfile.mkdtemp(prefix="rekey-"))
PDIR = TMP / "people"
PDIR.mkdir()
os.environ["ASTRYX_PEOPLE_DIR"] = str(PDIR)                         # never the estate's real people store
ENV = TMP / ".env"                                                  # never the estate's real .env


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


OLD, NEW, ORG = "fixture-org", "fixture-secret-salt", "fixture-org"
CANDS = {"PEOPLE_SALT": NEW, "ASTRYX_ORG": OLD, "unsalted": R.UNSALTED}
P1, P2, P3 = "111@s.whatsapp.net", "222@s.whatsapp.net", "333@s.whatsapp.net"
G1 = "999-1@g.us"
JIDS = {P1, P2, P3, G1}
ENV.write_text(f"ASTRYX_ORG={OLD}\nPEOPLE_SALT={NEW}\n")            # ASTRYX_ORG named first: the bug's layout

# S1: the candidates and the hash
saved = {k: os.environ.pop(k, None) for k in ("PEOPLE_SALT", "ASTRYX_ORG")}
os.environ["PEOPLE_SALT"] = "an-environment-value"
want("S1 candidates() reads the .env FILE only (the environment never stands in for it)",
     R.candidates(config.read_env(ENV)) == CANDS)
os.environ["PEOPLE_SALT"] = NEW
want("S1 ids() is people.pid() byte for byte", R.ids(NEW, P1) == people.pid(P1))
for k, v in saved.items():
    os.environ.pop(k, None)
    if v is not None:
        os.environ[k] = v


def multi_org_env(key, default=None, path=None, environ=None):
    """config.org_env as a multi-org host answers it: the HOME's .env, never the environment."""
    v = config.read_env(ENV).get(key)
    return v if v else default


def seed(cur, org, salt, rel=(P1, P3)):
    o = lambda j: R.ids(salt, j)                                    # noqa: E731
    for j in (P1, P2, P3):
        cur.execute("INSERT INTO social_person (org, id, label) VALUES (%s, %s, 'someone')", (org, o(j)))
    cur.execute("INSERT INTO social_person (org, id, kind, label) VALUES (%s, %s, 'group', 'a group')", (org, o(G1)))
    for j in (P1, P2):
        cur.execute("INSERT INTO social_edge (org, src, dst, rel) VALUES (%s, %s, %s, 'member-of')", (org, o(j), o(G1)))
    cur.execute("INSERT INTO social_edge (org, src, dst, rel) VALUES (%s, 'owner', %s, 'dm')", (org, o(P3)))
    for j in rel:
        cur.execute("INSERT INTO social_relation (org, pid, kind) VALUES (%s, %s, 'friend')", (org, o(j)))


def wipe(cur):
    cur.execute("DELETE FROM social_edge; DELETE FROM social_relation; DELETE FROM social_person")


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


def files_bytes():
    return {f: f.read_bytes() for f in sorted(PDIR.glob("*.jsonl"))}


def run(conn, label):
    cur = conn.cursor()
    p = R.plan(cur, ORG, CANDS, NEW, JIDS)
    a = p["attribution"]
    want(f"{label} D1 attribution: every held id explained by ASTRYX_ORG, none current, none unexplained",
         a["social_person.id"] == {"rows": 4, "ids": 4, "current": 0, "ASTRYX_ORG": 4, "unsalted": 0, "none": 0}
         and a["social_relation.pid"]["ASTRYX_ORG"] == 2 and not p["unmapped"], str(a))
    want(f"{label} D1 the plan's operations: 4 person, 3 edge, 2 relation moves; no drops, nothing kept",
         p["ops"]["person_update"] == 4 and p["ops"]["edge_update"] == 3 and p["ops"]["relation_update"] == 2
         and p["ops"]["person_drop"] == p["ops"]["edge_drop"] == 0 and p["kept"] == 0, str(p["ops"]))
    before = snap(cur)
    text = R.report(p)
    leaks = [x for x in list(p["map"]) + list(p["map"].values()) + [j.split("@")[0] for j in JIDS] + [OLD, NEW]
             if x in text]
    want(f"{label} D1 the report names no id, no jid and no salt", not leaks, f"{len(leaks)} leaked")
    want(f"{label} D1 planning changed nothing", snap(cur) == before)
    r = R.apply(conn, ORG, p)
    want(f"{label} A1 every keyed column now holds the NEW ids", keyset(cur, ORG) == expect(NEW))
    want(f"{label} A1 row counts unchanged", r["rows"] == p["rows"], f"{r['rows']} vs {p['rows']}")
    want(f"{label} A1 another org's rows untouched", keyset(cur, "other-org") == expect(OLD))
    after = snap(cur)
    p2 = R.plan(cur, ORG, CANDS, NEW, JIDS)
    want(f"{label} I1 a second run finds nothing to do", p2["work"] == 0 and not p2["unmapped"]
         and p2["attribution"]["social_person.id"]["current"] == 4, str(p2["ops"]))
    R.apply(conn, ORG, p2)
    want(f"{label} I1 ...and applying it changes nothing", snap(cur) == after)


try:
    with fixture_db() as fx:
        with psycopg.connect(fx["dsn"], autocommit=True) as conn:
            cur = conn.cursor()
            seed(cur, ORG, OLD)
            seed(cur, "other-org", OLD)
            run(conn, "plain")

            # main()'s seams: this fixture's DSN and org, this .env, this channel. _salt() and candidates() run REAL.
            R.channel_jids = lambda msgs: JIDS
            R.env_path = lambda: ENV
            people._org, people._dsn = (lambda: ORG), (lambda: fx["dsn"])
            real_org_env = config.org_env
            config.org_env = multi_org_env

            # M1: the multi-org false green
            wipe(cur)
            seed(cur, ORG, OLD)

            def prefix_old_salt(env):                                # the shipped derivation #16 replaced
                for k in ("PEOPLE_SALT", "ASTRYX_ORG"):
                    v = config.org_env(k)
                    if v:
                        return v
                return env.get("PEOPLE_SALT") or env.get("ASTRYX_ORG")
            want("M1 control: the old derivation through multi-org routing answers the NEW salt (the false green)",
                 prefix_old_salt(config.read_env(ENV)) == NEW == people._salt())
            db0 = snap(cur)
            rc = R.main([])
            want("M1 under multi-org routing, main()'s dry run still sees the org-name rows (exit 0, nothing moved)",
                 rc == 0 and snap(cur) == db0, f"rc={rc}")
            rc = R.main(["--apply"])
            want("M1 ...and --apply moves them to the current salt", rc == 0 and keyset(cur, ORG) == expect(NEW), f"rc={rc}")

            # C1: clashes don't stop the run
            wipe(cur)
            seed(cur, ORG, OLD)
            seed(cur, ORG, NEW, rel=())                              # a post-change sweep ran: persons + edges re-made
            cur.execute("INSERT INTO social_relation (org, pid, kind) VALUES (%s, %s, 'friend')", (ORG, R.ids(NEW, P1)))
            cur.execute("INSERT INTO social_relation (org, pid, kind) VALUES (%s, %s, 'colleague')", (ORG, R.ids(NEW, P3)))
            p = R.plan(cur, ORG, CANDS, NEW, JIDS)
            o = p["ops"]
            want("C1 the plan: 4 duplicate persons and 3 duplicate edges to drop, 2 relation clashes kept (1 same, 1 "
                 "different kind)", o["person_drop"] == 4 and o["edge_drop"] == 3 and o["person_update"] == 0
                 and o["relation_kept_same"] == 1 and o["relation_kept_different"] == 1 and p["kept"] == 2, str(o))
            rc = R.main(["--apply"])
            k = keyset(cur, ORG)
            want("C1 --apply runs (exit 0): duplicates gone, persons and edges on the new ids only",
                 rc == 0 and k[("social_person", "id")] == expect(NEW)[("social_person", "id")]
                 and k[("social_edge", "src")] == expect(NEW)[("social_edge", "src")], f"rc={rc}")
            want("C1 ...both clashing relations kept untouched: the old rows under their old ids beside the new",
                 k[("social_relation", "pid")] == sorted([R.ids(OLD, P1), R.ids(OLD, P3), R.ids(NEW, P1), R.ids(NEW, P3)]))
            db1 = snap(cur)
            rc = R.main(["--apply"])
            want("C1 a rerun: nothing to do, the kept clashes still kept", rc == 0 and snap(cur) == db1, f"rc={rc}")

            # R1: an id that no channel jid explains
            wipe(cur)
            seed(cur, ORG, OLD)
            cur.execute("INSERT INTO social_person (org, id) VALUES (%s, %s)", (ORG, R.ids(OLD, "444@s.whatsapp.net")))
            before = snap(cur)
            rc = R.main(["--apply"])
            want("R1 an unexplained id: main(--apply) exits 1 and changes nothing", rc == 1 and snap(cur) == before,
                 f"rc={rc}")

            # F: the people store's files, end to end through main()
            wipe(cur)
            seed(cur, ORG, OLD)
            o_, n_ = (lambda j: R.ids(OLD, j)), (lambda j: R.ids(NEW, j))
            asks, answers = PDIR / "asks.jsonl", PDIR / "answers.jsonl"
            asks.write_text(json.dumps({"pid": o_(P1), "q": "who?"}) + "\nnot json at all\n"
                            + json.dumps({"pid": o_(P2), "q": "and?"}) + "\n" + json.dumps({"note": "no pid"}) + "\n")
            answers.write_text(json.dumps({"pid": o_(P1), "kind": "friend"}) + "\n")
            files0, db0 = files_bytes(), snap(cur)
            rc = R.main([])
            want("F-D1 dry run: exit 0, tables and files untouched", rc == 0 and snap(cur) == db0
                 and files_bytes() == files0, f"rc={rc}")
            real_apply = R.apply
            R.apply = lambda *a: (_ for _ in ()).throw(RuntimeError("simulated failed transaction"))
            try:
                R.main(["--apply"])
            except RuntimeError:
                pass
            R.apply = real_apply
            want("F-O1 a failed transaction leaves the files alone (they move only after the commit)",
                 files_bytes() == files0 and snap(cur) == db0)
            rc = R.main(["--apply"])
            la, ln = asks.read_text().splitlines(), answers.read_text().splitlines()
            want("F-A1 --apply: exit 0, the files hold the NEW ids", rc == 0 and json.loads(la[0])["pid"] == n_(P1)
                 and json.loads(la[2])["pid"] == n_(P2) and json.loads(ln[0])["pid"] == n_(P1), f"rc={rc}")
            want("F-A1 ...every other line byte for byte, the same line count",
                 la[1] == "not json at all" and la[3] == json.dumps({"note": "no pid"}) and len(la) == 4 and len(ln) == 1)
            want("F-A1 ...a .bak beside each holds what it held, no temp file left",
                 all(f.with_name(f.name + ".bak").read_bytes() == b for f, b in files0.items())
                 and not list(PDIR.glob(".*rekey-tmp")))
            files1, db1 = files_bytes(), snap(cur)
            rc = R.main(["--apply"])
            want("F-I1 a second --apply: exit 0, tables and files unchanged", rc == 0 and snap(cur) == db1
                 and files_bytes() == files1, f"rc={rc}")
            wipe(cur)
            seed(cur, ORG, OLD)
            for f, b in files0.items():
                f.write_bytes(b)
            with asks.open("a") as fh:
                fh.write(json.dumps({"pid": R.ids(OLD, "555@s.whatsapp.net")}) + "\n")
            files2, db2 = files_bytes(), snap(cur)
            rc = R.main(["--apply"])
            want("F-R1 an unexplained file id: exit 1, tables and files unchanged", rc == 1 and snap(cur) == db2
                 and files_bytes() == files2, f"rc={rc}")
            asks.write_bytes(files0[asks])
            PDIR.chmod(0o555)
            try:
                rc = R.main(["--apply"])
            finally:
                PDIR.chmod(0o755)
            want("F-W1 a failed file write: exit 1, the file unchanged, the tables re-keyed", rc == 1
                 and asks.read_bytes() == files0[asks] and keyset(cur, ORG) == expect(NEW), f"rc={rc}")
            rc = R.main(["--apply"])
            want("F-W1 ...a rerun once it's writable moves the files (the tables are a no-op)", rc == 0
                 and json.loads(asks.read_text().splitlines()[0])["pid"] == n_(P1), f"rc={rc}")
            for f in list(PDIR.iterdir()):
                f.unlink()
            config.org_env = real_org_env

            # T1: the tenant column leading every key
            wipe(cur)
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
