"""Mutants for nucleus/release.py (plan-9139 S1a). Each is a wrong door the design names: an unknown tier that
releases wide, a cached membership, a guessed destination, a borrowed route, a caller-chosen thread, a bare hash,
an empty audience that passes, a pointer that traverses. The oracle is tests/test_release.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "nucleus" / "release.py"
ORACLE = REPO / "tests" / "test_release.py"
ENV = "RELEASE_SRC"
MUTANTS = {
    "R1 an unknown tier is unrestricted, not private":
        ('r = READERS.get(t, frozenset({OWNER}))', 'r = READERS.get(t)\n        if r is None:\n            continue'),
    "R2 an empty audience releases":
        ('if aud is UNKNOWN or not aud:', 'if aud is UNKNOWN:'),
    "R3 group membership is cached (read once per route)":
        ('            ids = list(members(channel, route.get("chat")))',
         '            _c = route.setdefault("_cache", list(members(channel, route.get("chat"))))\n            ids = _c'),
    "R4 a failed membership read counts as the owner":
        ('            return UNKNOWN\n        if not ids:', '            return frozenset({OWNER})\n        if not ids:'),
    "R5 a DM with no declared counterpart is taken as the owner's":
        ('return frozenset({OWNER}) if route.get("counterpart") == OWNER else UNKNOWN', 'return frozenset({OWNER})'),
    "R6 the door borrows any agent's owner-only route":
        ('        if route.get("agent") != sender:\n            continue\n', ''),
    "R7 two owner-only routes: the door picks the first":
        ('    if len(ok) > 1:\n        raise Refused', '    if False:\n        raise Refused'),
    "R8 the body MAC is a bare sha256":
        ('    return _mac(key, "body", body)', '    return hashlib.sha256(body.encode()).hexdigest()'),
    "R9 the stamp omits the label":
        ('return _mac(key, "stamp", str(int(row_id)), rkey, _label_text(lbl))', 'return _mac(key, "stamp", str(int(row_id)), rkey)'),
    "R10 a labelled agent send keeps the caller's thread":
        ('th = inbound_thread if (inbound_thread and thread == inbound_thread) else f"tier-{sender}"', 'th = str(thread)'),
    "R11 a labelled agent send keeps the caller's intent":
        ('"intent": intent if intent in INTENTS else "chat"', '"intent": intent'),
    "R12 a pointer is not validated before reading":
        ('        if not (all(_TIER_RE.fullmatch(t) for t in tier.split("+")) and _PTR_RE.fullmatch(ptr)):\n            raise Refused("malformed pointer")\n', ''),
    "R13 the body file is created world-readable":
        ('os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)', 'os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)'),
    "R14 no key falls back to a fixed one":
        ('        raise Refused(f"no {MAC_KEY_ENV}', '        return b"x" * 32\n        raise Refused(f"no {MAC_KEY_ENV}'),
}
