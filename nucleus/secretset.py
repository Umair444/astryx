"""The org's ONE answer to "what is secret here?" (plan-5497 S0).

Every consumer imports it, never copies it: step.py's writer redaction, the PreToolUse guard,
the at-rest sweeper and plan-4918's branch_check precondition. Four hand-kept lists would drift
apart; this derives the set from the holders themselves, at the moment of use.

POLARITY (fail-safe): every .env value is a secret unless its KEY is on NOT_SECRET. A new key
nobody classified is therefore guarded, never exposed. A URL value is not secret as a whole: its
password and its query values are (a DSN's host and database are config, a capability URL's
`key=` is not).

  secret_set()  -> [Secret(name, value, forms)]   .env ∪ ~/.pgpass passwords, raw + URL-encoded
  redact(obj)   -> obj with every form replaced by "[redacted:<name>]", walking str/list/dict
  scan(text)    -> {name: count}, never a value
  holders()     -> the declared holder manifest (nucleus/secret_holders.json)
  undeclared()  -> secret-bearing files under the manifest's scan_roots that it does not list

A value shorter than MIN_LEN is not matched (a 4-char "secret" would redact ordinary words). It
is REPORTED by unguardable(), not silently dropped. Nothing here ever prints a value.
"""
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env"
PGPASS_FILE = Path(os.environ.get("PGPASSFILE") or Path.home() / ".pgpass")
MIN_LEN = 8

# Keys whose values are configuration, not credentials. Adding a key here is a claim that its
# value grants nothing; the oracle holds every such value to "contains no secret".
NOT_SECRET = frozenset({
    "WA_CLI", "WA_DATA_HOST", "WA_DATA_CTR", "ASTRYX_ORG", "ASTRYX_URL", "TG_API_BASE",
    "GROWBOT_BODY_URL", "ASTRYX_NODE",
    "GMAIL_ADDRESS",        # an identifier (tier question, not a credential): see plan-5497 BC-b
    # a URL query value is secret by default; these name ONE parameter ("<KEY>:<param>") whose
    # value is an ordinary word (it appears in the tree's own code) and grants nothing
    "AUTOREMOTE_GETLOC_URL:message",
})


# URL keys whose URL is CONFIGURATION (host, port, database): the URL is not guarded whole, but its
# password and query values still are. Every OTHER URL key is guarded whole, plus its parts: a token
# can sit in a path (a webhook) or in the userinfo username, and "no password, no query" is not
# evidence of "no secret" (a2 #28956 B1). After S1c these DSNs carry no password at all.
URL_CONFIG = frozenset({"ASTRYX_DSN", "GEOLOC_DSN", "OBSERVER_DSN"})


class Secret(NamedTuple):
    name: str               # "ASTRYX_DSN:password", "OPENAI_API_KEY", "pgpass:localhost:5432:*:genesis"
    value: str
    forms: tuple            # the byte-for-byte spellings a copy can take


def _forms(v: str) -> tuple:
    # raw, URL-encoded (a DSN), and JSON-escaped (a transcript line doubles a backslash)
    out = {v, urllib.parse.quote(v, safe=""), urllib.parse.quote_plus(v), json.dumps(v)[1:-1]}
    return tuple(sorted(f for f in out if f))


def _env_pairs(path) -> list[tuple[str, str]]:
    pairs = []
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        pairs.append((k, v))
    return pairs


def _url_parts(k: str, v: str) -> list[tuple[str, str]] | None:
    """The secret parts of a URL value, or None when v is not a URL."""
    if "://" not in v:
        return None
    p = urllib.parse.urlsplit(v)
    out = []
    if p.password:
        out.append((f"{k}:password", urllib.parse.unquote(p.password)))
    for qk, qv in urllib.parse.parse_qsl(p.query, keep_blank_values=False):
        out.append((f"{k}:{qk}", qv))
    return out


