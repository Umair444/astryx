#!/usr/bin/env python3
"""Oracle for the people library's privilege boundary, build 1a (memory #35896, seed #35894/#36018).

GRADE: ACCIDENT-GRADE. This proves what a role can't reach. It does NOT prove a resident can't read the details:
every resident runs as the same OS user, and the superuser credential is in .env and ~/.pgpass, readable by all of
them. A resident that connects as the superuser reads social_relation regardless of every GRANT here. What is
proven is that the TOOL paths and the resident ROLE can't, so a read needs a deliberate credential grab (detection
grade, by org-form + steward). Prevention-grade is owner infrastructure (a separate OS user, or a credential broker).

Arms, on SCRATCH roles and SCRATCH databases only (it never changes, and never depends on, a live role):
  RED      the role residents use TODAY (ASTRYX_DSN's) is a superuser: it reads every detail. A NOSUPERUSER resident
           given the obvious network grant (table-level SELECT on social_person) reads them too.
  GREEN    after people_gate + people_move, the scratch resident is refused SELECT on social_relation, refused the
           detail columns of social_person, and refused CONNECT to the private database, each with the error text
           predicted here; PUBLIC holds nothing on social_relation; people_gate.drift() is empty.
  CONTROL  a scratch member of the scratch cleared role reads social_relation (values intact) and walks the private
           graph; the scratch resident still reads social_person's network columns, social_edge, and walks the
           network graph, whose nodes carry no detail.
  MOVE     the receipt: digest == digest_after, left == 0, a re-run moves nothing.
  CUTOVER  people.write_pg never writes a detail and never erases social_relation; persona.apply_pg / load_pg round-
           trip through social_relation.

Needs a role that can CREATE DATABASE and CREATE ROLE, with AGE on the server, else SKIP 77 (branch_check's run role
can't create roles: there this verifies nothing, and says so). Debris of a killed run is reaped by pid at start.
"""
import os
import re
import secrets
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
EXIT_SKIP = 77


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(EXIT_SKIP)


try:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — needs the org runtime")

from nucleus.sqlguard.fixture import FixtureUnavailable, fixture_db, live_dsn  # noqa: E402

PID = os.getpid()
NAME = re.compile(r"^astryx_pgate_(\d+)_(res|clr|mem|inr|inc|priv|net)$")
RES, CLR, MEM = (f"astryx_pgate_{PID}_{s}" for s in ("res", "clr", "mem"))
INR, INC = f"astryx_pgate_{PID}_inr", f"astryx_pgate_{PID}_inc"     # made by people_gate.ensure_roles itself
PRIV, NET = f"astryx_pgate_{PID}_priv", f"astryx_pgate_{PID}_net"
ORG = "pgtest"
# synthetic people: (id, label, direct, relation, who, shape, confidence)
PEOPLE = [("pA", "Alpha", True, "close-friend", "an old classmate", "daily, both ways", "high"),
          ("pB", "Bravo", False, "cousin", "a cousin on the mother's side", None, "medium"),
          ("pC", "Charlie", False, None, None, "weekly, they reach out", None),
          ("pD", "Delta", False, None, None, None, None),
          ("pE", "Echo", False, None, "a neighbour", None, None)]
DETAILED = [p for p in PEOPLE if any(v is not None for v in p[3:])]

fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def refused(dsn, stmt=None):
    """The error text a connect (stmt None) or a statement raises, or None if it succeeded."""
    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as c:
            if stmt:
                c.execute(stmt).fetchall()
        return None
    except psycopg.Error as e:
        return str(e)


def _gone(pid):
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def reap(adm, mine=False):
    """Drop this oracle's scratch objects: a dead pid's (start), or our own (finally). DBs before roles."""
    def ours(n):
        m = NAME.match(n)
        return m and (int(m.group(1)) == PID if mine else _gone(int(m.group(1))))
    for (d,) in adm.execute("SELECT datname FROM pg_database").fetchall():
        if ours(d):
            adm.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(d)))
    for (r,) in adm.execute("SELECT rolname FROM pg_roles ORDER BY rolname DESC").fetchall():   # mem before clr
        if ours(r):
            adm.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(r)))


try:
    ADMIN_DSN = live_dsn()
    admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
except Exception as e:                                              # noqa: BLE001
    skip(f"no reachable admin DSN ({type(e).__name__})")
sup, cdb, crole = admin.execute("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles "
                                "WHERE rolname = current_user").fetchone()
