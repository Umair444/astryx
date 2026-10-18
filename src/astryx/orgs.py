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

The file:  {"orgs": {"<org>": {"home": "/abs/HOME", "db": "<its database>", "ports": {"<unit stem>": <port>}, "door": false}, ...}}
`ports` (S3b 5/n, seed #59954 ruling 3) is optional at load: it holds the port of each per-org unit that binds one
(data/org_units.json, scope org with a port), keyed by the unit's stem. A port is a HOST-wide name like a tmux socket,
so the registry refuses one two orgs share, and one equal to a COG-scoped unit's port (8090/8845, ruling 3(a)).
In a cog of several orgs there is no default: port() REFUSES a missing one (ruling 3(b): the primary org declares its
ports like any other).
`door` (optional, at most one entry true) names the org the cog's gateway serves at its bare root (S3e).
`primary` (optional, at most one entry true; seed #60780: the primary org moves as little as possible when a cog forms)
names the org that was this host's one org before the cog: it keeps tmux's DEFAULT socket and its PLAIN unit names
(socket() and unit() answer for it as on one org), so its residents, its pulse and every tool see nothing move. A
door, if named, is the primary's: the bare root was the primary's before the cog existed.
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


UNITS = Path(__file__).resolve().parent / "data" / "org_units.json"


def _units() -> dict:
    return json.loads(UNITS.read_text())["units"]


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
    out, homes, dbs, ports = {}, {}, {}, {}
    units = _units()
    cog_ports = {u["port"] for u in units.values() if u["scope"] == "cog" and "port" in u}
    org_stems = {k for k, u in units.items() if u["scope"] == "org" and ("port" in u or u.get("registry_port"))}
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
        pe = e.get("ports", {})
        if not isinstance(pe, dict):
            raise RegistryError(f"org registry {p}: {org}'s ports must be an object {{unit stem: port}}")
        pe = {k: int(v) if type(v) is float and v.is_integer() else v for k, v in pe.items()}   # JSON's 18477.0 is
        # node's integer 18477 (home.mjs can't tell them apart): one number, one verdict in both readers
        for stem, port in pe.items():
            if stem not in org_stems:
                raise RegistryError(f"org registry {p}: {org} gives a port to {stem!r}, not a per-org unit that binds one")
            if type(port) is not int or not 1 <= port <= 65535:
                raise RegistryError(f"org registry {p}: {org}'s {stem} port {port!r} is not a port number")
            if port in cog_ports:
                raise RegistryError(f"org registry {p}: {org}'s {stem} port {port} is a COG-scoped unit's")
            if port in ports:
                raise RegistryError(f"org registry {p}: {org}'s {stem} port {port} is already {ports[port]}'s")
            ports[port] = f"{org} {stem}"
        door, primary = e.get("door", False), e.get("primary", False)
        if not isinstance(door, bool):
            raise RegistryError(f"org registry {p}: {org}'s door must be true or false")
        if not isinstance(primary, bool):
            raise RegistryError(f"org registry {p}: {org}'s primary must be true or false")
        if door and not primary:                        # the bare root was the primary's before the cog (seed #60780)
            raise RegistryError(f"org registry {p}: {org} claims the door but is not the primary; the door is the "
                                "primary's")
        homes[h], dbs[db] = org, org
        out[org] = {"home": h, "db": db, "ports": dict(pe), "door": door, "primary": primary}
    # ONE primary (it alone keeps the default socket and plain unit names); a door is the primary's, so there is at
    # most one door too (S3e, seed #60376), by construction
    prims = [o for o, e in out.items() if e["primary"]]
    if len(prims) > 1:
        raise RegistryError(f"org registry {p}: {' and '.join(prims)} both claim to be the primary; one org is")
    return out


def door(env=None) -> str | None:
    """The org whose door is the cog's BARE root (S3e, seed #60376), or None: then a bare path names no org and
    refuses. It answers at /o/<org> as well, so its peers move to the explicit path at their own pace."""
    return next((o for o, e in (load(env) or {}).items() if e["door"]), None)


def primary(env=None) -> str | None:
    """The org that keeps the one-org names in a cog (seed #60780), or None."""
    return next((o for o, e in (load(env) or {}).items() if e["primary"]), None)


def _plain(o, env) -> bool:
    """True when THIS process's org answers as on one org: no org (one-org host), or the primary."""
    return o is None or load(env)[o]["primary"]


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
    Several orgs: `ax-<org>`, a server of its own (-L), so a session name only ever means this org's resident. The
    PRIMARY keeps the default socket (seed #60780): its residents were there before the cog, and stay. In a cog it NAMES
    it, `default` (tmux's own default socket, $TMUX_TMPDIR/tmux-<uid>/default: the same server), never the bare
    form: a bare `tmux` follows an inherited $TMUX, so a primary tool run from another org's pane would spawn on
    THAT org's server and the primary's healer would start the seat again (a2 #60794 R-1). One org: None, as before."""
    o = name(env, cwd)
    return None if o is None else "default" if _plain(o, env) else f"ax-{o}"


def tmux(env=None, cwd=None) -> list[str]:
    """The argv prefix every tmux call starts with: ["tmux"] on one org, ["tmux", "-L", "ax-<org>"] on several (the
    primary's: ["tmux", "-L", "default"]). -L wins over an inherited $TMUX, so a caller inside another org's pane still
    reaches its own org's server, the primary's included."""
    s = socket(env, cwd)
    return ["tmux"] if s is None else ["tmux", "-L", s]


def unit(stem: str, suffix: str = "service", env=None, cwd=None) -> str:
    """THIS org's systemd unit name (plan-11324 S3b, data/org_units.json): `<stem>.<suffix>` on one org, exactly as
    before; `<stem>@<org>.<suffix>` on several, the instance FILE init.sh units() writes for this org. The PRIMARY keeps
    its plain names (seed #60780)."""
    o = name(env, cwd)
    return f"{stem}.{suffix}" if _plain(o, env) else f"{stem}@{o}.{suffix}"


def port(stem: str, env=None, cwd=None) -> int | None:
    """The port THIS org's unit `stem` binds (S3b 5/n): None on one org (the caller keeps its fixed port, byte for byte
    as before); in a cog of several orgs the org's registry `ports[stem]`, and a missing one RAISES, never a default."""
    o = name(env, cwd)
    if o is None:
        return None
    got = load(env)[o]["ports"].get(stem)
    if got is None:
        raise RegistryError(f"org registry {path(env)}: {o} declares no port for {stem} (this cog runs several orgs: "
                            f"every org's port is in its registry entry, there is no default)")
    return got


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
    `primary` prints the registry's primary org (exit 1 when none); `unit <stem> [suffix]` THIS org's unit file name.
    `socket` prints this org's tmux socket (`name` its name, `port <stem>` its unit's port) and exits 0 on several
    orgs, exits 1 on one, 2 when no registered HOME is carried (or, for `port`, the org declares none). spawn.sh and init.sh ask THIS, so a shell copy of the predicate can never drift from it."""
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
        if argv[:1] == ["port"] and len(argv) == 2:   # init.sh units(): this org's port for a unit (exit 0); 1 on one
            n = port(argv[1])
            if n is None:
                return 1
            print(n)
            return 0
        if argv[:1] == ["unit"] and len(argv) in (2, 3):   # init.sh units(): THIS org's unit file name (exit 0)
            print(unit(argv[1], *argv[2:]))              # the ONE authority for it (a2 #60794): never rebuilt in bash
            return 0
        if argv[:1] == ["primary"]:           # init.sh units(): the registry's primary org (exit 0); 1 when none
            o = primary()
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
    print("usage: python -m astryx.orgs multi|name|primary|socket|port <unit stem>|unit <stem> [suffix]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # run as a script: `socket` reaches astryx.paths
    sys.exit(_main(sys.argv[1:]))
