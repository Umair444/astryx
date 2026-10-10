#!/usr/bin/env python3
"""Oracle for nucleus/pg_design.py: the RUNNING postgres matches its declared design, infra/pg (owner 10-10: "the design
on github should match local"; steward F4, plan seed #42759).

  STATIC     the compose file's container_name IS nucleus/pgcontainer.sh's PG_CONTAINER; its port is loopback only; its
             command carries max_connections; the Dockerfile pins AGE to a 40-hex commit (never a moving master) and
             declares the extension versions it carries.
  RED        on synthetic inspect/server records, each drift is named in its own class: a LAN bind, another image, a
             setting whose effective value differs, an extension version that differs, no declared versions, a helper
             name that disagrees. A matching record is green, and an out-of-scope database's mismatch is REPORTED only.
  LIVE       the running server matches (read-only); the setting's SOURCE is reported, never judged.
Exit 0 pass · 1 fail · 77 could not observe the live server (the static and RED arms still ran).
"""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

if os.environ.get("PG_DESIGN_SRC"):                       # mutation_probe hands a mutant copy here
    import importlib.util
    _spec = importlib.util.spec_from_file_location("nucleus.pg_design", os.environ["PG_DESIGN_SRC"])
    P = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(P)
else:
    from nucleus import pg_design as P                    # noqa: E402

fails, skips = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


print("static:")
compose, dockerfile = P.COMPOSE.read_text(), P.DOCKERFILE.read_text()
want = P.declared(compose, dockerfile)
check("compose's container_name IS pgcontainer.sh's PG_CONTAINER (every docker fallback names the declared server)",
      P.helper_container(P.HELPER.read_text()) == want["container"], f"{want['container']}")
import yaml as _yaml
check("the compose PROJECT name is pinned to `pg` (so its network stays pg_default wherever the file lives; seed #43418)",
      _yaml.safe_load(compose).get("name") == "pg", str(_yaml.safe_load(compose).get("name")))
check("the published port is LOOPBACK ONLY (127.0.0.1:5432:5432, and nothing else)",
      want["ports"] == ["127.0.0.1:5432:5432"], str(want["ports"]))
check("max_connections is DECLARED in the compose command (never only in the data dir)",
      want["settings"].get("max_connections", "").isdigit(), str(want["settings"]))
m = re.search(r"^ARG AGE_REF=([0-9a-f]+)$", dockerfile, re.M)
check("the Dockerfile pins AGE to a 40-hex commit and checks it out (a moving master can't match local)",
      bool(m) and len(m.group(1)) == 40 and 'git checkout --detach "$AGE_REF"' in dockerfile
      and "--depth 1" not in dockerfile, m.group(0) if m else "no AGE_REF")
check("the Dockerfile declares the extension versions it carries (age, vector, postgis)",
      set(want["versions"]) == {"age", "vector", "postgis"}, str(want["versions"]))

pins = dict(re.findall(r"postgresql-18-(pgvector|postgis-3)=(\d+\.\d+\.\d+)", dockerfile))
check("the apt packages are PINNED, to exactly the versions the labels declare (a1 #43407: unpinned, a fresh build "
      "installed pgvector 0.8.7 under a 0.8.6 label)", pins.get("pgvector") == want["versions"].get("vector")
      and pins.get("postgis-3") == want["versions"].get("postgis"), f"{pins} vs {want['versions']}")
check("the base image is pinned by digest (the tag moves)",
      len(re.findall(r"^FROM postgres:18-bookworm@sha256:[0-9a-f]{64}", dockerfile, re.M)) == 2)

print("red, on synthetic records:")
TAG_ID = "sha256:" + "a" * 64
OK_INSPECT = {"Config": {"Image": want["image"], "Cmd": ["postgres"]}, "Image": TAG_ID,
              "HostConfig": {"PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}]}}}
OK_SHOW = {k: (v, "command line") for k, v in want["settings"].items()}
OK_EXT = [("astryx", P.EXT_NAME[n], v) for n, v in want["versions"].items()]
H = want["container"]
g = P.compare(want, OK_INSPECT, OK_SHOW, OK_EXT, H, TAG_ID)
check("a matching record is GREEN (the comparison has a green)", g["drift"] == [], str(g))
lan = {**OK_INSPECT, "HostConfig": {"PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"},
                                                                 {"HostIp": "192.168.1.5", "HostPort": "5432"}]}}}
d = P.compare(want, lan, OK_SHOW, OK_EXT, H, TAG_ID)["drift"]
check("a LAN bind beside loopback → PORTS drift (#5497's unbind can't silently return)",
      len(d) == 1 and d[0].startswith("PORTS:") and "192.168.1.5" in d[0], str(d))
d = P.compare(want, {**OK_INSPECT, "Config": {"Image": "postgres:18"}}, OK_SHOW, OK_EXT, H, TAG_ID)["drift"]
check("another image (a stock postgres:18, no AGE/pgvector/postgis) → IMAGE drift",
      len(d) == 1 and d[0].startswith("IMAGE:"), str(d))
d = P.compare(want, OK_INSPECT, {"max_connections": ("100", "default")}, OK_EXT, H, TAG_ID)["drift"]
check("an effective max_connections other than the declared one → SETTINGS drift, naming its source",
      len(d) == 1 and d[0].startswith("SETTINGS: max_connections is 100 (source: default)"), str(d))
r = P.compare(want, OK_INSPECT, {"max_connections": (want["settings"]["max_connections"], "configuration file")}, OK_EXT, H, TAG_ID)
check("the declared value from the data dir's auto.conf (today, before the cutover) is GREEN, its source REPORTED",
      r["drift"] == [] and any("source: configuration file" in x for x in r["report"]), str(r))
