"""Is the estate a sqlguard ENTRY needs actually here? Stdlib only: this runs BEFORE any dependency import.

ABSENT and BROKEN get different exit codes (a3 #22659), and the ESTATE decides which applies, because it's the
authority the judge already uses for the same question:
- triggers/ absent means a committed-only tree (pushed_tree_check, CI, a fresh clone). A missing .env or dep is
  expected there, so it's NOT SEARCHED (77), with the reason named.
- triggers/ present means a live host. A missing .env or dep there is the runner losing its world (PY=python3, a
  broken venv, a minimal systemd env), so it's rc 1, loud. A 77 there has no clock, so it would be the guard
  switched off quietly.
- A PRESENT .env without ASTRYX_DSN is misconfiguration on any tree, so it's rc 1.
Deps are probed with find_spec, not imported, so a present-but-BROKEN psycopg still crashes loud. pulse_run
stays strict, because production must never run without .env.
"""
import importlib.util
import sys


def absent(repo, deps=("psycopg",)):
    """(rc, why) when an entry can't run on this tree, else None. rc 77 = absent here; rc 1 = broken."""
    env = repo / ".env"
    live = (repo / "triggers").is_dir()
    miss = None
    if not env.is_file():
        miss = ".env absent"
    elif not any(l.startswith("ASTRYX_DSN=") for l in env.read_text().splitlines()):
        return 1, ".env is present but has no ASTRYX_DSN line (a misconfigured host, not an absent one)"
    else:
        missing = [d for d in deps if importlib.util.find_spec(d) is None]
        if missing:
            miss = f"{', '.join(missing)} not importable by {sys.executable}"
    if miss is None:
        return None
    if live:
        return 1, f"{miss}, on a LIVE host (triggers/ present): the runner lost its estate"
    return 77, f"{miss} (a committed-only tree: triggers/ absent)"


def gate(name, repo, deps=("psycopg",)):
    got = absent(repo, deps)
    if got:
        rc, why = got
        print(f"  {'NOT SEARCHED' if rc == 77 else 'BROKEN'}: {why}")
        print(f"sqlguard {name}: rc={rc} · RED {int(rc == 1)} · reported 0 · not-searched {int(rc == 77)}")
        sys.exit(rc)
