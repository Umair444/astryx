"""The ONE text normalisation, shared by the static inventory and the runtime shim.

Both sides must transform a query identically, or a site and its execution never meet. So there is exactly
one function, and both import it.
"""
import re

# asyncpg `$1`, psycopg `%(name)s` and `%s` all become `?`. `%%` (psycopg's escaped percent) is left alone:
# the source literal and the string handed to execute() carry it identically.
_PLACEHOLDER = re.compile(r"\$\d+|%\([A-Za-z_]\w*\)s|%s")
_SPACE = re.compile(r"\s+")
# A statement is a SQL SITE when its first keyword is one of these. The same set a1 measured with (T1).
# A keyword followed by a HYPHEN is a CLI argv literal ("merge-base", "update-index"), not SQL (steward #26944).
# Exclude exactly that. A hand-made follower set would also drop real SQL (SELECT*FROM, select"c", SELECT/*h*/1),
# silently, from the inventory AND the trace at once (a3 #29426).
_SITE = re.compile(r"^\s*(select|insert|update|delete|with|merge)\b(?!-)", re.I)
# A literal that is the VERB ALONE (a trailing `;` allowed) is no statement a driver would run: `attr == "insert"`,
# a keymap's "delete", a `head in ("select", "with")` allowlist (plan-10107, a1 #50598 F2: exactly one token, never a
# keyword list, which would drop `select 1` and the AGE graph-DDL selects).
_BARE = re.compile(r"^\s*(select|insert|update|delete|with|merge)\s*;?\s*$", re.I)
FORMS = ("statement", "head")
# WRITE is classified CONSERVATIVELY (#21938): a DML keyword ANYWHERE, word-bounded. A data-modifying CTE leads
# with WITH, and Postgres's command tag calls it SELECT. Misclassifying something as a write only removes
# public credit.
_WRITE = re.compile(r"\b(insert|update|delete|merge)\b", re.I)


def norm(text: str) -> str:
    return _SPACE.sub(" ", _PLACEHOLDER.sub("?", text)).strip().lower()


def is_site(text: str, *, form: str) -> bool:
    """Is `text` SQL? Two questions, and every caller says which (plan-10107 D2; no default, so a new caller can't
    inherit the wrong one):
      form="statement"  a COMPLETE text: a resolved literal, an executed statement. The bare verb is not a site.
      form="head"       the HEAD of a composed string (`"DELETE " + tbl`, f"SELECT {cols}"): the verb alone, plus a
                        dynamic rest, may be SQL. Exactly the old predicate.
    """
    if form not in FORMS:
        raise ValueError(f"is_site: form must be one of {FORMS}, not {form!r}")
    t = text or ""
    if not _SITE.match(t):
        return False
    return form == "head" or not _BARE.match(t)


def is_bare_verb(text: str) -> bool:
    """A statement-form drop: the verb alone. The inventory classifies such a literal by its USE (plan-10107 D5)."""
    return bool(_SITE.match(text or "")) and bool(_BARE.match(text or ""))


def is_write(text: str) -> bool:
    return bool(_WRITE.search(text or ""))
