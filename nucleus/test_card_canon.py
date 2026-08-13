#!/usr/bin/env python3
"""A2A card canonicalisation invariants — the committed guard against a silent revert.

SCOPE, STATED HONESTLY: this file cannot prove the served card is spec-conformant, and it
does not try. Proving that requires re-deriving the SERVED bytes with an implementation
that shares no code with the signer — that is nucleus/card_assert.py check (iv), which uses
third-party rfc8785 and runs against the live gateway (hourly, via steward's tier_drift).

What this file does, needing no running org and no pip (pure stdlib, so it runs in CI):
  1. pins the RFC 8785 facts that make the flags load-bearing, against LITERAL expected
     bytes — ground truth from the RFC, not from anything astryx emits;
  2. asserts the emitter's SOURCE still carries them, so a revert fails CI instead of
     silently going out over the wire and reading as SIGNATURE INVALID to every peer.

Why it exists: check (iv) passed every hour while the card was unverifiable to the world,
because it re-canonicalised with the signer's own json.dumps — proving conformance-to-self.
Three em-dashes in `description` went out as \\uXXXX escapes; a peer reconstructing under
JCS got 1654 bytes where we signed 1663, which reads not as "unsigned" but as SPOOFED.

    venv/bin/python nucleus/test_card_canon.py     (also run by nucleus/check.sh)
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATEWAY = REPO / "bridges" / "gateway.py"

fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(f"{label}{': ' + detail if detail else ''}")


# ---------------------------------------------------------------- 1. RFC 8785 ground truth
# A card-shaped fixture carrying the exact hazard: a non-ASCII character in a description,
# and a rank, which is the card's only numeric field (int or null — never a float).
FIXTURE = {"description": "metadata only — never content", "name": "astryx", "rank": 1}

# Expected canonical form, written out from RFC 8785 rather than computed by us:
#   §3.2.3 keys sort by UTF-16 code unit;  §3.2.2.2 only ", \\ and C0 are escaped, so the
#   em-dash is literal UTF-8 (\xe2\x80\x94);  §3.2.2.3 numbers use ECMAScript Number::toString.
EXPECTED = b'{"description":"metadata only \xe2\x80\x94 never content","name":"astryx","rank":1}'

emitted = json.dumps(FIXTURE, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
check("(1a) the emitter's serialisation is JCS for a non-ASCII card fixture",
      emitted == EXPECTED, f"got {emitted!r}")

# The defect, pinned: the old construction diverges on exactly this input. If these ever
# match, the fixture stopped exercising the hazard and this test has gone vacuous.
old = json.dumps(FIXTURE, sort_keys=True, separators=(",", ":")).encode()
check("(1b) ensure_ascii=True still diverges (fixture exercises the hazard)",
      old != EXPECTED and b"\\u2014" in old, f"got {old!r}")

# Where this WOULD rot next, pinned as a live fact rather than a comment: stdlib renders a
# float as "1.0" where JCS requires "1". The card has no float today, and _assert_jcs_safe
# in the gateway refuses to sign one — (2j) below proves that guard is still there.
check("(1c) stdlib json is NOT a general JCS implementation (floats diverge)",
      json.dumps({"n": 1.0}, separators=(",", ":")) == '{"n":1.0}',
      "stdlib float rendering changed; re-check the JCS assumptions")

# ---------------------------------------------------------------- 2. the emitter's source
src = GATEWAY.read_text()

payload = re.search(r"payload = _b64u\(json\.dumps\(card,(.*?)\.encode\(\"utf-8\"\)\)", src, re.S)
check("(2a) the signed payload is JCS-serialised and UTF-8 encoded", payload is not None,
      "the _sign_card payload construction moved or dropped .encode(\"utf-8\") — re-point this test")
if payload:
    args = payload.group(1)
    check("(2b) signed payload sets ensure_ascii=False (JCS emits non-ASCII literally)",
          "ensure_ascii=False" in args, f"args were: {args.strip()!r}")
    check("(2c) signed payload is sorted and compact",
          "sort_keys=True" in args and '","' in args, args.strip())

served = re.search(r"return json\.dumps\(card,(.*?)\)\.encode\(", src, re.S)
check("(2e) the SERVED bytes use the same JCS serialisation as the signature",
      served is not None and "ensure_ascii=False" in served.group(1),
      "served card diverges from the signed payload")

# A2A §8.4.1 rule 1: a plain (non-optional, non-REQUIRED) proto field at its default MUST be
# omitted from the canonical form. AgentExtension.required is a plain `bool` in a2a.proto, so
# sending `false` breaks a conformant verifier's reconstruction. capabilities.streaming and
# .pushNotifications are `optional bool` — explicitly-set defaults MUST be KEPT. Same rule,
# opposite answers; both directions are pinned here so neither gets "tidied" into the other.
check("(2f) AgentExtension.required is omitted, not sent as false",
      not re.search(r'"required":\s*False', src), "found a literal \"required\": False")
for f in ("streaming", "pushNotifications"):
    check(f"(2g) capabilities.{f} is still emitted (optional bool, explicitly set)",
          re.search(rf'"{f}":\s*False', src) is not None,
          "stripping it would violate §8.4.1 rule 1 for `optional` fields")

# §8.4.2: `kid` MUST be present, `typ` SHOULD be "JOSE".
check("(2h) protected header carries kid + typ", '"kid"' in src and '"typ": "JOSE"' in src)

# The independence property itself: the signer must never import the verifier's canonicaliser,
# or check (iv) silently reverts to proving conformance-to-self.
check("(2i) the gateway does NOT import the verifier's JCS library",
      not re.search(r"^\s*(import|from)\s+rfc8785", src, re.M),
      "gateway imports rfc8785 — check (iv) would prove conformance-to-SELF again")

# The two divergences stdlib json cannot express are refused at the boundary rather than
# left to be detected after they ship (see (1c)).
check("(2j) the signer refuses card shapes stdlib cannot canonicalise",
      "_assert_jcs_safe(card)" in src and "def _assert_jcs_safe" in src,
      "the float / astral-key guard is gone — stdlib would silently sign non-JCS bytes")

if fails:
    print("CARD CANONICALISATION INVARIANTS FAILED:", file=sys.stderr)
    for f in fails:
        print(f"  ✗ {f}", file=sys.stderr)
    sys.exit(1)
print("card canonicalisation: JCS bytes pinned to RFC 8785, emitter source holds, "
      "signer/verifier independence intact ✓")
