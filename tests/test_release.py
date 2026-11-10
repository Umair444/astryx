#!/usr/bin/env python3
"""Oracle for src/astryx/security/release.py, the one door for personal-tier content (plan-9139 S1a).

Pure: no database, no bridge, no network. Every route and id below is a FIXTURE (synthetic jids, a synthetic key);
nothing here reads the live routes files. Arms, in the design's terms (v4 #45058 and the binding set #45071):
  LABEL      a label is a set of tiers; ORG is unrestricted; an UNKNOWN tier is private (owner only)
  AUDIENCE   derived from the route, a group's membership read LIVE on every call (never cached), and anything
             unestablished is UNKNOWN, which never releases
  KEYS       no key → refused; the stamp binds (row id, route key, label); the body MAC is keyed
  STORE      0600 files under a 0700 dir outside every home, never overwritten; a pointer can't traverse
  RELEASE    the destination is the sender's ONE owner-only route; the result carries no body and no chat id
  AGENT SEND a labelled member's agent-addressed row carries no caller-chosen string (a1 BC-2)
Exit 0 pass · 1 fail.
"""
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
sys.path.insert(0, str(REPO))
if os.environ.get("RELEASE_SRC"):                 # the mutation probe hands a mutated copy here
    import importlib.util
    _spec = importlib.util.spec_from_file_location("release_under_test", os.environ["RELEASE_SRC"])
    R = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(R)
    R.REPO = REPO
else:
    from astryx.security import release as R  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except R.Refused as e:
        return str(e)
    return None


KEY = b"k" * 40
SENT = "S1A-SENTINEL-body-7f3a"
DM = {"chat": "101@s.whatsapp.net", "agent": "canopus-career", "enabled": True, "counterpart": "owner"}
GROUP = {"chat": "901@g.us", "agent": "gemini-family", "enabled": True,
         "owner_ids": ["101@s.whatsapp.net"]}

print("label:")
check("ORG reads as unrestricted", R.readers(R.ORG) is None)
check("one tier → the owner", R.readers(R.label(["career"])) == {R.OWNER})
check("a mixed label intersects ({career, family} → the owner)", R.readers(R.label(["career", "family"])) == {R.OWNER})
check("an UNKNOWN tier is private: the owner only, never wider", R.readers(R.label(["zz_new"])) == {R.OWNER})
check("UNKNOWN audience never releases, under any label",
      not R.releasable(R.ORG, R.UNKNOWN) and not R.releasable(R.label(["career"]), R.UNKNOWN))
check("an EMPTY audience never releases (a door to nobody is a bug)", not R.releasable(R.label(["career"]), frozenset()))
check("an audience wider than the readers is refused",
      not R.releasable(R.label(["career"]), frozenset({R.OWNER, "outsider:1"})))

print("chat kind:")
check("WhatsApp: @g.us is a group, @s.whatsapp.net and @lid are DMs, anything else unknown",
      [R.chat_kind("whatsapp", c) for c in ("1@g.us", "1@s.whatsapp.net", "1@lid", "1@x")] ==
      ["group", "dm", "dm", "unknown"])
check("Telegram: a positive id is a private chat, a negative one a group, garbage unknown",
      [R.chat_kind("telegram", c) for c in ("12345", "-100123", "abc")] == ["dm", "group", "unknown"])
check("Discord routes are channels: groups", R.chat_kind("discord", "123") == "group")

print("audience:")
check("a DM whose counterpart is DECLARED owner → {owner}", R.audience("whatsapp", DM) == {R.OWNER})
check("a DM with no declared counterpart → UNKNOWN", R.audience("whatsapp", {**DM, "counterpart": None}) is R.UNKNOWN)
check("a disabled route → UNKNOWN", R.audience("whatsapp", {**DM, "enabled": False}) is R.UNKNOWN)
check("a group with no membership reader → UNKNOWN", R.audience("whatsapp", GROUP) is R.UNKNOWN)


def boom(ch, chat):
    raise RuntimeError("store locked")


check("a group whose membership read FAILS → UNKNOWN (the sync daemon's lock, S0)",
      R.audience("whatsapp", GROUP, boom) is R.UNKNOWN)
check("a group whose read returns nobody → UNKNOWN", R.audience("whatsapp", GROUP, lambda c, x: []) is R.UNKNOWN)
check("a group of only the owner's declared ids → {owner}",
      R.audience("whatsapp", GROUP, lambda c, x: ["101@s.whatsapp.net"]) == {R.OWNER})
calls = []
roster = [["101@s.whatsapp.net"], ["101@s.whatsapp.net", "199@s.whatsapp.net"]]


def live(ch, chat):
    calls.append(1)
    return roster[min(len(calls), 2) - 1]


a1 = R.audience("whatsapp", GROUP, live)
a2 = R.audience("whatsapp", GROUP, live)
check("membership is read LIVE on every call, never cached (a2's carried trip)", len(calls) == 2, f"calls={len(calls)}")
check("…so a member added between two releases is SEEN: the second is refused",
      R.releasable(R.label(["family"]), a1) and not R.releasable(R.label(["family"]), a2), f"{a1} {a2}")
