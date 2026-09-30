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
# WRITE is classified CONSERVATIVELY (#21938): a DML keyword ANYWHERE, word-bounded. A data-modifying CTE leads
# with WITH, and Postgres's command tag calls it SELECT. Misclassifying something as a write only removes
# public credit.
_WRITE = re.compile(r"\b(insert|update|delete|merge)\b", re.I)


def norm(text: str) -> str:
    return _SPACE.sub(" ", _PLACEHOLDER.sub("?", text)).strip().lower()


def is_site(text: str) -> bool:
    return bool(_SITE.match(text or ""))


def is_write(text: str) -> bool:
    return bool(_WRITE.search(text or ""))
