"""Is the estate a sqlguard ENTRY needs actually here? Stdlib only: this runs BEFORE any dependency import.

A committed-only tree (pushed_tree_check, CI, a fresh clone) has no .env, and pushed_tree_check runs it with a
bare `python3` that may lack psycopg. Either absence means nothing live can be observed, so the entry says
NOT SEARCHED (77) and names why. It never crashes to rc 1, which would read as a real failure. Absence only:
an unreadable .env still raises (loud). pulse_run stays strict, because production must never run without .env.
"""
import importlib.util
import sys


def absent(repo, deps=("psycopg",)):
    """Why an entry can't run on this tree, or None."""
    env = repo / ".env"
    if not env.is_file():
        return ".env absent (a committed-only tree has no live DSN)"
    if not any(l.startswith("ASTRYX_DSN=") for l in env.read_text().splitlines()):
        return ".env has no ASTRYX_DSN line"
    missing = [d for d in deps if importlib.util.find_spec(d) is None]
    if missing:
        return f"{', '.join(missing)} not importable by {sys.executable} (deps not installed here)"
    return None


def gate(name, repo, deps=("psycopg",)):
    why = absent(repo, deps)
    if why:
        print(f"  NOT SEARCHED: {why}")
        print(f"sqlguard {name}: rc=77 · RED 0 · reported 0 · not-searched 1")
        sys.exit(77)
