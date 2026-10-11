"""Authored mutants for nucleus/runscope.py (plan-4918 R1), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_runscope.py

One per property the primitive rests on: ownership-derived teardown, the template clear, the (pid, starttime)
liveness key, and the refusal of a scope that isn't bound to its own directory.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "runscope.py"
ORACLE = REPO / "tests" / "test_runscope.py"
ENV = "RUNSCOPE_SRC"

# R13 was once DECLARED (unsafe: the oracle's sweep ran org-wide, and it dropped every bc_* role on 10-09). Since a3 D1
# #35480 every oracle sweep passes only= its OWN roles, so a mutated predicate can destroy nothing else: authored.
TIMEOUT = 300          # ~60 s alone; concurrent full checks and batteries pushed some runs past 120 s (10-09)
MUTANTS = {
    "R1 teardown by NAME prefix, not ownership (a differently named db is missed)":
        ("    q = \"SELECT d.datname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba WHERE r.rolname = %s ORDER BY 1\"",
         "    q = \"SELECT d.datname FROM pg_database d WHERE d.datname LIKE %s || '%%' ORDER BY 1\""),
    "R2 no IS_TEMPLATE clear before DROP (a run-owned template survives)":
        ("                c.execute(sql.SQL(\"ALTER DATABASE {} IS_TEMPLATE false\").format(sql.Identifier(db)))\n", ""),
    "R3 liveness by pid alone (a reused pid reads alive)":
        ("    return st is not None and st == lock.get(\"starttime\")", "    return st is not None"),
    "R4 the role isn't bound to its directory (a crafted lock can name any role)":
        ("            and role == f\"{ROLE_PREFIX}{root.name}\".lower() and role.startswith(ROLE_PREFIX))",
         "            and role.startswith(ROLE_PREFIX))"),
    "R5 the root isn't bound to the base (any absolute path is removed)":
        ("    return (root.is_absolute() and root.resolve().parent == base.resolve()", "    return (root.is_absolute()"),
    "R7 create_db is born OPEN (a concurrent run role can connect in the gap and keep its session)":
        ("        q = sql.SQL(\"CREATE DATABASE {} OWNER {} ALLOW_CONNECTIONS false\").format(",
         "        q = sql.SQL(\"CREATE DATABASE {} OWNER {}\").format("),
    "R8 create_db never revokes PUBLIC CONNECT":
        ("            c.execute(sql.SQL(\"REVOKE CONNECT ON DATABASE {} FROM PUBLIC\").format(sql.Identifier(name)))\n", ""),
    "R6 the server gets the PLAINTEXT password, not a SCRAM verifier":
        ("sql.Identifier(self.role), sql.Literal(verifier.decode())))",
         "sql.Identifier(self.role), sql.Literal(self._password)))"),
    "R10 live() counts every scope, dead ones included (a stale scope would stop eviction forever)":
        ("            if alive(json.loads((d / \"lock.json\").read_text())):", "            if json.loads((d / \"lock.json\").read_text()):"),
    "R9 the run role gets no AGE preload (it can't LOAD, so AGE is unusable in the run)":
        ("            if c.execute(\"SELECT 1 FROM pg_available_extensions WHERE name = 'age'\").fetchone():",
         "            if False:"),
    "R11 the sweep never reads postgres for orphans (a reboot strands every crashed run's role and DBs: a2 F1)":
        ("    for role in orphan_roles(admin_dsn, only=only, foreign=foreign, synthetic=synthetic):", "    for role in []:"),
    "R12 orphan liveness by pid alone (a reused pid after a reboot shields the dead run's role forever)":
        ("        if started is not None and started <= int(m.group(2)) + 2:", "        if started is not None:"),
    "R13 orphans ignore liveness (a LIVE run whose lock was wiped is torn down mid-run)":
        ("            if started is not None and started <= int(m.group(2)) + 2:      # the creator (or older) is still alive\n                continue\n", ""),
    "R14 the candidate set is ignored (an oracle's sweep reaches every role on the cluster)":
        ("            if only is not None and r not in only:\n                continue\n", ""),
    "R15 the host stamp is ignored (host A reaps host B's live run, which has no local pid)":
        ("            if not MACHINE_ID or not stamp or stamp[0] not in ok:", "            if False:"),
    "R16 the dbus id is never consulted (an older Linux host stamps nothing, so its orphans are never reaped)":
        ('    for f in ("/etc/machine-id", "/var/lib/dbus/machine-id"):', '    for f in ("/etc/machine-id",):'),
    "R17 an EMPTY id file is taken as the id (every host with an empty file shares one stamp)":
        ("        if v:\n            return v", "        if True:\n            return v"),
    "R18 an unscoped sweep adopts a synthetic-epoch role (a real run reaps a live oracle's planted roles)":
        ("            if only is None and int(m.group(2)) < MIN_EPOCH:", "            if False:"),
    "R19 _drop_owned raises on a lost connection (one orphan crashes the run)":
        ("    except psycopg.Error as e:\n        out[\"errors\"].append(f\"connection:",
         "    except ZeroDivisionError as e:\n        out[\"errors\"].append(f\"connection:"),
    "R20 sweep lets one orphan's drop failure escape":
        ("        except Exception as e:                         # noqa: BLE001 — one orphan never crashes the run",
         "        except ZeroDivisionError as e:                 # noqa: BLE001 — one orphan never crashes the run"),
    "R21 an unscoped sweep accepts the TEST stamp (a real run reaps a live oracle's real-epoch crashed child: a3 #37109)":
        ("            ok = {MACHINE_ID} if only is None else {MACHINE_ID, TEST_STAMP}",
         "            ok = {MACHINE_ID, TEST_STAMP}"),
    "R22 an oracle's run role carries the production stamp (ownership is invisible to the sweep)":
        ("    return TEST_STAMP if os.environ.get(TEST_ENV) else MACHINE_ID", "    return MACHINE_ID"),
    "R23 a scoped oracle sweep rejects its own test stamp (an oracle's crashed run is never reaped)":
        ("            ok = {MACHINE_ID} if only is None else {MACHINE_ID, TEST_STAMP}",
         "            ok = {MACHINE_ID}"),
    "R24 the census REAPS what it reads (a standing read that drops a live operator's debris evidence)":
        ("    dead = [d.name for d, _ in dead_scopes(base, unprovable)]",
         "    dead = [x[\"scope\"] for x in sweep(admin_dsn, base, only=only) if not x.get(\"orphan\")]"),
    "R25 the census calls a lockless dir debris (an unprovable dir accused)":
        ("    return {\"dead_scopes\": dead, \"orphans\": orphans,",
         "    return {\"dead_scopes\": dead + unprovable, \"orphans\": orphans,"),
    "R26 the census counts another host's (or an oracle's) orphan as this host's debris":
        ("    return {\"dead_scopes\": dead, \"orphans\": orphans,", "    return {\"dead_scopes\": dead, \"orphans\": orphans + foreign,"),
    "R27 the census keys on AGE, not liveness (a live scope older than a minute is accused)":
        ("    dead = [d.name for d, _ in dead_scopes(base, unprovable)]",
         "    dead = [d.name for d in sorted((base or SCOPE_ROOT).iterdir()) if d.is_dir() and (d / \"lock.json\").exists()\n"
         "            and time.time() - (d / \"lock.json\").stat().st_mtime > 0]"),
    "R28 IS_TEMPLATE is ALTERed BEFORE the drop (an INVALID database FATALs and closes the connection: 10-11)":
        ("                    try:\n                        c.execute(sql.SQL(\"DROP DATABASE {} WITH (FORCE)\").format(sql.Identifier(db)))\n"
         "                    except psycopg.errors.WrongObjectType:\n",
         "                    c.execute(sql.SQL(\"ALTER DATABASE {} IS_TEMPLATE false\").format(sql.Identifier(db)))\n"
         "                    if True:\n                        c.execute(sql.SQL(\"DROP DATABASE {} WITH (FORCE)\").format(sql.Identifier(db)))\n"
         "                    if False:\n"),
}