if not (sup or (cdb and crole)):
    skip("this role can't CREATE DATABASE and CREATE ROLE (a branch_check run role): VERIFIED NOTHING")
if not admin.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'age'").fetchone():
    skip("AGE isn't available on this server: the graph arms can't run")

def _load(mod, env):
    """mutation_probe hands a mutant copy's path in `env`; it REPLACES the module everywhere (social_age imports it)."""
    src = os.environ.get(env)
    if not src:
        return importlib.import_module(f"nucleus.{mod}")
    spec = importlib.util.spec_from_file_location(f"nucleus.{mod}", src)
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"nucleus.{mod}"] = m
    spec.loader.exec_module(m)
    return m


import importlib  # noqa: E402
import importlib.util  # noqa: E402

G = _load("people_gate", "PEOPLE_GATE_SRC")
M = _load("people_move", "PEOPLE_MOVE_SRC")

reap(admin)
PW = {r: secrets.token_urlsafe(18) for r in (RES, MEM)}


def as_(role, db):
    return make_conninfo(ADMIN_DSN, user=role, password=PW[role], dbname=db)


def mkrole(name, login, *in_roles):
    verifier = admin.pgconn.encrypt_password(PW[name].encode(), name.encode(), b"scram-sha-256").decode() \
        if login else None
    admin.execute(sql.SQL("CREATE ROLE {} " + ("LOGIN PASSWORD {}" if login else "NOLOGIN")
                          + " NOSUPERUSER NOCREATEDB NOCREATEROLE"
                          + (" IN ROLE {}" if in_roles else ""))
                  .format(sql.Identifier(name), *([sql.Literal(verifier)] if login else []),
                          *([sql.SQL(", ").join(map(sql.Identifier, in_roles))] if in_roles else [])))


