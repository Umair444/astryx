#!/usr/bin/env python3
"""Oracle for plan-11324 S3e's ADDRESSING (src/astryx/federation/node.py): the cog as one federation node.

DB-FREE. node.py is loaded from FED_NODE_SRC (mutation_probe's seam), never by a bare import. Arms:
  ONE ORG: every path is the org's own (org None), and its public url is the install's base, unchanged.
  A COG: /o/<X>/… reaches X with the org-relative path; a bare path, an unknown org, a prefix-only org name and an
    org named by a longer path segment reach nothing; an empty (NAT) base stays empty.
  ADDRESSED: an envelope reaches only the org its signed `to` names (agent@X at X's door; agent@Y at X's refused;
    no agent, no @, a non-dict refused).
  SCOPED: a cog's rate and replay keys are per org; one org's keys are byte for byte today's.
  THE DOOR (seed #60376): a registry may name ONE door org (orgs.py, loaded from ORGS_SRC); two claimants refuse, a
    non-boolean refuses, a door on an org that isn't the primary refuses (seed #60780), none means no door. The door org answers at the bare root AND at /o/<door>; with no door a
    bare path reaches nothing; another org is never reached at the bare root.
Exit 0 pass · 1 fail.
"""
import importlib.util
import json
import os
import tempfile
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("FED_NODE_SRC") or REPO / "src" / "astryx" / "federation" / "node.py")
ORGS = Path(os.environ.get("ORGS_SRC") or REPO / "src" / "astryx" / "orgs.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def registry(N):
    spec = importlib.util.spec_from_file_location("orgs_under_test", ORGS)
    O = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(O)
    O.UNITS = REPO / "src" / "astryx" / "data" / "org_units.json"   # a relocated copy reads the checkout's units
    with tempfile.TemporaryDirectory() as d:
        reg = Path(d) / "orgs.json"
        env = {O.ENV: str(reg)}

        def write(a_door, b_door, primary=True):
            # a door is the primary's (seed #60780): an org given a door is the primary too, unless an arm says not,
            # so each refusal below is the one it names, never "a door that isn't the primary"
            e = {"a": {"home": f"{d}/a", "db": "org_a"}, "b": {"home": f"{d}/b", "db": "org_b"}}
            for k, v in (("a", a_door), ("b", b_door)):
                if v is not None:
                    e[k]["door"] = v
                    if v and primary:
                        e[k]["primary"] = True
            reg.write_text(json.dumps({"orgs": e}))

        write(True, None)
        check("door: a registry naming one door gives it", O.door(env) == "a", str(O.door(env)))
        write(None, None)
        check("door: a registry naming none gives None", O.door(env) is None)
        write(False, False)
        check("door: door false everywhere gives None", O.door(env) is None)
        for a, b, why, pr in ((True, True, "two orgs claim the door", True), ("yes", None, "a non-boolean door", True),
                              (True, None, "a door on an org that isn't the primary", False)):
            write(a, b, pr)
            try:
                O.load(env)
                check(f"door: {why} REFUSES (fail closed)", False, "loaded")
            except O.RegistryError:
                check(f"door: {why} REFUSES (fail closed)", True)
        check("door: no registry, no door (one org)", O.door({O.ENV: f"{d}/absent.json"}) is None)


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

    for to in ("seed@a@b", "seed@@b", "se@ed@b"):
        check(f"addressed: {to} has no reading, so it is refused at b too (a4 #60377 R-1)", not N.addressed_to({"to": to}, "b"))
    check("split_to: seed@a is (seed, a); one reader for the agent and the org", N.split_to("seed@a") == ("seed", "a"))
    check("split_to: two '@' have no reading", N.split_to("seed@a@b") is None)
    check("cog: a dot-dot segment reaches nothing", N.route("/o/a/../b/astryx/inbox", cog) is None)
    check("scoped: one org's keys are today's", N.scoped(None, "inbox:p") == "inbox:p")
    check("scoped: a cog's keys differ per org", N.scoped("a", "inbox:p") != N.scoped("b", "inbox:p")
          and N.scoped("a", "inbox:p") != "inbox:p")
    check("door: the door org answers at the bare root", N.route("/astryx/inbox", cog, "a") == ("a", "/astryx/inbox"),
          str(N.route("/astryx/inbox", cog, "a")))
    check("door: ...and at /o/<door>", N.route("/o/a/astryx/inbox", cog, "a") == ("a", "/astryx/inbox"))
    check("door: the other org is still reached only at its own /o/", N.route("/o/b/astryx/inbox", cog, "a") == ("b", "/astryx/inbox"))
    check("door: no door, a bare path reaches nothing", N.route("/astryx/inbox", cog, None) is None)
    check("door: a door the cog does not hold reaches nothing", N.route("/astryx/inbox", cog, "c") is None)
    check("door: a dot-dot segment on a bare path reaches nothing (a4 #60384)", N.route("/../x", cog, "a") is None)
    registry(N)
    print(f"{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
