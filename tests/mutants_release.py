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
        ('_mac(key, "stamp", str(int(row_id)), rkey, _label_text(lbl), str(pointer), str(bmac))',
         '_mac(key, "stamp", str(int(row_id)), rkey, str(pointer), str(bmac))'),
    "R15 the stamp omits the pointer (a swap on a stamped row delivers, a3 F1)":
        ('_mac(key, "stamp", str(int(row_id)), rkey, _label_text(lbl), str(pointer), str(bmac))',
         '_mac(key, "stamp", str(int(row_id)), rkey, _label_text(lbl), str(bmac))'),
    "R16 the door skips the body-MAC recompute on the resolved body":
        ('    if not hmac.compare_digest(body_mac(key, body), str(bmac)):', '    if False:'),
    "R17 get() ignores the stamped label's tier dir":
        ('        if tier != self.tier_dir(frozenset(lbl)):', '        if False:'),
    "R18 a reply keeps ANY inbound thread, a channel thread included (a3 F2)":
        ('and _ORG_THREAD_RE.fullmatch(str(inbound_thread))', ''),
    "R19 label() accepts a bare string (a3 F3)":
        ('    if isinstance(tiers, (str, bytes)):\n        raise Refused', '    if False:\n        raise Refused'),
    "R21 get() defaults to no label (any tier's body reads by omission, a3 MC-1)":
        ('    def get(self, pointer: str, lbl: frozenset) -> str:', '    def get(self, pointer: str, lbl: frozenset = None) -> str:'),
    "R20 an odd tier name is kept verbatim (the label encoding is no longer injective)":
        ('t if _TIER_RE.fullmatch(t) else UNKNOWN_TIER', 't'),
    "R10 a labelled agent send keeps the caller's thread":
        ('th = inbound_thread if keep else f"tier-{sender}"', 'th = str(thread)'),
    "R11 a labelled agent send keeps the caller's intent":
        ('"intent": intent if intent in INTENTS else "chat"', '"intent": intent'),
    "R12 a pointer is not validated before reading":
        ('        if not (all(_TIER_RE.fullmatch(t) for t in tier.split("+")) and _PTR_RE.fullmatch(ptr)):\n            raise Refused("malformed pointer")\n', ''),
    "R13 the body file is created world-readable":
        ('os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)', 'os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)'),
    "R14 no key falls back to a fixed one":
        ('        raise Refused(f"no {MAC_KEY_ENV}', '        return b"x" * 32\n        raise Refused(f"no {MAC_KEY_ENV}'),
}
