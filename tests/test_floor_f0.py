#!/usr/bin/env python3
"""Oracle: plan-11860 F0, the floor's foundation (a4 #61976 E1/E2/E3/E4/E5/E9, a1 #61979 BC-1/BC-2/BC-3).
  - E1 GATE CENSUS: every (method, path) the observatory serves under /api/ answers an anonymous call 403, unless the
    pair is in PUBLIC. Enumerated from the live app, so a route added later is ACCUSED by default; a public GET never
    opens its POST (POST /api/messages, POST /api/agents are 403 to a visitor).
  - E2 ONE RESOLVER (bridges/routing.py): a duplicate chat and an agent with several routes but no single home are
    problems; the doorbell is the only row, else the single home, else NONE (never file order); diff() reads the
    EFFECTIVE maps. BC-2: no first-match route loop is left in a bridge, and each bridge's routes() is the resolver.
  - BC-3: a routes file that stops parsing keeps the last good table and alarms, never [] silently.
  - E3 ONE HOST WRITER: no write_text / open-for-write in observatory/api outside hostfile.py (the answers log's
    O_APPEND is the one declared exception); atomic_write refuses a stale If-Match and leaves the file and no temp.
  - E4 THE ROUTES PUT: no If-Match is 428, a stale one 409, a duplicate chat 400 (nothing written), and a move returns
    the diff the bridges' own reader agrees with.
  - E5 / BC-1: config.set_env writes a key exactly once (a hand-made duplicate collapses, and the first-wins and the
    last-wins readers agree); duplicate_keys() names a duplicate; federate.set_env is config.set_env.
  - E9 GLYPHS: the public projection carries only {agent, channel, kind, count}: no chat id, jid, number, name, note or
    webhook of the route table reaches it (fixture tables, and the org's own routes files when GLYPH_ROUTES_DIR names them).
"""
import ast
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_floor_f0', REPO, deps=('psycopg', 'asyncpg', 'fastapi'), env=False)   # fixture_db only: a worktree passes
#   its admin DSN as ASTRYX_FIXTURE_ADMIN_DSN (devtools/sqlsite.sh), never a linked .env
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

fails = 0
O = {"x-obs-key": "test-owner-key"}
# every chat id is BUILT here, never written as a literal (a3 #62025: no JID-shaped literal, nothing from a live file)
G1, G2, G3, G4 = (d * 18 + "@g.us" for d in "1234")
P1, P2 = (d * 12 + "@s.whatsapp.net" for d in "67")
LID = "8" * 15 + "@lid"


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