check("an outsider principal carries no id (only its position)",
      all("199" not in p for p in a2), str(a2))

print("keys and MACs:")
check("no key in the env → Refused (no key, no door)", refused(R.mac_key, {}) is not None)
check("a key shorter than 32 chars → Refused", refused(R.mac_key, {R.MAC_KEY_ENV: "short"}) is not None)
check("a 32+ char key is accepted", R.mac_key({R.MAC_KEY_ENV: "x" * 32}) == b"x" * 32)
rk = R.route_key(KEY, "whatsapp", DM)
check("the route key carries no chat id", DM["chat"].split("@")[0] not in rk and len(rk) == 24)
lbl = R.label(["career"])
PA, MA = "career/" + "a" * 32, "m" * 64
st = R.stamp(KEY, 41, rk, lbl, PA, MA)
check("a stamp verifies for its own (row id, route key, label, pointer, body MAC)",
      R.verify_stamp(KEY, 41, rk, lbl, PA, MA, st))
check("…and fails for another row, route, label, key, pointer, body MAC, or an empty value (a3 F1)",
      not any([R.verify_stamp(KEY, 42, rk, lbl, PA, MA, st), R.verify_stamp(KEY, 41, "x" * 24, lbl, PA, MA, st),
               R.verify_stamp(KEY, 41, rk, R.label(["family"]), PA, MA, st),
               R.verify_stamp(b"j" * 40, 41, rk, lbl, PA, MA, st),
               R.verify_stamp(KEY, 41, rk, lbl, "career/" + "b" * 32, MA, st),
               R.verify_stamp(KEY, 41, rk, lbl, PA, "n" * 64, st), R.verify_stamp(KEY, 41, rk, lbl, PA, MA, "")]))
check("label() refuses a bare string (it would iterate to letters, a3 F3)", refused(R.label, "career") is not None)
check("a tier name outside [a-z0-9_] canonicalizes to 'unknown' (still private)",
      R.label(["a,b"]) == {R.UNKNOWN_TIER} and R.readers(R.label(["a,b"])) == {R.OWNER})
check("two distinct labels never give one stamp (the encoding is injective)",
      R.stamp(KEY, 1, rk, R.label(["a,b"]), PA, MA) != R.stamp(KEY, 1, rk, R.label(["a", "b"]), PA, MA))
check("the body MAC is KEYED: not a bare sha256, and another key gives another MAC",
      R.body_mac(KEY, "ok") != hashlib.sha256(b"ok").hexdigest() and R.body_mac(KEY, "ok") != R.body_mac(b"j" * 40, "ok"))

print("tier store:")
with tempfile.TemporaryDirectory() as td:
    store = R.TierStore(Path(td) / "store")
    p1, p2 = store.put(lbl, SENT), store.put(lbl, SENT)
    f1 = Path(td) / "store" / p1
    check("put → a pointer that round-trips the body", store.get(p1, lbl) == SENT)
    import inspect
    check("get()'s label has NO default: no caller reads across tiers by omission (a3 MC-1)",
          inspect.signature(store.get).parameters["lbl"].default is inspect.Parameter.empty)
    check("the body file is 0600 and its tier dir 0700",
          stat.S_IMODE(f1.stat().st_mode) == 0o600 and stat.S_IMODE(f1.parent.stat().st_mode) == 0o700,
          f"{oct(f1.stat().st_mode)} {oct(f1.parent.stat().st_mode)}")
    check("two puts of the same body are two files (never overwritten)", p1 != p2)
    check("a traversing pointer is refused", refused(store.get, "career/../../etc/passwd", lbl) is not None
          and refused(store.get, "../x/" + "a" * 30, lbl) is not None)
    check("a tier name outside [a-z0-9_] can't name a store dir (it becomes 'unknown')",
          store.put(R.label(["../x"]), "b").startswith("unknown/") and not (Path(td) / "x").exists())
    fam = store.put(R.label(["family"]), "fam-body")
    check("get(pointer, label) refuses a pointer from ANOTHER tier's dir",
          refused(store.get, p1, R.label(["family"])) is not None and store.get(fam, R.label(["family"])) == "fam-body")
    bm = R.body_mac(KEY, SENT)
    sv = R.stamp(KEY, 9, rk, lbl, p1, bm)
    check("open_stamped returns the body when stamp, tier dir and resolved-body MAC all agree",
          R.open_stamped(KEY, store, 9, rk, lbl, p1, bm, sv) == SENT)
    check("…refuses a POINTER swapped onto the stamped row", refused(R.open_stamped, KEY, store, 9, rk, lbl, p2, bm, sv)
          is not None)
    (Path(td) / "store" / p1).chmod(0o600)
    (Path(td) / "store" / p1).write_text("tampered")
    check("…refuses when the stored body was changed after release (the MAC is recomputed on the RESOLVED body)",
          refused(R.open_stamped, KEY, store, 9, rk, lbl, p1, bm, sv) is not None)
    fv = R.stamp(KEY, 9, rk, R.label(["family"]), p2, bm)
    check("…refuses a career body under a family stamp (the pointer's tier must be the label's)",
          refused(R.open_stamped, KEY, store, 9, rk, R.label(["family"]), p2, bm, fv) is not None)
