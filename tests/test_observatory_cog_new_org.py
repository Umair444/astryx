#!/usr/bin/env python3
"""Oracle: POST /api/cog/orgs, the owner's "New org" from the Agents view (the owner's ask 10-19: "in agents view make
sure we can also create a new org in cog too"). The route builds nothing (no sudo, init.sh or cog_add_org.py): it
judges the request and puts ONE wire message to seed on thread cog-new-org-<key>. On a throwaway fixture database
(sqlguard's stamped fixture_db), the API in process (TestClient), the registry planted per request:

  N1 no key, or a wrong key: 403, and no row
  N2 a bad key (uppercase, a leading digit, too short, too long, a dot, a space): 400, and no row
  N3 a name that isn't a federation name a new org can take (reserved, illegal, OUR own): 400, and no row
  N4 a key already in the cog's registry: 409, and no row; a registry that refuses: 500
  N5 a valid request: {queued: true, thread}, exactly ONE row: owner -> seed, intent task, the thread, the body
     `COG NEW ORG key=<k> name=<n> purpose=<p>` (purpose folded to one line); the name defaults to <key>.<our org>
  N6 a second request for that key while the first is open (younger than a day): 409 naming the thread, no row;
     once that row is a day old, a new request is taken
Seam: OBS_MAIN_SRC (a mutant main.py). Exit 0 · 1 · 77.
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = Path(os.environ.get("OBS_MAIN_SRC") or REPO / "observatory" / "api" / "main.py")
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_observatory_cog_new_org', REPO, deps=('psycopg', 'asyncpg', 'fastapi'), env=False)   # a worktree: the admin DSN by env
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0
O = {"x-obs-key": "test-owner-key"}


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(url, tmp):
    import psycopg
    sys.path.insert(0, str(REPO / "observatory" / "api"))
    subject = SUBJECT
    if os.environ.get("OBS_MAIN_SRC"):              # seated where paths.estate() places a code-tree file
        subject = tmp / "subject" / "observatory" / "api" / "main.py"
        subject.parent.mkdir(parents=True)
        subject.write_text(SUBJECT.read_text())
    spec = importlib.util.spec_from_file_location("main", subject)
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.testclient import TestClient

    with psycopg.connect(url, autocommit=True) as c, TestClient(obs.app) as cl:
        def rows(thread=None):           # two literal statements: sqlguard's inventory reads SQL it can see (steward #61761 D)
            if thread:
                return [tuple(r) for r in c.execute(
                    "SELECT from_agent, to_agent, intent, thread, body FROM messages"
                    " WHERE starts_with(thread, 'cog-new-org-') AND thread = %s ORDER BY id", (thread,)).fetchall()]
            return [tuple(r) for r in c.execute(
                "SELECT from_agent, to_agent, intent, thread, body FROM messages"
                " WHERE starts_with(thread, 'cog-new-org-') ORDER BY id").fetchall()]

        def post(body, headers=O):
            r = cl.post("/api/cog/orgs", json=body, headers=headers)
            return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})

        os.environ["ASTRYX_COG_REGISTRY"] = str(tmp / "absent.json")       # one org: this becomes org #2

        print("N1 OWNER ONLY")
        arm("no key: 403, no row", post({"key": "lab"}, headers={})[0] == 403 and not rows())
        arm("a wrong key: 403, no row", post({"key": "lab"}, headers={"x-obs-key": "nope"})[0] == 403 and not rows())

        print("\nN2 A BAD KEY")
        for k in ("Lab", "1lab", "l", "a" * 32, "lab.x", "la b", "", "-lab"):
            st, _ = post({"key": k})
            arm(f"key {k!r}: 400", st == 400, st)
        arm("…and no row", not rows())

        print("\nN3 A NAME A NEW ORG CAN'T TAKE")
        for n in ("local", "Bad Name", "owner", "fixture.example"):
            st, _ = post({"key": "lab", "name": n})
            arm(f"name {n!r}: 400", st == 400, st)
        arm("…and no row", not rows())

        print("\nN4 ALREADY AN ORG OF THIS COG")
        reg = tmp / "cog.json"
        reg.write_text(json.dumps({"orgs": {"zeta": {"home": str(tmp / "zeta"), "db": "zeta_db"},
                                            "alpha": {"home": str(obs.ESTATE), "db": "alpha_db"}}}))
        os.environ["ASTRYX_COG_REGISTRY"] = str(reg)
        st, j = post({"key": "zeta"})
        arm("a key the registry holds: 409, no row", st == 409 and not rows(), (st, j))
        reg.write_text("{not json")
        st, j = post({"key": "newone"})
        arm("a registry that refuses: 500 that says why, no row",
            st == 500 and j.get("error", "").startswith("cog registry refused") and not rows(), (st, j))
        os.environ["ASTRYX_COG_REGISTRY"] = str(tmp / "absent.json")

        print("\nN5 A VALID REQUEST: ONE ROW TO SEED")
        st, j = post({"key": "lab", "purpose": "  research\n and   scouting  "})
        got = rows()
        arm("{queued: true, thread: cog-new-org-lab}", st == 200 and j.get("queued") is True
            and j.get("thread") == "cog-new-org-lab", (st, j))
        arm("exactly one row: owner -> seed, intent task, the thread, the body (purpose on one line, name defaulted)",
            got == [("owner", "seed", "task", "cog-new-org-lab",
                     "COG NEW ORG key=lab name=lab.fixture.example purpose=research and scouting")], got)

        print("\nN6 ONE OPEN REQUEST PER KEY")
        st, j = post({"key": "lab", "name": "lab2.fixture.example"})
        arm("a second request while the first is open: 409 naming the thread, no row",
            st == 409 and j.get("thread") == "cog-new-org-lab" and len(rows()) == 1, (st, j, rows()))
        st, j = post({"key": "ops", "name": "ops.example.org"})
        arm("another key is its own request (an explicit name kept)", st == 200
            and rows("cog-new-org-ops") == [("owner", "seed", "task", "cog-new-org-ops",
                                             "COG NEW ORG key=ops name=ops.example.org purpose=-")], (st, j))
        c.execute("UPDATE messages SET ts = now() - interval '25 hours' WHERE thread = 'cog-new-org-lab'")
        st, j = post({"key": "lab"})
        arm("once that request is a day old, a new one is taken", st == 200 and len(rows("cog-new-org-lab")) == 2, (st, j))
        os.environ["ASTRYX_COG_REGISTRY"] = str(tmp / "absent.json")


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    with tempfile.TemporaryDirectory() as td:
        # never the host's /etc registry (a host in a cog has one): one org, before anything resolves a HOME
        os.environ["ASTRYX_COG_REGISTRY"] = str(Path(td) / "absent.json")
        try:
            with fixture_db() as fx:
                os.environ["ASTRYX_DSN"] = fx["url"]
                os.environ["OBS_KEY"] = "test-owner-key"
                os.environ["ASTRYX_ORG"] = "fixture.example"
                os.environ["ASTRYX_GATEWAY_PORT"] = "9"          # discard: a real gateway is never asked
                main(fx["url"], Path(td))
        except FixtureUnavailable as e:                          # no admin DSN here: NOT SEARCHED, or BROKEN on a live host
            unavailable("test_observatory_cog_new_org", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: observatory cog new org ({fails} failing)")
    sys.exit(1 if fails else 0)