def _pgpass_pairs(path) -> list[tuple[str, str]]:
    out = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # host:port:db:user:password — ':' and '\' are backslash-escaped inside fields
        fields = re.split(r"(?<!\\):", line, maxsplit=4)
        if len(fields) == 5:
            pw = fields[4].replace("\\:", ":").replace("\\\\", "\\")
            out.append(("pgpass:" + ":".join(fields[:4]), pw))
    return out


def _raw(env_file=None, pgpass_file=None) -> list[tuple[str, str]]:
    """(name, value) for every secret the holders declare. Raises if .env is unreadable: the
    CALLER picks the polarity (a writer drops what it can't clean; a guard allows and logs)."""
    pairs = []
    for k, v in _env_pairs(env_file or ENV_FILE):
        if k in NOT_SECRET or not v:
            continue
        parts = _url_parts(k, v)
        if parts is None:
            pairs.append((k, v))
        else:
            # FAIL-SAFE (a2 #28956 B1): an unclassified URL is guarded WHOLE, and its password and
            # query values too (so a copy of just the token is caught). Only a URL_CONFIG key gives
            # up whole-URL guarding, and only that: its password and query values stay guarded.
            if k not in URL_CONFIG:
                pairs.append((k, v))
                u = urllib.parse.urlsplit(v).username
                if u:                                     # a token as the userinfo username
                    pairs.append((f"{k}:username", urllib.parse.unquote(u)))
            pairs.extend((n, pv) for n, pv in parts if n not in NOT_SECRET)
    pp = Path(pgpass_file or PGPASS_FILE)
    if pp.exists():
        pairs.extend(_pgpass_pairs(pp))
    return pairs


def secret_set(env_file=None, pgpass_file=None) -> list[Secret]:
    """Every guardable secret, longest first (so a secret containing another redacts whole).
    Same value under two names (GEOLOC_DSN and ASTRYX_DSN share a password) is kept once, under
    the first name."""
    seen, out = set(), []
    for name, v in _raw(env_file, pgpass_file):
        if len(v) < MIN_LEN or v in seen:
            continue
        seen.add(v)
        out.append(Secret(name, v, _forms(v)))
    return sorted(out, key=lambda s: -len(s.value))


def unguardable(env_file=None, pgpass_file=None) -> list[str]:
    """Names of declared secrets too short to match safely. Reported, never silently dropped."""
    return sorted({n for n, v in _raw(env_file, pgpass_file) if v and len(v) < MIN_LEN})


def marker(name: str) -> str:
    return f"[redacted:{name}]"


