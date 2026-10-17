"""The HOST's org registry (plan-11324 S3a, design #58435 item 1): which orgs this host runs, and where each one's HOME is.

ONE predicate decides every multi-org rule, `multi()`. The resolver's refusals (paths.resolve_home), the environment
DSN's check (config.dsn, correction 2), spawn's built environment (BC-S3) and the units' HOME all key off it, never
off anything else, so a host without a registry runs today's code byte for byte (the bar for every S3 stage).

  ABSENT registry       one org, today's behaviour: every other branch here is dead code
  one entry             one org, still today's behaviour (a registry naming only the primary changes nothing)
  two or more entries   multi-org: the HOME is CARRIED (ASTRYX_HOME) or marked, never the checkout or ~/.astryx

Its place is HOST-level, inside neither the checkout nor any HOME: `/etc/astryx/orgs.json` (writing it is a sudo
step, which is what adding an org to a host should cost). `ASTRYX_ORG_REGISTRY` names another file; it is the
fixture seam the oracles use, and it is a DECLARED host-class name (data/org_env.json) so it survives spawn's built
environment. Under R1 (one owner, one superuser) it isn't a security boundary: an org process that sets it to a
missing file reads a one-org host. That is correctness isolation, declared, not containment (a1 §6).

The file:  {"orgs": {"<org>": {"home": "/abs/HOME", "db": "<its database>"}, ...}}
`db` is the org's main database by name, so a process can tell "another org's database" WITHOUT reading another
org's .env (no cross-org read outside the declared host-scoped set, a2 E). Its own .env must name the same database:
config.dsn checks that pair for its own org only.

A registry that is present but malformed RAISES (RegistryError): an unreadable registry fails closed, never as absent.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_PATH = Path("/etc/astryx/orgs.json")
ENV = "ASTRYX_ORG_REGISTRY"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
# libpq's last-resort databases (correction 1(ii)): with no dbname anywhere it binds the USER's name, and `postgres`
# is every cluster's maintenance database. An org there could be reached by an empty DSN plus two PG* names.
NEVER_ORG_DB = ("postgres",)
FIXTURE_DB = "astryx_fx_"       # sqlguard.fixture.PREFIX, re-read there by the oracle, never imported here


class RegistryError(RuntimeError):
    """The registry is present and refuses: malformed, or it names an org the rules forbid. A RuntimeError, NOT a
    LookupError: oracles read a LookupError around the DSN as "no DB, not run" (77), and a broken registry must fail."""


def path(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env[ENV]) if env.get(ENV) else DEFAULT_PATH


def load(env=None) -> dict | None:
    """{org: {"home": Path, "db": str}}, or None when there is no registry (a one-org host)."""
    p = path(env)
    try:
        text = p.read_text()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise RegistryError(f"org registry {p} unreadable: {type(e).__name__}") from None
    try:
        raw = json.loads(text)["orgs"]
        assert isinstance(raw, dict) and raw
    except (ValueError, KeyError, TypeError, AssertionError):
        raise RegistryError(f"org registry {p}: expected {{\"orgs\": {{name: {{home, db}}}}}}") from None
    out, homes, dbs = {}, {}, {}
    for org, e in raw.items():
        if not isinstance(org, str) or not NAME.fullmatch(org) or not isinstance(e, dict):
            raise RegistryError(f"org registry {p}: bad entry {org!r}")
        home, db = e.get("home"), e.get("db")
        if not isinstance(home, str) or not os.path.isabs(home) or not isinstance(db, str) or not db:
            raise RegistryError(f"org registry {p}: {org} needs an absolute home and a db")
        h = Path(home).resolve()
        if db in NEVER_ORG_DB or db.startswith(FIXTURE_DB):
            raise RegistryError(f"org registry {p}: {org}'s database {db!r} is libpq's fallback or a fixture's")
        if h in homes or db in dbs:
            raise RegistryError(f"org registry {p}: {org} shares a home or database with {homes.get(h) or dbs[db]}")
        homes[h], dbs[db] = org, org
        out[org] = {"home": h, "db": db}
    return out


def multi(env=None) -> bool:
    """THE predicate: does this host run more than one org?"""
    reg = load(env)
    return reg is not None and len(reg) > 1


def org_of(home, env=None) -> str | None:
    """The registered org whose HOME is `home`, or None."""
    h = Path(home).resolve()
    for org, e in (load(env) or {}).items():
        if e["home"] == h:
            return org
    return None


def conninfo(dsn: str) -> dict:
    """libpq's own reading of a DSN (URI or key=value), through psycopg: never a second parser of the grammar."""
    from psycopg.conninfo import conninfo_to_dict
    return conninfo_to_dict(dsn)


def db_of(dsn: str) -> str | None:
    """The database a DSN binds, as libpq resolves it when the DSN names none: the user's name (correction 1).
    None when neither is in the DSN (then the environment's PG* decides, which multi-org forbids, BC-S3)."""
    d = conninfo(dsn)
    return d.get("dbname") or d.get("user")


def is_fixture(dsn: str) -> bool:
    return (db_of(dsn) or "").startswith(FIXTURE_DB)


def _main(argv) -> int:
    """`python -m astryx.orgs multi` exits 0 on a multi-org host, 1 otherwise, 2 when the registry refuses.
    spawn.sh and init.sh ask THIS, so a shell copy of the predicate can never drift from it."""
    import sys
    try:
        if argv[:1] == ["multi"]:
            return 0 if multi() else 1
    except RegistryError as e:
        print(f"astryx.orgs: {e}", file=sys.stderr)
        return 2
    print("usage: python -m astryx.orgs multi", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
