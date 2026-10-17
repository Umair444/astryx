"""An org process's environment is BUILT, never inherited (plan-11324 S3a, a3 BC-S3 #58597, a1 BC-S1(1) #58437).

On a host that runs several orgs (orgs.multi), spawn's pane and every generated unit exec through this:

    python src/astryx/orgenv.py exec --home <HOME> [--agent <name>] -- <command> [args...]

It starts from NOTHING (the `env -i` of BC-S3) and keeps, from what it inherited, only the names in a PASS class of
data/org_env.json (host: PATH, HOME, LANG, …; pane: TMUX, TMUX_PANE), then sets the home class from the HOME:
ASTRYX_HOME, ASTRYX_AGENT and ASTRYX_DSN (read from HOME/.env through astryx.config, so the environment agrees with
the HOME at its source, BC-S1(1)). Every other name is ABSENT: an org name (A's PEOPLE_SALT, WA_CLI, …), a session
name, a PG* default (correction 1(i)), and any name in no class at all (fail closed). Readers then fall back to the
HOME's .env.

tmux `-e` can only ADD names (a3's mechanism), so the pane runs this as its command and this execs the shell. The
shell is `bash --norc --noprofile`: an rc file could export a name back after the build (the pane's environ would be
clean and the CLI's not). On a one-org host nothing calls this; spawn and the units are byte-identical to before.
"""
if not __package__:  # run by path (spawn's pane, a unit): the checkout's src/ goes first so `astryx` resolves
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))
import fnmatch  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from astryx import paths  # noqa: E402

CLASSES = paths.DATA / "org_env.json"


def classes() -> dict:
    doc = json.loads(CLASSES.read_text())
    return {"classes": doc["classes"], "pass": tuple(doc["pass"])}


def class_of(name: str, cls: dict | None = None) -> str | None:
    """The class whose patterns match `name`, or None (unclassed). The home class is exact names."""
    cls = cls or classes()
    for c, pats in cls["classes"].items():
        if any(fnmatch.fnmatchcase(name, p) for p in pats):
            return c
    return None


def build(inherited: dict, home: Path, agent: str | None = None, cls: dict | None = None) -> dict:
    """The environment for an org process at `home`: the PASS-class names of `inherited`, plus the home class.
    Pure but for reading HOME/.env (the DSN); never prints a value."""
    from astryx import config
    cls = cls or classes()
    out = {k: v for k, v in inherited.items() if class_of(k, cls) in cls["pass"]}
    out["ASTRYX_HOME"] = str(home)
    if agent:
        out["ASTRYX_AGENT"] = agent
    out["ASTRYX_DSN"] = config.dsn(Path(home) / ".env", environ={**out, "ASTRYX_DSN": ""}, env_first=False)
    return out


def _main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="orgenv")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("exec")
    ex.add_argument("--home", required=True)
    ex.add_argument("--agent")
    ex.add_argument("command", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        print("orgenv exec: no command", file=sys.stderr)
        return 2
    from astryx import orgs
    home = Path(a.home).resolve()
    try:
        if orgs.org_of(home) is None:
            print(f"orgenv exec: {home} is no registered org's HOME", file=sys.stderr)
            return 2
        env = build(dict(os.environ), home, a.agent)
    except (LookupError, RuntimeError) as e:
        print(f"orgenv exec: {e}", file=sys.stderr)
        return 2
    os.execvpe(cmd[0], cmd, env)


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
