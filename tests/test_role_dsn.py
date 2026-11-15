"""cog_roles.role_dsn keeps the base DSN's FORM: a postgresql:// URL stays a URL (asyncpg, the observatory's pool,
accepts only URLs; make_conninfo always returns key=value — a live rehearsal caught the observatory failing to start,
11-13), key=value stays key=value; user/password with reserved characters round-trip."""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_role_dsn", REPO, deps=('psycopg',), env=False)   # a clean clone (no venv): 77, not an import crash
spec = importlib.util.spec_from_file_location("cog_roles", REPO / "devtools" / "cog_roles.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
from psycopg.conninfo import conninfo_to_dict  # noqa: E402

fails = []


def arm(name, ok, got=None):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  got={got!r}"))
    if not ok:
        fails.append(name)


u = m.role_dsn("postgresql://su:old%40pw@127.0.0.1:5433/main?sslmode=disable", "org_x", "p@ss:/w rd", "other")
d = conninfo_to_dict(u)
arm("U1 a URL base stays a postgresql:// URL", u.startswith("postgresql://"), u.split("@")[-1])
arm("U2 role, password (reserved chars), db, port and params round-trip",
    (d["user"], d["password"], d["dbname"], d["port"], d.get("sslmode")) == ("org_x", "p@ss:/w rd", "other", "5433", "disable"))
arm("U3 no dbname given keeps the base's", conninfo_to_dict(m.role_dsn("postgresql://su@h:1/main", "r", "p"))["dbname"] == "main")
k = m.role_dsn("host=h port=5 dbname=a user=u", "org_x", "pw")
arm("K1 a key=value base stays key=value", "://" not in k and conninfo_to_dict(k)["user"] == "org_x")
try:
    import asyncpg.connect_utils as cu
    cu._parse_connect_dsn_and_args(dsn=u, host=None, port=None, user=None, password=None, passfile=None, database=None,
                                   ssl=None, direct_tls=None, server_settings=None, target_session_attrs=None,
                                   krbsrvname=None, gsslib=None, service=None, servicefile=None)
    arm("A1 asyncpg parses the URL", True)
except Exception as e:  # noqa: BLE001
    arm("A1 asyncpg parses the URL", False, repr(e))
print("PASS: role dsn" if not fails else f"FAIL: role dsn ({fails})")
sys.exit(1 if fails else 0)