bad_ext = [(db, e, ("9.9.9" if e == "age" else v)) for db, e, v in OK_EXT]
d = P.compare(want, OK_INSPECT, OK_SHOW, bad_ext, H, TAG_ID)["drift"]
check("a rebuilt AGE of another version → VERSIONS drift (seed #42759: a rebuild can't drift silently)",
      len(d) == 1 and d[0].startswith("VERSIONS: age in astryx is 9.9.9"), str(d))
r = P.compare(want, OK_INSPECT, OK_SHOW, OK_EXT + [("genesis", "vector", "0.0.1")], H, TAG_ID)
check("an OUT-OF-SCOPE database's mismatch (genesis, deprecated) is REPORTED, never judged",
      r["drift"] == [] and any("genesis" in x and "out of scope" in x for x in r["report"]), str(r))
d = P.compare({**want, "versions": {}}, OK_INSPECT, OK_SHOW, OK_EXT, H, TAG_ID)["drift"]
check("a Dockerfile that declares no versions → drift (a version check over nothing would read green)",
      any("declares no" in x for x in d), str(d))
d = P.compare(want, OK_INSPECT, OK_SHOW, OK_EXT, "astryx-pg", TAG_ID)["drift"]
check("a helper naming another container → NAME drift", len(d) == 1 and d[0].startswith("NAME:"), str(d))
d = P.compare(want, OK_INSPECT, OK_SHOW, [x for x in OK_EXT if x[1] != "postgis"], H, TAG_ID)["drift"]
check("a declared extension installed nowhere → VERSIONS drift", any("postgis" in x and "no database" in x for x in d),
      str(d))

# a1 #43407 R2: the tag NAME matches, the binary doesn't (a retag or rebuild after the container was made)
moved = {**OK_INSPECT, "Image": "sha256:" + "0" * 64}
d = P.compare(want, moved, OK_SHOW, OK_EXT, H, TAG_ID)["drift"]
check("R2: same tag NAME, different image ID under the container → IMAGE drift (the tag moved: an unproven recreate)",
      len(d) == 1 and d[0].startswith("IMAGE:") and "tag moved" in d[0], str(d))
d = P.compare(want, OK_INSPECT, OK_SHOW, OK_EXT, H, None)["drift"]
check("R2: the declared tag absent from the host → IMAGE drift (nothing proves the binary)",
      len(d) == 1 and "isn't present" in d[0], str(d))
cut = {**OK_INSPECT, "Config": {**OK_INSPECT["Config"], "Cmd": ["postgres", "-c", "max_connections=" + want["settings"]["max_connections"]]}}
d = P.compare(want, cut, {"max_connections": (want["settings"]["max_connections"], "configuration file")}, OK_EXT, H, TAG_ID)["drift"]
check("AFTER THE CUTOVER (the -c is on the container's Cmd) the source must be the command line: a data-dir override "
      "reads drift (derived from the container, never a hand flag)", len(d) == 1 and "command line" in d[0], str(d))
r = P.compare(want, cut, {"max_connections": (want["settings"]["max_connections"], "command line")}, OK_EXT, H, TAG_ID)
check("  ...and from the command line it is green", r["drift"] == [], str(r))
r = P.compare(want, OK_INSPECT, OK_SHOW, OK_EXT, H, TAG_ID, unread=("zz_gone",))
check("an unreadable database is REPORTED (not read: …), never silently dropped",
      r["drift"] == [] and any("not read: database zz_gone" in x for x in r["report"]), str(r))

print("estate (a1 #43424: a tree without .env must read NOT SEARCHED, not crash):")
import tempfile
with tempfile.TemporaryDirectory() as td:
    tree = Path(td)
    try:
        P._live(want, repo=tree)
        got = "observed"
    except P.Unobservable as e:
        got = f"77: {e}"
    except P.Broken as e:
        got = f"1: {e}"
    except Exception as e:                                # noqa: BLE001 — the old crash
        got = f"CRASH {type(e).__name__}"
    check("a committed-only tree (no .env, no triggers/) → NOT SEARCHED (77), never a crash", got.startswith("77:"), got)
    (tree / "triggers").mkdir()
    try:
        P._live(want, repo=tree)
        got = "observed"
    except P.Unobservable as e:
        got = f"77: {e}"
    except P.Broken as e:
        got = f"1: {e}"
    except Exception as e:                                # noqa: BLE001
        got = f"CRASH {type(e).__name__}"
    check("the same tree with triggers/ (a LIVE host that lost its estate) → BROKEN (1), loud", got.startswith("1:"), got)

print("live (read-only):")
try:
    inspect, show, ext, tag_id, unread = P._live(want)
except P.Unobservable as e:
    print(f"  SKIP  live: {e}")
    skips.append("live")
except P.Broken as e:
    check(f"LIVE: the estate is intact on a live host ({e})", False, str(e))
else:
    got = P.compare(want, inspect, show, ext, P.helper_container(P.HELPER.read_text()), tag_id, unread)
    check("LIVE: the running server matches infra/pg", got["drift"] == [], str(got["drift"]))
    for x in got["report"]:
        print(f"        reported, not judged: {x}")

if fails:
    print(f"\nFAIL: {len(fails)} arm(s)")
    sys.exit(1)
if skips:
    print(f"\nSKIP (partial): {', '.join(skips)} — the rest passed")
    sys.exit(77)
print("\nALL PASS")
