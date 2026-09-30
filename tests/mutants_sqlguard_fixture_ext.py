"""Authored mutants for nucleus/sqlguard/fixture.py's run-role path (plan-4918 P0-c), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_sqlguard_fixture_ext.py

The sqlguard harness runs as superuser, which hides both properties: it can COMMENT on extension-owned views, and
it CREATEs extensions itself. Only the prep oracle's NOSUPERUSER fixture sees them, so that's the oracle here.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "sqlguard" / "fixture.py"
ORACLE = REPO / "tests" / "test_branch_check_prep.py"
ENV = "SQLGUARD_FIXTURE_SRC"

MUTANTS = {
    "F1 extension members are stamped (COMMENT on postgis's views: 'must be owner' under the run role)":
        ("             \"AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass \"\n"
         "             \"AND d.objid = c.oid AND d.deptype = 'e')\")",
         "             \"\")"),
    "F3 no REVOKE at creation (a concurrent run role can CONNECT to the fixture)":
        ("        admin.execute(f'REVOKE CONNECT ON DATABASE \"{name}\" FROM PUBLIC')\n", ""),
    "F4 the fixture is born OPEN (a run role can connect in the CREATE→REVOKE window and keep its session)":
        ("        admin.execute(f'CREATE DATABASE \"{name}\" ALLOW_CONNECTIONS false'",
         "        admin.execute(f'CREATE DATABASE \"{name}\"'"),
    "F5 schema.sql errors are wrapped as FixtureUnavailable (a broken schema reads 'not run')":
        ("            c.execute(SCHEMA.read_text())          # the WHOLE file, the same bytes init.sh applies\n",
         "            try:\n                c.execute(SCHEMA.read_text())\n"
         "            except Exception as e:\n                raise FixtureUnavailable('wrapped') from e\n"),
    "F6 an unreachable server raises raw, not FixtureUnavailable (consumers can't narrow)":
        ("    except (OSError, StopIteration, psycopg.OperationalError) as e:\n", "    except ZeroDivisionError as e:\n"),
    "F7 url() puts a socket directory in the authority (asyncpg falls back to localhost TCP)":
        ('    if d.get("host", "").startswith("/"):\n', '    if False:\n'),
    "F2 ASTRYX_FIXTURE_TEMPLATE ignored (a NOSUPERUSER fixture silently lacks the extensions)":
        ("    tpl = os.environ.get(\"ASTRYX_FIXTURE_TEMPLATE\")", "    tpl = None"),
}
