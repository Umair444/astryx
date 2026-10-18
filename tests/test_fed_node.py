#!/usr/bin/env python3
"""Oracle for plan-11324 S3e's ADDRESSING (src/astryx/federation/node.py): the cog as one federation node.

DB-FREE. node.py is loaded from FED_NODE_SRC (mutation_probe's seam), never by a bare import. Arms:
  ONE ORG: every path is the org's own (org None), and its public url is the install's base, unchanged.
  A COG: /o/<X>/… reaches X with the org-relative path; a bare path, an unknown org, a prefix-only org name and an
    org named by a longer path segment reach nothing; an empty (NAT) base stays empty.
  ADDRESSED: an envelope reaches only the org its signed `to` names (agent@X at X's door; agent@Y at X's refused;
    no agent, no @, a non-dict refused).
  SCOPED: a cog's rate and replay keys are per org; one org's keys are byte for byte today's.
Exit 0 pass · 1 fail.
"""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("FED_NODE_SRC") or REPO / "src" / "astryx" / "federation" / "node.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    print("S3e node addressing: one org, a cog, addressed, scoped")
    try:
        spec = importlib.util.spec_from_file_location("fed_node_under_test", SRC)
        N = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(N)
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  the subject loads ({type(e).__name__}: {e})")
        return 1

    for p in ("/astryx/inbox", "/astryx/identity", "/.well-known/agent-card.json", "/o/a/astryx/inbox"):
        check(f"one org: {p} is the org's own path, unchanged", N.route(p, None) == (None, p), str(N.route(p, None)))
    check("one org: the public url is the install's base (a trailing / dropped, as push() joins it)",
          N.public_url("https://x.example/", "a", False) == "https://x.example")

    cog = {"a", "b"}
    check("cog: /o/a/astryx/inbox reaches a at /astryx/inbox", N.route("/o/a/astryx/inbox", cog) == ("a", "/astryx/inbox"),
          str(N.route("/o/a/astryx/inbox", cog)))
    check("cog: /o/b/.well-known/agent-card.json reaches b's card",
          N.route("/o/b/.well-known/agent-card.json", cog) == ("b", "/.well-known/agent-card.json"))
    check("cog: /o/a alone reaches a at /", N.route("/o/a", cog) == ("a", "/"), str(N.route("/o/a", cog)))
    for p in ("/astryx/inbox", "/o/c/astryx/inbox", "/o//astryx/inbox", "/o/ab/astryx/inbox", "/oa/astryx/inbox", "/"):
        check(f"cog: {p} reaches no org", N.route(p, cog) is None, str(N.route(p, cog)))
    check("cog: a's public url is <base>/o/a", N.public_url("https://x.example/", "a", True) == "https://x.example/o/a")
    check("cog: a NAT'd install's url stays empty", N.public_url("", "a", True) == "")

    check("addressed: seed@a reaches a", N.addressed_to({"to": "seed@a"}, "a"))
    for e in ({"to": "seed@b"}, {"to": "seed"}, {"to": "@a"}, {"to": "seed@a@b"}, {}, "seed@a", None):
        check(f"addressed: {e!r} is refused at a", not N.addressed_to(e, "a"))

    check("scoped: one org's keys are today's", N.scoped(None, "inbox:p") == "inbox:p")
    check("scoped: a cog's keys differ per org", N.scoped("a", "inbox:p") != N.scoped("b", "inbox:p")
          and N.scoped("a", "inbox:p") != "inbox:p")
    print(f"{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