default = R.TierStore().root.resolve()
check("the default store is under the repo's tier/, outside every home (a1 BC-1)",
      default.is_relative_to((ESTATE / "tier").resolve()) and not default.is_relative_to((ESTATE / "homes").resolve()))

print("release:")
with tempfile.TemporaryDirectory() as td:
    store = R.TierStore(Path(td) / "store")
    rfile = Path(td) / "routes.json"
    rfile.write_text(json.dumps([DM]))
    other_dm = {**DM, "agent": "someone-else", "chat": "102@s.whatsapp.net"}
    routes = [("whatsapp", DM, rfile), ("whatsapp", other_dm, rfile), ("whatsapp", GROUP, rfile)]
    out = R.release("canopus-career", lbl, SENT, routes, KEY, store)
    flat = json.dumps(out)
    check("the sender's one owner-only route is the destination", out["route_key"] == R.route_key(KEY, "whatsapp", DM))
    check("the result carries NO body and NO chat id", SENT not in flat and "101@s.whatsapp.net" not in flat, flat)   # the whole id: "101" alone could match MAC/pointer hex
    check("…but its pointer resolves to the body in the tier store", store.get(out["pointer"], lbl) == SENT)
    check("the result's KEY SET is exactly the metadata fields, so a future `chat`/`to` field fails (a3 #46038)",
          set(out) == {"pointer", "bytes", "body_mac", "channel", "route_key", "route_sha", "label"}, str(sorted(out)))
    check("…and the bare fixture number is absent from the non-crypto fields (channel, label, bytes)",
          "101" not in f"{out['channel']}|{out['label']}|{out['bytes']}")
    check("the audit fields are there: bytes, keyed body MAC, route-file sha, label",
          out["bytes"] == len(SENT) and out["body_mac"] == R.body_mac(KEY, SENT)
          and out["route_sha"] == hashlib.sha256(rfile.read_bytes()).hexdigest() and out["label"] == "career")
    check("a sender with no owner-only route of its own → Refused (another agent's DM is never borrowed)",
          refused(R.release, "gemini-family", lbl, SENT, routes, KEY, store, live) is not None)
    check("two owner-only routes for one sender → Refused (the door never guesses)",
          refused(R.release, "canopus-career", lbl, SENT, routes + [("telegram", {**DM, "chat": "777"}, rfile)],
                  KEY, store) is not None)
    check("an ORG-labelled body is not a release → Refused", refused(R.release, "canopus-career", R.ORG, SENT,
                                                                     routes, KEY, store) is not None)
    n_before = sum(1 for _ in (Path(td) / "store").rglob("*") if _.is_file())
    refused(R.release, "nobody", lbl, SENT, routes, KEY, store)
    n_after = sum(1 for _ in (Path(td) / "store").rglob("*") if _.is_file())
    check("a refused release writes NOTHING to the store", n_before == n_after, f"{n_before}→{n_after}")

print("agent send (a1 BC-2):")
plain = R.agent_send("seed", R.ORG, "steward", "plan-1", "task", SENT)
check("an ORG-labelled session's send passes through unchanged",
      plain == {"to": "steward", "thread": "plan-1", "intent": "task", "body": SENT})
row = R.agent_send("gemini-family", R.label(["family"]), "seed", "SENT-THREAD-do-this", "SENT-INTENT", SENT)
flat = json.dumps(row)
check("a labelled member's body, caller thread and caller intent are all ABSENT from the row",
      SENT not in flat and "SENT-THREAD" not in flat and "SENT-INTENT" not in flat, flat)
check("…the thread is derived (tier-<sender>) and the intent clamped to the enum",
      row["thread"] == "tier-gemini-family" and row["intent"] == "chat")
reply = R.agent_send("gemini-family", R.label(["family"]), "seed", "t-ab12cd", "receipt", SENT,
                     inbound_thread="t-ab12cd")
check("a reply on an ORG inbound thread keeps that thread (derived, not chosen)", reply["thread"] == "t-ab12cd"
      and reply["intent"] == "receipt")
chan = R.agent_send("gemini-family", R.label(["family"]), "seed", "wa:101@s.whatsapp.net", "chat", SENT,
                    inbound_thread="wa:101@s.whatsapp.net")
check("a reply on a CHANNEL inbound thread does NOT carry it onto the wire (a3 F2): tier-<sender>",
      chan["thread"] == "tier-gemini-family" and "101@s.whatsapp.net" not in json.dumps(chan))
odd = R.agent_send("gemini-family", R.label(["family"]), "seed", "zz:anything", "chat", SENT, inbound_thread="zz:anything")
check("…and an UNLISTED prefix fails closed the same way (an allowlist, not a channel list)",
      odd["thread"] == "tier-gemini-family")
check("every derived string is within the metadata cap",
      all(len(str(v)) <= R.METADATA_CAP for k, v in row.items() if k != "to"))

print(f"\n{'FAIL: ' + str(len(fails)) + ' arm(s)' if fails else 'ALL PASS'}")
sys.exit(1 if fails else 0)
