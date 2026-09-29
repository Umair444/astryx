"""Driver-internal SQL (forge #23806, a3 #23986): statements a DRIVER composes from its OWN source constants, such
as asyncpg's pool reset ('SELECT pg_advisory_unlock_all();' 'CLOSE ALL;' 'UNLISTEN *;' 'RESET ALL;').

Frames can't tell them apart: repo `conn.execute(q)` and `pool.release()` both reach the wrapped method FROM
inside the driver (psycopg connection.py calls Cursor.execute; asyncpg pool.py calls con.fetchrow). Only the TEXT's
origin differs, so this uses the design's own axis, text provenance, extended to the driver side. The judge asks
only about a statement attribute() already called BLIND. That comes after the repo-literal owner (tier 1) and the
unresolved-site FALLBACK (tier 2), so any text a repo author can own is claimed before this runs.

The constant set is DERIVED by AST from the INSTALLED package (docstrings excluded), never listed by hand, so it
moves with the driver's version, and the version is printed with the count. A driver text composed at runtime
from constants plus values doesn't match, so it stays R-BLIND (the loud direction).
DECLARED RESIDUAL (a3 #23988): a repo caller the inventory doesn't see as SQL-bearing (its SQL arrives as a
parameter or from config) whose runtime text equals a driver constant reads driver-internal: COUNTED, not blind.
So the count is never proof that only the driver spoke.
"""
import ast
import importlib.metadata
import importlib.util
from functools import lru_cache
from pathlib import Path

from nucleus.sqlguard.inventory import _docstring_ids
from nucleus.sqlguard.normalize import norm


def _stmt(s: str) -> str:
    return norm(s).rstrip(";").strip()


@lru_cache(maxsize=None)
def constants(name: str) -> frozenset:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        return frozenset()
    out = set()
    for loc in spec.submodule_search_locations:
        for p in Path(loc).rglob("*.py"):
            try:
                tree = ast.parse(p.read_text(errors="replace"))
            except SyntaxError:
                continue
            docs = _docstring_ids(tree)
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                    s = _stmt(n.value)
                    if s:
                        out.add(s)
    return frozenset(out)


def version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "?"


def is_internal(text: str, name: str) -> bool:
    """EVERY ;-statement of the (normalized) text is a constant in the driver's own source."""
    parts = [p for p in (_stmt(x) for x in (text or "").split(";")) if p]
    lits = constants(name)
    return bool(parts) and all(p in lits for p in parts)