# ------------------------------------------------------------------------------------------------ E2 / BC-2 / BC-3
def resolver_arms(tmp: Path):
    from bridges import routing as R
    dup = [{"chat": G1, "agent": "seed", "enabled": True}, {"chat": G1, "agent": "ledger", "enabled": True}]
    arm("E2: a chat routed twice is a problem naming both agents",
        any("seed" in p and "ledger" in p for p in R.validate(dup)), R.validate(dup))
    two = [{"chat": "a", "agent": "seed", "enabled": True}, {"chat": "b", "agent": "seed", "enabled": True}]
    arm("E2: an agent with two routes and no home is a problem", any("home" in p for p in R.validate(two)), R.validate(two))
    arm("E2: …and its doorbell is NONE, never the first row in the file", R.resolve(two).doorbell("seed") is None)
    homed = [two[0], {**two[1], "home": True}]
    arm("E2: with one home it validates, and the home is the doorbell",
        R.validate(homed) == [] and R.resolve(homed).doorbell("seed")["chat"] == "b", R.validate(homed))
    arm("E2: an agent's only route is its doorbell; a disabled route reaches no one",
        R.resolve([two[0], {"chat": "c", "agent": "ledger", "enabled": False}]).doorbell("seed")["chat"] == "a"
        and R.resolve([{"chat": "c", "agent": "ledger", "enabled": False}]).chat("c") is None)
    arm("E2: an unknown agent is a problem when the roster is given",
        any("no such agent" in p for p in R.validate([{"chat": "x", "agent": "ghost", "enabled": True}], {"seed"})))
    d = R.diff([{"chat": "a", "agent": "seed", "enabled": True}], [{"chat": "a", "agent": "ledger", "enabled": True}])
    arm("E2: diff reads the effective maps: a move, and both doorbells it changed",
        d["moved"] == [{"chat": "a", "from": "seed", "to": "ledger"}] and not d["added"] and not d["removed"]
        and {x["agent"] for x in d["doorbell"]} == {"seed", "ledger"}, d)

    flip = [{**two[0], "home": True}, two[1]]
    d = R.diff(homed, flip)
    arm("E2: a home flip moves no chat but rings a different doorbell (the diff is over effective maps, not rows)",
        d["moved"] == [] and not d["added"] and not d["removed"]
        and d["doorbell"] == [{"agent": "seed", "old": "b", "new": "a"}], d)

    # ONE validator: doctor imports it, and neither doctor nor the observatory keeps a copy (a3 #61993 (3))
    cli = (REPO / "src" / "astryx" / "cli.py").read_text()
    oc = next(n for n in ast.walk(ast.parse(cli)) if isinstance(n, ast.FunctionDef) and n.name == "org_checks")
    seg = ast.get_source_segment(cli, oc)
    arm("E2: doctor (cli.org_checks) judges routes with bridges.routing.validate",
        "from bridges import routing" in seg and "routing.validate(" in seg, seg[:300])
    copies = {}
    for f in (REPO / "src" / "astryx" / "cli.py", REPO / "observatory" / "api" / "main.py"):
        names = {n.name for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        copies[f.name] = sorted(names & {"validate", "resolve", "diff", "effective", "Routes", "doorbell"})
    arm("E2: no copy of the resolver or validator in doctor or the observatory", not any(copies.values()), copies)

    # BC-2: the census, then each bridge's own reader IS the resolver
    loops = re.compile(r"for\s+\w+\s+in\s+routes\(\)|next\(\(\s*\w+\s+for\s+\w+\s+in\s+routes\(\)")
    left = {b: len(loops.findall((REPO / "bridges" / f"{b}.py").read_text())) for b in ("whatsapp", "telegram", "discord")}
    arm("BC-2: no first-match route loop is left in any bridge (every lookup is .chat() / .doorbell())",
        not any(left.values()), left)
    src = (REPO / "bridges" / "common.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "load_routes")
    arm("BC-2: common.load_routes (every bridge's routes()) returns the resolver over read_table",
        "resolve(read_table(" in ast.get_source_segment(src, fn), ast.get_source_segment(src, fn))
    for b in ("whatsapp", "telegram", "discord"):
        t = ast.parse((REPO / "bridges" / f"{b}.py").read_text())
        rf = [n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == "routes"]
        arm(f"BC-2: {b}.routes() reads through load_routes", bool(rf) and any(
            isinstance(c, ast.Call) and getattr(c.func, "id", None) == "load_routes" for c in ast.walk(rf[0])))

    # doctor, BEHAVIORAL (a3 #62025 R2): cli.org_checks on fixture estates, its failures counted and named
    import io
    from types import SimpleNamespace
    from astryx import cli
    from astryx.ui import UI

    def doctor(routes, env="A=1\n"):
        d = tmp / f"est{len(list(tmp.glob('est*')))}"
        (d / "bridges").mkdir(parents=True)
        (d / "agents").mkdir()
        for a in ("seed", "ledger"):
            (d / "agents" / f"{a}.md").write_text(f"# {a}\n")
        (d / "bridges" / "routes-whatsapp.json").write_text(json.dumps(routes))
        (d / ".env").write_text(env)
        buf = io.StringIO()
        n = cli.org_checks(SimpleNamespace(root=d, home=d, ui=UI(stream=buf)))
        return n, buf.getvalue()
    n, out = doctor([{"chat": G1, "agent": "seed", "enabled": True, "note": "Zeta group -> seed"}])
    arm("DOCTOR: a clean estate fails nothing", n == 0 and "✗" not in out, (n, out))
    n, out = doctor([{"chat": G1, "agent": "seed", "enabled": True, "note": "Zeta group -> seed"},
                     {"chat": G1, "agent": "ledger", "enabled": True}])
    arm("DOCTOR: a duplicate chat fails the routes step, naming its label and both agents (never the chat id)",
        n >= 1 and "✗ routes: bridges/routes-whatsapp.json" in out and "Zeta group" in out and "seed" in out
        and "ledger" in out and G1 not in out, out)
    n, out = doctor([{"chat": G1, "agent": "seed", "enabled": True}, {"chat": G2, "agent": "seed", "enabled": True}])
    arm("DOCTOR: an agent with two routes and no home fails", n >= 1 and "home" in out, out)
    n, out = doctor([{"chat": G1, "agent": "seed", "enabled": True}], env="K=a\nB=2\nK=b\n")
    arm("DOCTOR: a key held twice in the .env fails, naming the key and never a value",
        n >= 1 and "✗ .env holds each key once" in out and "K" in out and "=a" not in out and "=b" not in out, out)

    # the mutant runner's baseline (a1 #62023 R-1): an oracle that can't reach a fixture makes the runner 77, never 0.
    # On a scratch tree whose two oracles are 77 stubs, and no triggers/ (the runner refuses a live tree)
    import shutil
    import subprocess
    sc = tmp / "runner"
    (sc / "tests").mkdir(parents=True)
    shutil.copy(REPO / "tests" / "mutants_floor_f0.py", sc / "tests" / "mutants_floor_f0.py")
    for o in ("test_floor_f0.py", "test_floor_s3.py"):
        (sc / "tests" / o).write_text("import sys\nprint('NOT SEARCHED: no fixture database')\nsys.exit(77)\n")
    rr = subprocess.run([sys.executable, str(sc / "tests" / "mutants_floor_f0.py")], capture_output=True, text=True, timeout=120)
    arm("R-1: with no reachable fixture the mutant runner says NOT CHECKED and exits 77, never a PASS",
        rr.returncode == 77 and "NOT CHECKED" in rr.stdout, (rr.returncode, rr.stdout[-300:]))

    # BC-3
    f = tmp / "routes-x.json"
    f.write_text(json.dumps(homed))
    good = R.read_table(f)
    f.write_text('[{"chat": "a", ')
    import contextlib
    import io
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        kept = R.read_table(f)
    arm("BC-3: a file that stops parsing keeps the last good table", kept == good and len(kept) == 2, kept)
    arm("BC-3: …and alarms", "ALARM" in err.getvalue(), err.getvalue())


# ------------------------------------------------------------------------------------------------ E3
def hostwrite_arms(tmp: Path):
    api = REPO / "observatory" / "api"
    bad = []
    for p in sorted(api.glob("*.py")):
        if p.name == "hostfile.py":
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Call):
                name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                if name in ("write_text", "write_bytes"):
                    bad.append(f"{p.name}:{n.lineno} {name}")
                if name == "open" and getattr(n.func, "id", None) == "open":
                    modes = [a.value for a in n.args[1:2] if isinstance(a, ast.Constant)] + \
                            [k.value.value for k in n.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
                    if any(set(str(m)) & set("wax+") for m in modes):
                        bad.append(f"{p.name}:{n.lineno} open({modes})")
                if name == "fdopen" and any(isinstance(a, ast.Constant) and set(str(a.value)) & set("wx+")
                                            for a in n.args[1:2]):
                    bad.append(f"{p.name}:{n.lineno} fdopen")
    arm("E3 CENSUS: no host write in observatory/api outside hostfile.atomic_write (O_APPEND log excepted)", not bad, bad)

    from observatory.api.hostfile import Conflict, atomic_write, etag
    f = tmp / "h.json"
    f.write_text("one\n")
    os.chmod(f, 0o640)
    tag = etag(f)
    atomic_write(f, "two\n", if_match=tag)
    arm("E3: atomic_write with the current etag writes, and keeps the file's mode",
        f.read_text() == "two\n" and stat.S_IMODE(os.stat(f).st_mode) == 0o640, oct(os.stat(f).st_mode))
    try:
        atomic_write(f, "three\n", if_match=tag)
        refused = False
    except Conflict:
        refused = True
    arm("E3: a stale If-Match is refused and nothing is written", refused and f.read_text() == "two\n")
    arm("E3: no temp file is left behind", sorted(x.name for x in tmp.iterdir() if x.name.startswith(".h.json")) == [])


# ------------------------------------------------------------------------------------------------ E5 / BC-1
def env_arms(tmp: Path):
    from astryx import config
    f = tmp / ".env"
    f.write_text("K=a\nX=1\nK=b\n")
    arm("E5: duplicate_keys names a key held twice (names only)", config.duplicate_keys(f) == ["K"])
    config.set_env("K", "c", f)
    lines = f.read_text().splitlines()
    last_wins = {}
    for ln in lines:
        k, _, v = ln.partition("=")
        last_wins[k] = v
    arm("BC-1: set_env writes the key exactly once, at its first position",
        [ln for ln in lines if ln.startswith("K=")] == ["K=c"] and lines[0] == "K=c" and "X=1" in lines, lines)
    arm("BC-1: …so the first-wins reader and the last-wins reader agree",
        config.read_env(f)["K"] == "c" == last_wins["K"], (config.read_env(f), last_wins))
    arm("E5: a duplicate-free file names none", config.duplicate_keys(f) == [])
    try:
        config.set_env("K", "x\nWA_CLI=evil", f)
        took = True
    except ValueError:
        took = False
    arm("E5: a value carrying a newline is refused (the planted-WA_CLI bypass)", not took and "WA_CLI" not in f.read_text())
    src = (REPO / "src" / "astryx" / "federation" / "federate.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "set_env")
    body = ast.get_source_segment(src, fn)
    arm("E5: federate.set_env is config.set_env (no writer of its own)",
        "config.set_env(" in body and "write_text" not in body and "open(" not in body, body)


# ------------------------------------------------------------------------------------------------ E1 / E4 / E9
def app_arms(tmp: Path):
    sys.path.insert(0, str(REPO / "observatory" / "api"))
    spec = importlib.util.spec_from_file_location("main", REPO / "observatory" / "api" / "main.py")
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.routing import APIRoute, APIWebSocketRoute
    from fastapi.testclient import TestClient

    cl = TestClient(obs.app)            # no lifespan: the gate answers before any handler, so no pool is needed
    leaks, seen = [], 0
    for r in obs.app.routes:
        if not isinstance(r, APIRoute) or not r.path.startswith("/api/"):
            continue
        path = re.sub(r"\{[^}]+\}", "x", r.path)
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            if (m, r.path) in obs.PUBLIC or (m == "GET" and obs._PUBLIC_AVATAR.match(path)):
                continue
            seen += 1
            code = cl.request(m, path).status_code
            if code != 403:
                leaks.append(f"{m} {r.path} -> {code}")
    arm(f"E1 CENSUS: every non-public (method, path) under /api/ is 403 to a visitor ({seen} pairs)",
        seen > 50 and not leaks, leaks)
    # what Starlette SERVES, not what the decorators list: HEAD on every GET route, OPTIONS anywhere (a3 #61993 (1))
    served = []
    for r in obs.app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api/"):
            path = re.sub(r"\{[^}]+\}", "x", r.path)
            pub_get = ("GET", r.path) in obs.PUBLIC or obs._PUBLIC_AVATAR.match(path)
            for m in ("HEAD", "OPTIONS"):
                if m == "HEAD" and pub_get:
                    continue                      # HEAD is judged as GET: a public GET's HEAD is public
                code = cl.request(m, path).status_code
                if code != 403:
                    served.append(f"{m} {r.path} -> {code}")
    arm("E1 CENSUS: HEAD and OPTIONS on every non-public path are 403 too", not served, served)
    h = cl.head("/api/floor/glyphs").status_code
    arm("E1: HEAD on a public GET passes the gate as that GET (the route answers it, 200, or refuses it, 405), "
        "and on an owner path the gate refuses it", h in (200, 405) and cl.head("/api/wire/routes").status_code == 403, h)
    arm("E1: a public GET never opens its POST (POST /api/messages, POST /api/agents are 403 anonymously)",
        cl.post("/api/messages", json={"to": "seed", "body": "x"}).status_code == 403
        and cl.post("/api/agents", json={}).status_code == 403)
    arm("E1: the only public non-GET is POST /api/vega", {m for m, _ in obs.PUBLIC} <= {"GET", "POST"}
        and [p for m, p in obs.PUBLIC if m != "GET"] == ["/api/vega"], obs.PUBLIC)
    ws = sorted(r.path for r in obs.app.routes if isinstance(r, APIWebSocketRoute))
    arm("E1: the websocket routes are the declared, self-gated set", ws == ["/api/hands/{agent}/vnc"], ws)
    on_public = sorted(f"{m} {r.path}" for r in obs.app.routes if isinstance(r, APIRoute) and r.path in obs.PUBLIC_PATHS
                       for m in r.methods - {"HEAD", "OPTIONS"} if (m, r.path) not in obs.PUBLIC)
    arm("E1: a non-GET handler on a public path is ACCUSED: owner-gated (403) to a visitor",
        all(cl.request(x.split()[0], x.split()[1]).status_code == 403 for x in on_public), on_public)
    arm("E1/E9: /api/floor/glyphs is public as GET ONLY", [m for m, p in obs.PUBLIC if p == "/api/floor/glyphs"] == ["GET"]
        and not [x for x in on_public if x.endswith(" /api/floor/glyphs")])
    arm("E1/E9: /api/wire/routes is NOT public", ("GET", "/api/wire/routes") not in obs.PUBLIC
        and cl.get("/api/wire/routes").status_code == 403)

    # E4, on a fixture bridges dir (never the estate's)
    bdir = tmp / "bridges"
    bdir.mkdir()
    rows = [{"chat": G1, "agent": "seed", "enabled": True, "note": "Zeta group -> seed",
             "trusted_jids": [P1]}]
    (bdir / "routes-whatsapp.json").write_text(json.dumps(rows))
    obs.BRIDGES = bdir
    obs.agent_meta = lambda: {"seed": {}, "ledger": {}}
    g = cl.get("/api/wire/routes", headers=O).json()
    tag = g[0]["etag"]
    moved = [{**rows[0], "agent": "ledger"}]
    r = cl.put("/api/wire/routes/whatsapp", json={"routes": moved}, headers=O)
    arm("E4: a PUT without If-Match is 428, and writes nothing", r.status_code == 428
        and json.loads((bdir / "routes-whatsapp.json").read_text()) == rows, r.status_code)
    r = cl.put("/api/wire/routes/whatsapp", json={"routes": moved}, headers={**O, "if-match": "0" * 64})
    arm("E4: a stale If-Match is 409", r.status_code == 409, (r.status_code, r.text))
    r = cl.put("/api/wire/routes/whatsapp", json={"routes": moved + [{**rows[0], "agent": "seed"}]},
               headers={**O, "if-match": tag})
    arm("E4: a duplicate chat is 400, naming both agents, and writes nothing",
        r.status_code == 400 and "seed" in r.json().get("error", "") and "ledger" in r.json()["error"]
        and json.loads((bdir / "routes-whatsapp.json").read_text()) == rows, (r.status_code, r.text))
    r = cl.put("/api/wire/routes/whatsapp", json={"routes": moved}, headers={**O, "if-match": tag})
    j = r.json() if r.status_code == 200 else {}
    arm("E4: a move answers the effective diff", r.status_code == 200 and j.get("diff", {}).get("moved")
        == [{"chat": rows[0]["chat"], "from": "seed", "to": "ledger"}], (r.status_code, r.text))
    from bridges.routing import read_table, resolve       # what common.load_routes returns, the bridges' reader
    seen_by_bridge = resolve(read_table(bdir / "routes-whatsapp.json")).chat(rows[0]["chat"])
    arm("E4/BC-2: the bridges' reader agrees with the diff", seen_by_bridge and seen_by_bridge["agent"] == "ledger"
        and j.get("etag") == obs.etag(bdir / "routes-whatsapp.json"), seen_by_bridge)
    arm("E4: the trusted senders and note survive the write verbatim",
        json.loads((bdir / "routes-whatsapp.json").read_text())[0]["trusted_jids"] == rows[0]["trusted_jids"])

    # E9: the public glyphs
    tables = {"whatsapp": [{"chat": G2, "agent": "seed", "enabled": True, "note": "Zeta group -> seed (a fixture surface)",
                            "trusted_jids": [P1, LID]},
                           {"chat": P2, "agent": "canopus", "enabled": True, "note": "Example Person 1:1 DM -> canopus"},
                           {"chat": G3, "agent": "seed", "enabled": False, "note": "Example Household -> gemini"},
                           {"chat": G4, "agent": "gemini", "enabled": False}],
              "discord": [{"chat": "4" * 19, "agent": "seed", "enabled": True,
                           "webhook": "https://discord.com/api/webhooks/1/SECRETSECRET", "trusted_ids": [int("5" * 18)]}],
              "telegram": [{"chat": "-100855", "agent": "ledger", "enabled": True}]}
    out = obs.glyphs_of(tables)
    arm("E9: glyphs are {agent, channel, kind, count} only, enabled routes only",
        out == [{"agent": "canopus", "channel": "whatsapp", "kind": "person", "count": 1},
                {"agent": "ledger", "channel": "telegram", "kind": "group", "count": 1},
                {"agent": "seed", "channel": "discord", "kind": "group", "count": 1},
                {"agent": "seed", "channel": "whatsapp", "kind": "group", "count": 1}], out)

    VOCAB = {"whatsapp", "telegram", "discord", "group", "person", "agent", "channel", "kind", "count",
             "seed", "canopus", "gemini", "ledger"}     # the projection's own words: an agent, a channel, a kind

    def needles(tbls):
        n = set()
        for rows_ in tbls.values():
            for r_ in rows_:
                for k, v in r_.items():
                    if k in ("agent", "enabled", "open", "live_steps", "home"):
                        continue
                    for x in (v if isinstance(v, list) else [v]):
                        s = str(x)
                        n.add(s)
                        n.update(p for p in re.split(r"[@/:.\s]+", s) if len(p) >= 6)
        return {x for x in n if x.lower() not in VOCAB}
    arm("E9: every glyph's key set is EXACTLY {agent, channel, kind, count}",
        all(set(x) == {"agent", "channel", "kind", "count"} for x in out) and out, out)
    body = json.dumps(out)
    arm("E9: no chat id, jid, number, note or webhook substring of the fixture tables reaches the body",
        not [x for x in needles(tables) if x and x in body], [x for x in needles(tables) if x and x in body])
    names = ["Zeta", "Example Person", "Example Household", "a fixture surface"]
    arm("E9: no contact or group NAME reaches the body", not [x for x in names if x.lower() in body.lower()],
        [x for x in names if x.lower() in body.lower()])
    live_dir = os.environ.get("GLYPH_ROUTES_DIR")
    if live_dir:
        live = {p.name[7:-5]: json.loads(p.read_text()) for p in Path(live_dir).glob("routes-*.json")
                if not p.name.endswith(".example.json")}
        lb = json.dumps(obs.glyphs_of(live))
        hit = [x for x in needles(live) if x and x in lb]
        arm(f"E9: …nor of the org's own routes files ({len(live)} channels, read-only)", live and not hit, hit)
    obs.BRIDGES = bdir
    r = cl.get("/api/floor/glyphs")
    arm("E9: GET /api/floor/glyphs answers a visitor with the projection (keys pinned), a POST does not",
        r.status_code == 200 and r.json() == [{"agent": "ledger", "channel": "whatsapp", "kind": "group", "count": 1}]
        and cl.post("/api/floor/glyphs").status_code in (403, 405), (r.status_code, r.text))


if __name__ == "__main__":
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = "test-owner-key"
            os.environ["ASTRYX_ORG"] = "fixture.example"
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            tmp = Path(td)
            for name, fn in (("resolver", resolver_arms), ("hostwrite", hostwrite_arms), ("env", env_arms), ("app", app_arms)):
                d = tmp / name
                d.mkdir()
                fn(d)
    except FixtureUnavailable as e:                     # no admin DSN reachable: 77 on a committed-only tree, 1 live
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_floor_f0", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: floor F0 ({fails} failing)")
    sys.exit(1 if fails else 0)
