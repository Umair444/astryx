#!/usr/bin/env python3
"""Oracle for the org-identity boundary — can a stranger call itself one of us?

THE ATTACK, in one line: introduce as org="local", and every render that decides
internal-vs-foreign by `from_org === 'local'` prints your messages as a bare internal
agent name. Capability bounds still hold (clamped to seed, rate-capped, no grants) — what
breaks is the TRUST FRAMING, which is what the org's entire inbound defense rests on. An
agent cannot apply data-never-instructions to a body that does not look inbound.

Two independent layers, asserted separately, because each covers the other's gap:
  (1) THE DOOR — nucleus/orgname.py: a peer may not register a reserved or illegally
      shaped name. Prevention, but only go-forward: rows written before it predate it.
  (2) THE DERIVATION — channel/server.mjs PEER_ORG: internal-ness is derived from the
      absence of a `peers` row, which only a LOCAL decision writes, instead of from a
      string a peer can author. This holds even for rows that predate the door.

A door is a promise; a derivation is a property. The point of having both is that neither
is asked to be the only one.

    venv/bin/python nucleus/test_org_identity.py      (also run by nucleus/check.sh)
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nucleus.orgname import org_ok, peer_url_ok  # noqa: E402

fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(f"{label}{': ' + detail if detail else ''}")


# ---------------------------------------------------------------- (1) the door
check("'local' is refused — THE defect", not org_ok("local"),
      "a stranger could register the internal sentinel and render as a colleague")
for reserved in ("local",):
    check(f"reserved {reserved!r} refused in any case form",
          not org_ok(reserved.upper()) and not org_ok(reserved),
          "uppercase must fail on charset even if the reserved check is case-sensitive")

for bad, why in [
    ("", "empty"),
    ("-leading", "leading punctuation"),
    ("UPPER.com", "uppercase (would collide case-insensitively with a real host)"),
    ("has space", "space"),
    ("two\nlines", "NEWLINE — could forge a second wire header inside a rendered body"),
    ('quote"org', "double quote — breaks out of an attribute render"),
    ("<script>", "angle brackets"),
    ("bad\x00null", "NUL byte"),
    ("semi;colon", "shell/format punctuation"),
    ("x" * 81, "over the 80-char cap"),
]:
    check(f"refuses {why}", not org_ok(bad), f"org_ok({bad!r}) was True")

for good in ("umairfiaz.com", "arslans-macbook-pro", "a", "x" * 80, "org_1.example-2.net"):
    check(f"accepts legitimate {good[:24]!r}", org_ok(good),
          "a real peer must still be able to introduce itself")

# url: the one attacker-controlled field that had neither cast nor cap
check("absent url is allowed (NAT peer)", peer_url_ok(None) is None)
check("empty url is allowed", peer_url_ok("") is None)
check("http url accepted", peer_url_ok("http://a.example") == "http://a.example")
check("https url accepted", peer_url_ok("https://a.example") == "https://a.example")
for bad in ("ftp://a.example", "javascript:alert(1)", "file:///etc/passwd", "//a.example"):
    check(f"refuses url scheme {bad[:20]!r}", peer_url_ok(bad) is False)
check("url is capped, not unbounded", len(peer_url_ok("https://" + "a" * 9000)) == 200,
      "unbounded attacker text reached the peers table and a message body")
check("non-string url is cast", peer_url_ok(12345) is False, "a non-str url must not pass through")

# ---------------------------------------------------------------- (2) the derivation
SERVER = REPO / "channel" / "server.mjs"
raw_js = SERVER.read_text()


def strip_comments(src: str) -> str:
    """Scan CODE, not prose. The first run of this oracle failed on its own explanatory
    comment, which names the very pattern it forbids — the mirror of the defect the org
    already paid for twice (a check that passed because a COMMENT mentioned the right
    function; a fix that touched one of two paths a comment described). A comment can
    neither execute nor fail a build, so it must not be able to pass or fail one either."""
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("//", i):
            i = src.find("\n", i)
            if i < 0:
                break
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


js = strip_comments(raw_js)

check("no render decides internal-ness by comparing from_org to 'local'",
      not re.search(r"from_org\s*===\s*'local'", js),
      "found the string comparison this defect is made of — a sentinel sharing a "
      "namespace with attacker-controlled input is a guessable password, not a sentinel")
check("no render decides internal-ness by comparing to_org to 'local'",
      not re.search(r"to_org\s*===\s*'local'", js))
check("internal-ness is derived from the peers table",
      "FROM peers p WHERE p.org" in js,
      "PEER_ORG must consult `peers`, which only a local decision writes")
check("both render paths use the shared party() helper",
      js.count("party(") >= 4, "query_thread and read_message each render a from and a to")
check("names are control-char scrubbed before rendering",
      r"\x00-\x1f" in raw_js, "an org/agent name must not break the one-line render")

# ---------------------------------------------------------------- (3) live SQL semantics
def skip(why: str) -> None:
    print(f"  ○ live peers-predicate check skipped: {why}")
    _finish(partial=True)


def _finish(partial: bool = False) -> None:
    if fails:
        print("ORG-IDENTITY ORACLE FAILED:", file=sys.stderr)
        for f_ in fails:
            print(f"  ✗ {f_}", file=sys.stderr)
        sys.exit(1)
    if partial:
        # The door checks passed but the live peers-predicate did NOT run, so this is not
        # a pass — the unverified half is exactly where a regression would hide. 77 = SKIP
        # (automake convention); check.sh counts it UNVERIFIED and names it in the verdict.
        print("  ○ PARTIAL: the source-level door checks held, the live SQL semantics of "
              "the peers predicate were NOT verified this run")
        sys.exit(77)
    print("org identity: 'local' unclaimable at the door, url cast+capped+scheme-checked, "
          "internal-ness derived from peers (not from an authorable string) ✓")
    sys.exit(0)


try:
    import psycopg
except ImportError:
    skip("psycopg not importable")
try:
    dsn = next(l.split("=", 1)[1].strip()
               for l in (REPO / ".env").read_text().splitlines()
               if l.startswith("ASTRYX_DSN="))
    conn = psycopg.connect(dsn, connect_timeout=5)
except Exception as e:  # noqa: BLE001
    skip(f"no reachable org database ({type(e).__name__})")

# Extract the predicate from server.mjs and run it against real postgres, so the test
# cannot drift from the shipped SQL by quoting a copy of it here.
m = re.search(r"const PEER_ORG = `(.+?)`", raw_js, re.S)
check("PEER_ORG predicate is extractable", m is not None)
if m:
    pred = m.group(1)
    with conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO peers (org, pubkey, status, notes) "
                    "VALUES ('local','deadbeef','introduced','ORACLE FIXTURE') "
                    "ON CONFLICT (org) DO NOTHING")
        got = cur.execute(
            f"SELECT {pred} FROM (SELECT %s::text AS from_org) t", ("local",)).fetchone()[0]
        check("a PEER that claimed 'local' still renders as FOREIGN", got is True,
              "the pre-door row is exactly what the derivation exists to catch")
        conn.rollback()                       # the fixture peer never commits
    with psycopg.connect(dsn, connect_timeout=5) as c2:
        got = c2.execute(
            f"SELECT {pred} FROM (SELECT %s::text AS from_org) t", ("local",)).fetchone()[0]
        check("a genuine internal row renders as INTERNAL", got is False,
              "with no peer named 'local', from_org='local' must mean us")
        got = c2.execute(
            f"SELECT {pred} FROM (SELECT %s::text AS from_org) t",
            ("arslans-macbook-pro",)).fetchone()[0]
        check("a real introduced peer renders as FOREIGN", got is True)

_finish()