def age_db(name):
    """A scratch AGE database, born zero-window, with the extension, as the admin."""
    admin.execute(sql.SQL("CREATE DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(name)))
    admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
    admin.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(sql.Identifier(name)))
    with psycopg.connect(make_conninfo(ADMIN_DSN, dbname=name), autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS age")


def cypher(dsn, graph, q, cols="r agtype"):
    from nucleus import agelib
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as c:
        agelib.prepare(c)
        return c.execute(f"SELECT * FROM cypher('{graph}', $q${q}$q$) AS ({cols})").fetchall()


try:
    # RED, live and read-only: what residents connect as today.
    live_super = admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]
    want("RED: the role in ASTRYX_DSN (every resident's today) is a superuser, so no GRANT gates it", live_super)

    mkrole(RES, True)
    mkrole(CLR, False)
    mkrole(MEM, True, CLR)
    G.ensure_roles(admin, resident=INR, cleared=INC)
    attrs = admin.execute("SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                          "FROM pg_roles WHERE rolname = ANY(%s) ORDER BY 1", ([INR, INC],)).fetchall()
    want("INERT: ensure_roles' defaults make the resident and the cleared role NOLOGIN, NOSUPERUSER, no CREATEDB/"
         "CREATEROLE/BYPASSRLS (nothing can connect as them until 1b)",
         len(attrs) == 2 and not any(any(a[1:]) for a in attrs), str(attrs))
    with fixture_db() as fx:
        db = fx["dbname"]
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            for pid, label, direct, rel, who, shape, conf in PEOPLE:
                c.execute("INSERT INTO social_person (org,id,kind,label,direct,relation,who,shape,confidence) "
                          "VALUES (%s,%s,'person',%s,%s,%s,%s,%s,%s)", (ORG, pid, label, direct, rel, who, shape, conf))
            c.execute("INSERT INTO social_person (org,id,kind,label) VALUES (%s,'g1','group','Group')", (ORG,))
            for pid in ("pA", "pB", "pC"):                      # pD, pE: in no context
                c.execute("INSERT INTO social_edge (org,src,dst) VALUES (%s,%s,'g1')", (ORG, pid))

            # RED: the superuser reads every detail; so does a resident given the obvious table-level grant.
            n = c.execute("SELECT count(*) FROM social_person WHERE relation IS NOT NULL OR who IS NOT NULL "
                          "OR shape IS NOT NULL OR confidence IS NOT NULL").fetchone()[0]
            want(f"RED: the superuser reads the {len(DETAILED)} detailed rows", n == len(DETAILED), str(n))
            c.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), sql.Identifier(RES)))
            c.execute(sql.SQL("GRANT SELECT ON social_person TO {}").format(sql.Identifier(RES)))
            e = refused(as_(RES, db), "SELECT relation, who, shape, confidence FROM social_person")
            want("RED: a NOSUPERUSER resident with table-level SELECT on social_person reads the details", e is None, e)

            # THE GATE, then THE MOVE.
            G.grant_main(c, resident=RES, cleared=CLR)
        class Spy:                                   # records each statement and the db's state right after it
            def __init__(self, c):
                self.c, self.log = c, []

            def execute(self, q, a=None):
                r = self.c.execute(q, a)
                txt = q.as_string(self.c) if hasattr(q, "as_string") else q
                st = self.c.execute("SELECT datallowconn, has_database_privilege('public', datname, 'CONNECT') "
                                    "FROM pg_database WHERE datname = %s", (PRIV,)).fetchone()
                self.log.append((txt, st))
                return r
        spy = Spy(admin)
        G.ensure_private_db(spy, name=PRIV, cleared=CLR)
        opened_public = [t for t, st in spy.log if st and st[0] and st[1]]
        want(f"ZERO-WINDOW: {PRIV} is never connectable while PUBLIC holds CONNECT (born closed, revoked, then opened)",
             spy.log and not opened_public and spy.log[-1][1] == (True, False), str(opened_public or spy.log[-1:]))
        with psycopg.connect(make_conninfo(ADMIN_DSN, dbname=PRIV), autocommit=True) as p:
            p.execute("CREATE EXTENSION IF NOT EXISTS age")
        age_db(NET)
        G.grant_network_db(admin, name=NET, resident=RES, cleared=CLR)
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            # A cut-over writer got to pC first (its source has no relation): the move must keep that value.
            c.execute("INSERT INTO social_relation (org,pid,kind) VALUES (%s,'pC','prior')", (ORG,))
            # A move that doesn't land must roll back WHOLE: a trigger eats `evidence` on the way in.
            c.execute("CREATE FUNCTION pgate_eat() RETURNS trigger LANGUAGE plpgsql AS "
                      "$$BEGIN NEW.evidence := NULL; RETURN NEW; END$$")
            c.execute("CREATE TRIGGER pgate_eat BEFORE INSERT OR UPDATE ON social_relation "
                      "FOR EACH ROW EXECUTE FUNCTION pgate_eat()")
        with psycopg.connect(fx["dsn"]) as c:
            try:
                M.move(c, apply=True)
                eaten = "no error"
            except RuntimeError as x:
                eaten = str(x)
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            n_left = c.execute(M.LEFT_SQL).fetchone()[0]
            n_rel = c.execute("SELECT count(*) FROM social_relation").fetchone()[0]
            want("MOVE: a move whose values don't land raises and rolls back WHOLE (source intact, nothing added)",
                 "rolled back" in eaten and n_left == len(DETAILED) and n_rel == 1, f"{eaten} left={n_left} rel={n_rel}")
            c.execute("DROP TRIGGER pgate_eat ON social_relation")
        with psycopg.connect(fx["dsn"]) as c:
            dry = M.move(c)
            want("MOVE: a dry run counts the detailed rows and changes nothing",
                 dry["rows"] == len(DETAILED) and not dry["applied"]
                 and c.execute(M.LEFT_SQL).fetchone()[0] == len(DETAILED), str(dry))
            try:
                rec = M.move(c, apply=True)
            except RuntimeError as x:
                rec = {"error": str(x)}
            want("MOVE: digest == digest_after, left == 0, every detailed row landed",
                 rec.get("applied") and rec["digest"] == rec["digest_after"] and rec["left"] == 0
                 and rec["social_relation"] == len(DETAILED), str(rec))
            try:
                again = M.move(c, apply=True)
            except RuntimeError as x:
                again = {"rows": -1, "left": str(x)}
            want("MOVE: a re-run moves nothing", again["rows"] == 0 and again["left"] == 0, str(again))
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            got = sorted(c.execute("SELECT pid, kind, context, evidence, confidence FROM social_relation "
                                   "WHERE org=%s", (ORG,)).fetchall())
        expect = sorted((p[0], p[3] if p[0] != "pC" else "prior", p[4], p[5], p[6]) for p in DETAILED)
        want("MOVE: social_relation holds exactly the moved values (relation->kind, who->context, shape->evidence),"
             " and a NULL source never overwrites a value already there (pC's kind)", got == expect, str(got))
        from nucleus import social_age
        r = social_age.rebuild(base=fx["dsn"], social=make_conninfo(ADMIN_DSN, dbname=NET),
                               private=make_conninfo(ADMIN_DSN, dbname=PRIV), resident=RES, cleared=CLR)
        want("the rebuild projects both graphs", r.get("private") == len(DETAILED) and r["knows"] == 3, str(r))
        r2 = social_age.rebuild(base=fx["dsn"], social=make_conninfo(ADMIN_DSN, dbname=NET),
                                private=make_conninfo(ADMIN_DSN, dbname=PRIV), resident=RES, cleared=CLR)
        want("a second rebuild (drop_graph, then re-grant) gives the same graphs", r2 == r, f"{r2} != {r}")

        # GREEN: the resident is refused, with the text predicted.
        e = refused(as_(RES, db), "SELECT * FROM social_relation")
        want("GREEN: resident SELECT social_relation -> 'permission denied for table social_relation'",
             e is not None and "permission denied for table social_relation" in e, e)
        for col in ("relation", "who", "shape", "confidence"):
            e = refused(as_(RES, db), f"SELECT {col} FROM social_person")
            want(f"GREEN: resident SELECT social_person.{col} -> 'permission denied for table social_person'",
                 e is not None and "permission denied for table social_person" in e, e)
        e = refused(as_(RES, PRIV))
        want(f"GREEN: resident CONNECT {PRIV} -> 'permission denied for database' + 'User does not have CONNECT"
             " privilege'", e is not None and f'permission denied for database "{PRIV}"' in e
             and "User does not have CONNECT privilege" in e, e)
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            want("GREEN: PUBLIC holds nothing on social_relation",
                 not any(c.execute("SELECT has_table_privilege('public', 'social_relation', %s)", (p,)).fetchone()[0]
                         for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")))
            d = G.drift(c, admin, resident=RES, cleared=CLR, private_db=PRIV)
            want("GREEN: people_gate.drift() is empty on the gated fixture", d == [], str(d))
            c.execute(sql.SQL("GRANT SELECT ON social_relation TO {}").format(sql.Identifier(RES)))
            c.execute(sql.SQL("GRANT SELECT (relation) ON social_person TO {}").format(sql.Identifier(RES)))
            c.execute("GRANT SELECT ON social_relation TO PUBLIC")
            admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(PRIV), sql.Identifier(RES)))
            d = G.drift(c, admin, resident=RES, cleared=CLR, private_db=PRIV)
            want("DRIFT: planted leaks are each named (PUBLIC and resident on social_relation, the relation column,"
                 " the private CONNECT)", len(d) == 4 and any("PUBLIC" in x for x in d)
                 and any("relation" in x and "column" in x for x in d) and any("CONNECT" in x for x in d), str(d))
            admin.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(sql.Identifier(PRIV), sql.Identifier(RES)))
            G.grant_main(c, resident=RES, cleared=CLR)
            d = G.drift(c, admin, resident=RES, cleared=CLR, private_db=PRIV)
            want("GREEN: re-applying grant_main repairs the planted table and column leaks (idempotent)", d == [], str(d))

        # CONTROL: the cleared member reads both; the resident still reads the network.
        e = refused(as_(MEM, db), "SELECT * FROM social_relation")
        want("CONTROL: a people_cleared member SELECTs social_relation", e is None, e)
        try:
            kinds = sorted(str(k[0]).strip('"') for k in cypher(
                as_(MEM, PRIV), "astryx_people", "MATCH (:owner)-[r:relation]->(:person) RETURN r.kind")
                if k[0] is not None and str(k[0]) != "null")
        except psycopg.Error as x:
            kinds = f"ERR {x}"
        want("CONTROL: a people_cleared member walks the private graph (owner)-[:relation]->(person)",
             kinds == sorted(e[1] for e in expect if e[1]), str(kinds))
        e = refused(as_(RES, db), "SELECT org, id, kind, label, direct, seen_at FROM social_person")
        want("CONTROL: the resident reads social_person's network columns", e is None, e)
        e = refused(as_(RES, db), "SELECT * FROM social_edge")
        want("CONTROL: the resident reads social_edge", e is None, e)
        try:
            knows = cypher(as_(RES, NET), "astryx_social", "MATCH (a:person)-[k:knows]->(b:person) RETURN count(k)")
            keys = cypher(as_(RES, NET), "astryx_social", "MATCH (n) RETURN keys(n)")
            keyset = set().union(*({x.strip(' "') for x in str(k[0]).strip("[]").split(",") if x.strip()}
                                   for k in keys))
        except psycopg.Error as x:
            knows, keyset = f"ERR {x}", {"ERR"}
        want("CONTROL: the resident walks the network graph (knows edges)",
             isinstance(knows, list) and str(knows[0][0]) == "3", str(knows))
        want("CONTROL: the network graph's nodes carry no detail (keys within id/org/name/direct)",
             keyset <= {"id", "org", "name", "direct"}, str(keyset))

        # CUTOVER: the writers, pointed at the fixture.
        os.environ["ASTRYX_DSN"], os.environ["ASTRYX_ORG"] = fx["dsn"], ORG
        from nucleus import people, persona
        people.write_pg({"people": {p[0]: {"id": p[0], "label": p[1], "direct": p[2]} for p in PEOPLE},
                         "groups": {"g1": {"id": "g1", "label": "Group"}},
                         "edges": [{"src": "pA", "dst": "g1"}]},
                        personas={"pA": {"relation": "LEAK", "who": "LEAK", "shape": "LEAK", "confidence": "LEAK"}})
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            want("CUTOVER: people.write_pg writes no detail onto social_person",
                 c.execute(M.LEFT_SQL).fetchone()[0] == 0)
            want("CUTOVER: people.write_pg's nightly DELETE+INSERT leaves social_relation intact",
                 sorted(c.execute("SELECT pid, kind, context, evidence, confidence FROM social_relation "
                                  "WHERE org=%s", (ORG,)).fetchall()) == expect)
        n = persona.apply_pg({"pD": {"shape": "monthly", "relation": None, "who": None, "confidence": None},
                              "pA": {"shape": "hourly", "relation": None, "who": None, "confidence": None}})
        back = persona.load_pg()
        want("CUTOVER: persona.apply_pg writes social_relation, and load_pg reads it back (COALESCE keeps kind)",
             n == 2 and back.get("pD", {}).get("shape") == "monthly" and back["pA"]["shape"] == "hourly"
             and back["pA"]["relation"] == "close-friend", f"{n} {back.get('pA')} {back.get('pD')}")
        # persona_llm, with the channel and the model stubbed: it labels an UNLABELLED person into social_relation
        # and skips a labelled one, and never writes social_person.
        from nucleus import persona_llm
        jids = {"pA@s.whatsapp.net": "pA", "pD@s.whatsapp.net": "pD"}
        real = people._wa, people.pid, persona_llm.classify
        people.pid = lambda j: jids[j]
        people._wa = lambda *a, **k: ([{"jid": j, "last_message_ts": "1"} for j in jids] if a[0] == "chats"
                                      else {"messages": [{"Text": "a message long enough to be sampled " * 2}]})
        persona_llm.classify = lambda text: {"relation": "neighbour", "who": "next door", "confidence": "low"}
        try:
            res = persona_llm.run(limit=5, budget_s=60)
        finally:
            people._wa, people.pid, persona_llm.classify = real
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            kd = dict(c.execute("SELECT pid, kind FROM social_relation WHERE org=%s AND pid IN ('pA','pD')",
                                (ORG,)).fetchall())
            n_left = c.execute(M.LEFT_SQL).fetchone()[0]
        want("CUTOVER: persona_llm labels the unlabelled person into social_relation, skips the labelled one, and "
             "writes nothing onto social_person", res.get("labelled") == 1 and res.get("skipped") == 1
             and kd == {"pA": "close-friend", "pD": "neighbour"} and n_left == 0, f"{res} {kd} {n_left}")

        # LAST, because an ALTER changes social_person's signature and so voids its fixture stamp for any later
        # write (sqlguard would credit nothing after it).
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            c.execute("ALTER TABLE social_person ADD COLUMN pgate_later text")
            d = G.drift(c, admin, resident=RES, cleared=CLR, private_db=PRIV)
            e = refused(as_(RES, db), "SELECT pgate_later FROM social_person")
            want("GREEN: a column added later is hidden from the resident (fail-closed), and drift stays empty",
                 e is not None and "permission denied" in e and d == [], f"{e} {d}")
finally:
    try:
        reap(admin, mine=True)
        left = [n for (n,) in admin.execute("SELECT datname FROM pg_database UNION ALL SELECT rolname FROM pg_roles")
                .fetchall() if NAME.match(n) and int(NAME.match(n).group(1)) == PID]
        want("no scratch role or database is left behind", left == [], str(left))
    finally:
        admin.close()

print(f"\n{'FAIL' if fails else 'PASS'}: test_people_gate ({len(fails)} failing)")
sys.exit(1 if fails else 0)
