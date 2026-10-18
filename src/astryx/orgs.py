"""The COG's org registry (plan-11324 S3a, design #58435 item 1): which orgs this astryx install runs, and where each
one's HOME is. Vocabulary (owner ruling, seed #60082): agent → group → org → COG (several orgs in one install) →
FEDERATION (across installs). This module is about the orgs within a cog.

ONE predicate decides every multi-org rule, `multi()`. The resolver's refusals (paths.resolve_home), the environment
DSN's check (config.dsn, correction 2), spawn's built environment (BC-S3) and the units' HOME all key off it, never
off anything else, so a host without a registry runs today's code byte for byte (the bar for every S3 stage).

  ABSENT registry       one org, today's behaviour: every other branch here is dead code
  one entry             one org, still today's behaviour (a registry naming only the primary changes nothing)
  two or more entries   multi-org: the HOME is CARRIED (ASTRYX_HOME) or marked, never the checkout or ~/.astryx

Its place is HOST-level, inside neither the checkout nor any HOME: `/etc/astryx/cog.json` (writing it is a sudo
step, which is what adding an org to a host should cost). `ASTRYX_COG_REGISTRY` names another file; it is the
fixture seam the oracles use, and it is a DECLARED host-class name (data/org_env.json) so it survives spawn's built
environment. Under R1 (one owner, one superuser) it isn't a security boundary: an org process that sets it to a
missing file reads a one-org host. That is correctness isolation, declared, not containment (a1 §6).

The file:  {"orgs": {"<org>": {"home": "/abs/HOME", "db": "<its database>"}, ...}}
`db` is the org's main database by name, so a process can tell "another org's database" WITHOUT reading another
org's .env (no cross-org read outside the declared cog-scoped set, a2 E). Its own .env must name the same database:
config.dsn checks that pair for its own org only.

A registry that is present but malformed RAISES (RegistryError): an unreadable registry fails closed, never as absent.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_PATH = Path("/etc/astryx/cog.json")
ENV = "ASTRYX_COG_REGISTRY"
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


def name(env=None, cwd=None) -> str | None:
    """THIS process's org: None on a one-org host, else the registered org whose HOME the ONE resolver gives
    (paths.resolve_home, which refuses an unregistered or uncarried HOME: NoHome)."""
    if not multi(env):
        return None
    from astryx import paths
    return org_of(paths.resolve_home(env, cwd)[0], env)


def socket(env=None, cwd=None) -> str | None:
    """The tmux socket this org's residents live on (plan-11324 S3b, #58435: `ax-<agent>` is a HOST-wide name, so
    two orgs' `seed` would be one session). None on a one-org host: tmux's default socket, byte for byte as before.
    Several orgs: `ax-<org>`, a server of its own (-L), so a session name only ever means this org's resident."""
    o = name(env, cwd)
    return None if o is None else f"ax-{o}"


def tmux(env=None, cwd=None) -> list[str]:
    """The argv prefix every tmux call starts with: ["tmux"] on one org, ["tmux", "-L", "ax-<org>"] on several.
    -L wins over an inherited $TMUX, so a caller inside another org's pane still reaches its own org's server."""
    s = socket(env, cwd)
    return ["tmux"] if s is None else ["tmux", "-L", s]


def unit(stem: str, suffix: str = "service", env=None, cwd=None) -> str:
    """THIS org's systemd unit name (plan-11324 S3b, data/org_units.json): `<stem>.<suffix>` on one org, exactly as
    before; `<stem>@<org>.<suffix>` on several, the instance FILE init.sh units() writes for this org."""
    o = name(env, cwd)
    return f"{stem}.{suffix}" if o is None else f"{stem}@{o}.{suffix}"


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
    """`python -m astryx.orgs multi` exits 0 in a cog of several orgs, 1 otherwise, 2 when the registry refuses.
    `socket` prints this org's tmux socket (`name` its name) and exits 0 on several orgs, exits 1 on one, 2 when no
    registered HOME is carried. spawn.sh and init.sh ask THIS, so a shell copy of the predicate can never drift from it."""
    import sys
    try:
        if argv[:1] == ["multi"]:
            return 0 if multi() else 1
        if argv[:1] == ["name"]:              # init.sh units(): this org's name (exit 0) on several orgs; 1 on one
            o = name()
            if o is None:
                return 1
            print(o)
            return 0
        if argv[:1] == ["socket"]:            # scripts/org_tmux.sh: prints ax-<org> (exit 0) on several orgs; 1 on one
            s = socket()
            if s is None:
                return 1
            print(s)
            return 0
    except RegistryError as e:
        print(f"astryx.orgs: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — anything else REFUSES too: python's own crash exit is 1, which every
        # guard reads as "one org, proceed" (a registry nested past the parser's recursion limit did exactly that)
        print(f"astryx.orgs: the registry could not be judged ({type(e).__name__}): refusing", file=sys.stderr)
        return 2
    print("usage: python -m astryx.orgs multi|name|socket", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # run as a script: `socket` reaches astryx.paths
    sys.exit(_main(sys.argv[1:]))