def redact(obj, secrets=None):
    """obj with every form of every secret replaced by its marker. Walks str / list / tuple /
    dict (keys too). Anything else is returned as is."""
    secrets = secret_set() if secrets is None else secrets
    pairs = [(f, marker(s.name)) for s in secrets for f in s.forms]
    pairs.sort(key=lambda p: -len(p[0]))

    def walk(o):
        if isinstance(o, str):
            for f, m in pairs:
                if f in o:
                    o = o.replace(f, m)
            return o
        if isinstance(o, dict):
            return {walk(k): walk(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return type(o)(walk(x) for x in o)
        return o

    return walk(obj)


def scan(text: str, secrets=None) -> dict[str, int]:
    """{secret name: occurrences} in text. Counts only; a value is never returned."""
    secrets = secret_set() if secrets is None else secrets
    out = {}
    for s in secrets:
        n = sum(text.count(f) for f in s.forms)
        if n:
            out[s.name] = n
    return out


HOLDERS_FILE = Path(__file__).resolve().parent / "secret_holders.json"


def holders(path=None) -> dict:
    return json.loads(Path(path or HOLDERS_FILE).read_text())


def _expand(p: str, root: Path = REPO) -> list[Path]:
    import fnmatch
    import glob
    p = os.path.expanduser(p.replace("{uid}", str(os.getuid())))
    p = p if os.path.isabs(p) else str(root / p)
    if "**" not in p:
        return [Path(x) for x in sorted(glob.glob(p))]
    # walk WITHOUT following symlinks: a scratch tree links venv/ and the estate in, and a glob
    # that followed them would scan the whole org (and call a link to a holder a copy)
    base, _, pat = p.partition("**")
    pat = pat.lstrip("/")
    out = []
    for dp, dns, fns in os.walk(base or "/", followlinks=False):
        for n in fns:
            if fnmatch.fnmatch(n, pat):
                out.append(Path(dp) / n)
    return sorted(out)


def undeclared(secrets=None, manifest=None, root: Path = REPO) -> dict[str, list[str]]:
    """{file: [secret names]} for every file under scan_roots that holds a secret but is not a
    declared holder. Names only. This is the independent reading the manifest is checked against:
    the manifest is what we SAY; this is what the disk HOLDS."""
    secrets = secret_set() if secrets is None else secrets
    m = manifest or holders()
    declared = {str(x) for h in m["holders"] + m.get("expiring", [])
                for x in _expand(h["path"], root)}
    declared |= {str(Path(x).resolve()) for x in declared}
    out = {}
    for pattern in m["scan_roots"]:
        for f in _expand(pattern, root):
            if not f.is_file() or str(f) in declared:
                continue
            if f.is_symlink() and str(f.resolve()) in declared:
                continue                                  # a link to a holder is not a copy
            try:
                hits = scan(f.read_text(errors="replace"), secrets)
            except OSError:
                continue
            if hits:
                out[str(f)] = sorted(hits)
    return out


UNIT_DIRS = (REPO / "units", Path("/etc/systemd/system"), Path.home() / ".config/systemd/user")


def env_file_units(secrets=None) -> dict[str, list[str]]:
    """{"unit-env:<unit>": [secret names]} for every systemd unit whose EnvironmentFile holds a
    declared secret. Such a unit's PROCESS ENVIRON is a holder (readable at /proc/<pid>/environ
    by this uid), and a file scan can't see it (a2 #28956 B2)."""
    secrets = secret_set() if secrets is None else secrets
    out = {}
    for d in UNIT_DIRS:
        if not d.is_dir():
            continue
        for u in sorted(d.glob("*.service")):
            try:
                text = u.read_text(errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if not line.startswith("EnvironmentFile="):
                    continue
                f = Path(os.path.expanduser(line.split("=", 1)[1].strip().lstrip("-")))
                try:
                    hits = scan(f.read_text(errors="replace"), secrets) if f.is_file() else {}
                except OSError:
                    hits = {}
                if hits:
                    out.setdefault(f"unit-env:{u.name}", [])
                    out[f"unit-env:{u.name}"] = sorted(set(out[f"unit-env:{u.name}"]) | set(hits))
    return out


def undeclared_unit_envs(secrets=None, manifest=None) -> dict[str, list[str]]:
    m = manifest or holders()
    declared = {h["path"] for h in m["holders"] + m.get("expiring", [])}
    return {k: v for k, v in env_file_units(secrets).items() if k not in declared}


def derived_drift(manifest=None, root: Path = REPO) -> dict[str, list[str]]:
    """{holder: [keys whose value differs from their source]} for every holder that declares
    `derived_from`. A hand-derived copy with no writer is a second authority: this makes its drift
    loud. Values are compared in-process and never returned (a2 #29236)."""
    m = manifest or holders()
    out = {}
    for h in m["holders"] + m.get("expiring", []):
        for src, keys in (h.get("derived_from") or {}).items():
            copies = _expand(h["path"], root)
            sources = _expand(src, root)
            if not copies or not sources:
                out[h["path"]] = [f"missing {'copy' if not copies else 'source'}"]
                continue
            have = dict(_env_pairs(copies[0]))
            want = dict(_env_pairs(sources[0]))
            bad = sorted(k for k in keys if have.get(k) != want.get(k) or k not in want)
            if bad:
                out[h["path"]] = bad
    return out
