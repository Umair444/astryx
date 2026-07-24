#!/usr/bin/env python3
"""Hermetic tests for the contacts MCP — lock the @lid resolution and, above all,
the personal-tier invariant: NO output ever carries a raw phone number.

No docker, no live wacli, no session.db: `_wacli` is faked and the lid_map is
stubbed. Run with `pytest`, or directly: `python test_server.py`.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "csrv", Path(__file__).with_name("server.py"))
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)

resolve = getattr(srv.contact_resolve, "fn", srv.contact_resolve)
search = getattr(srv.contact_search, "fn", srv.contact_search)

# ── a fake contact store, keyed like wacli's: contacts searchable by name or pn ──
AMMI = {"name": "Ammi", "phone": "923001112222", "jid": "923001112222@s.whatsapp.net"}
# a contact SAVED AS its own number — name == digits (the second leak vector)
NUMNAME = {"name": "923004445555", "phone": "923004445555",
           "jid": "923004445555@s.whatsapp.net"}
_STORE = [AMMI, NUMNAME]

_LIDMAP = {
    "79645890351312": "923001112222",   # → Ammi
    "88888888888888": "923004445555",   # → number-named contact
    "77777777777777": "923009998888",   # → a pn with NO contact row
}


def _install():
    def fake_wacli(_action, query):
        q = query.split("@")[0]
        return [c for c in _STORE
                if q and (q == c["phone"] or q in c["jid"].split("@")[0]
                          or q.lower() in c["name"].lower())]
    srv._wacli = fake_wacli
    srv._lidmap = dict(_LIDMAP)
    srv._load_lidmap = lambda: None      # a cache miss must never touch docker here
    import time
    srv._lidmap_at = time.monotonic()


_install()

NUM = re.compile(r"\d{7,}")              # a phone-length digit run = a leak


# ── the invariant: not one path may surface a number ─────────────────────────
def test_no_output_ever_contains_a_number():
    outputs = [
        resolve("79645890351312@lid"),          # known lid
        resolve("79645890351312:7@lid"),        # + :device suffix
        resolve("88888888888888@lid"),          # lid → number-named contact
        resolve("77777777777777@lid"),          # lid → pn with no contact row
        resolve("00000000000000@lid"),          # unknown lid
        resolve("@lid"),                        # empty
        resolve("923001112222"),                # direct phone
        resolve("923001112222@s.whatsapp.net"), # direct jid
        search("a"), search("92300"), search("Ammi"), search("zzz"),
    ]
    for o in outputs:
        assert not NUM.search(o), f"NUMBER LEAK in output: {o!r}"


# ── resolution behaviour ─────────────────────────────────────────────────────
def test_known_lid_resolves_to_name():
    assert resolve("79645890351312@lid") == "Ammi"


def test_device_suffix_stripped():
    assert resolve("79645890351312:7@lid") == "Ammi"


def test_number_named_contact_is_masked():
    assert resolve("88888888888888@lid") == "(contact saved by number)"


def test_lid_maps_to_pn_without_contact():
    out = resolve("77777777777777@lid")
    assert "unknown sender" in out and "recognized" in out


def test_unknown_lid_is_unknown():
    assert "unknown sender" in resolve("00000000000000@lid")


def test_empty_id_is_unknown_not_crash():
    assert "unknown sender" in resolve("@lid")


def test_direct_phone_and_jid_resolve():
    assert resolve("923001112222") == "Ammi"
    assert resolve("923001112222@s.whatsapp.net") == "Ammi"


def test_search_returns_names_no_match_message():
    assert search("Ammi") == "known contacts: Ammi"
    assert search("zzz") == "no matching contact"


def test_search_masks_number_named_contact():
    # querying the raw number finds the number-named contact; label must be masked
    assert "(contact saved by number)" in search("923004445555")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
