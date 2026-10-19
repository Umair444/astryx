#!/usr/bin/env python3
"""plan-11324 S3c canvas (a2 #60582 A-2): in a cog of several orgs each org runs its OWN canvas, reached under the cog
front's /o/<org>/, and its session cookie lives at that org's path under a name of its own. One browser then holds each
org's session apart (a cookie name on one host is host-wide, like a tmux socket) and never sends one org's session to
another org's canvas. One org: the path is /canvas and the cookie `cv_session`, byte for byte as before.

Two fixture databases (one per org, each HOME's DSN; config.dsn allows a fixture's in a cog), a fixture registry
naming two HOMEs (their .env: a fixture federation name, a fake OBS_KEY), and three runs of the REAL
bridges/canvas.py in a child process each (its org is resolved at import): one org (no registry), HOME A, HOME B. Each
child drives the app in process (TestClient, nothing bound): the bare /canvas bounce, an owner login, /api/me under
its own cookie name and under another's, an invite link, a logout. Every call carries a caller's x-forwarded-prefix
(/o/evil): the prefix is computed from the registry, never read from a request.

  C1 one org: cookie cv_session, Path=/canvas; the bounce to /canvas/; the invite link .../canvas/#invite=; the logout
     clears Path=/canvas; main.py's canvas upstream is :8091 and its bounce /canvas/
  C2 HOME A: cookie cv_session-<A>, Path=/o/<A>/canvas; the bounce, the link and the logout under /o/<A>/canvas;
     /api/me is the owner under that name, and 401 under the one-org name; main.py: A's registry port, /o/<A>/canvas/
  C3 HOME B: its own name and path, neither equal to A's nor under it
Seams: CANVAS_SRC (a mutant bridges/canvas.py), CANVAS_MAIN_SRC (a mutant observatory/api/main.py). Exit 0 · 1 · 77.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_canvas_cog', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'httpx'), env=False)   # the admin DSN may come by env
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

PY = sys.executable
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


# the child: the REAL canvas (or a mutant, executed as bridges.canvas) and main.py's canvas lines, under its env
CHILD = r'''
import ast, asyncio, json, os, sys, types
from pathlib import Path
REPO = Path(sys.argv[1])
sys.path[:0] = [str(REPO), str(REPO / "src")]
src = os.environ.get("CANVAS_SRC")
if src:
    import bridges
    b = types.ModuleType("bridges.canvas"); b.__file__ = str(REPO / "bridges" / "canvas.py"); b.__package__ = "bridges"
    sys.modules["bridges.canvas"] = b
    exec(compile(Path(src).read_text(), b.__file__, "exec"), b.__dict__)
else:
    import bridges.canvas as b
from fastapi.testclient import TestClient
KEY, H, EVIL = sys.argv[2], {"x-astryx": "1"}, {"x-forwarded-prefix": "/o/evil"}   # the owner key: argv
out = {"cookie": b.COOKIE}

def bare(cl, h):
    cl.cookies.clear()
    return cl.get("/canvas", headers=h, follow_redirects=False)

with TestClient(b.root, base_url="http://testserver") as cl:
    r = bare(cl, EVIL)
    out["bounce"] = [r.status_code, r.headers.get("location")]
    cl.cookies.clear()
    r = cl.post("/canvas/api/login", json={"key": KEY}, headers={**H, **EVIL})
    out["login"] = r.status_code
    out["set"] = r.headers.get_list("set-cookie")
    tok = next((c.split(";")[0].split("=", 1)[1] for c in out["set"] if c.startswith(b.COOKIE + "=")), "")
    def me(name):
        cl.cookies.clear()
        return cl.get("/canvas/api/me", headers={"cookie": f"{name}={tok}", **EVIL}).status_code
    out["me"] = me(b.COOKIE)
    out["me_plain"] = me("cv_session")
    cl.cookies.clear()
    r = cl.post("/canvas/api/users", json={"name": "fxguest"}, headers={**H, **EVIL, "cookie": f"{b.COOKIE}={tok}"})
    out["link"] = (r.json() or {}).get("link", "") if r.status_code == 200 else f"HTTP {r.status_code}"
    cl.cookies.clear()
    r = cl.post("/canvas/api/logout", headers={**H, **EVIL, "cookie": f"{b.COOKIE}={tok}"})
    out["logout"] = r.headers.get_list("set-cookie")

# main.py's canvas lines, read from the source and run alone (the observatory itself is never imported)
msrc = Path(os.environ.get("CANVAS_MAIN_SRC") or REPO / "observatory" / "api" / "main.py").read_text()
keep = []
for n in ast.parse(msrc).body:
    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("CANVAS_UP", "CANVAS_PRE") for t in n.targets):
        keep.append(n)
    elif isinstance(n, ast.FunctionDef) and n.name == "_upstream":     # CANVAS_UP's one source (9b4c37c)
        keep.append(n)
    elif isinstance(n, ast.AsyncFunctionDef) and n.name == "canvas_root":
        n.decorator_list = []
        keep.append(n)
from astryx import orgs
from starlette.responses import Response
g = {"orgs": orgs, "_COG": orgs.multi(), "Response": Response}
exec(compile(ast.Module(body=keep, type_ignores=[]), "main.py", "exec"), g)
out["main_up"] = g.get("CANVAS_UP")
out["main_bounce"] = asyncio.run(g["canvas_root"]()).headers.get("location") if "canvas_root" in g else None
print("RESULT " + json.dumps(out))
'''


def run(t, env, key):
    base = {k: os.environ[k] for k in ("PATH", "HOME", "ASTRYX_FIXTURE_ADMIN_DSN") if k in os.environ}
    for k in ("CANVAS_SRC", "CANVAS_MAIN_SRC"):
        if os.environ.get(k):
            base[k] = os.environ[k]
    p = subprocess.run([PY, "-c", CHILD, str(REPO), key], env={**base, **env}, cwd=t, capture_output=True, text=True,
                       timeout=180)
    got = next((json.loads(ln[7:]) for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    return got or {"rc": p.returncode, "err": (p.stderr or p.stdout)[-600:]}


def attrs(cookie_line):
    """A Set-Cookie line's name and its attributes, lower-cased keys."""
    parts = [x.strip() for x in cookie_line.split(";")]
    d = {k.lower(): v for k, _, v in (x.partition("=") for x in parts[1:])}
    return parts[0].split("=", 1)[0], d


def one(got, name):
    lines = [c for c in got.get("set", []) if c.startswith(name + "=")]
    return attrs(lines[0])[1] if len(lines) == 1 else None


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-cvcog-")).resolve()
    pid = os.getpid()
    oa, ob = f"fxcva-{pid}", f"fxcvb-{pid}"
    with fixture_db() as da, fixture_db() as db:
        reg = {"orgs": {}}
        for o, d, port in ((oa, da, 18091), (ob, db, 28091)):
            h = t / o
            h.mkdir()
            (h / ".env").write_text(f"ASTRYX_ORG=fed-{o}\nASTRYX_DSN={d['url']}\nOBS_KEY=fx-owner-{o}\n")
            # the registry names a db of the org's own (never a fixture's: it refuses one); the HOME's DSN binds the
            # fixture database, which config.dsn allows in a cog (the oracles bind through it)
            reg["orgs"][o] = {"home": str(h), "db": f"fxcvorg_{o.replace('-', '_')}",
                              "ports": {"astryx-canvas": port, "astryx-observatory-org": port + 9}}
        (t / "cog.json").write_text(json.dumps(reg))
        none = str(t / "no-registry.json")
        one_org = run(t, {"ASTRYX_COG_REGISTRY": none, "ASTRYX_DSN": da["url"], "OBS_KEY": "fx-owner-one"}, "fx-owner-one")
        cog = {o: run(t, {"ASTRYX_COG_REGISTRY": str(t / "cog.json"), "ASTRYX_HOME": str(t / o),
                          "ASTRYX_DSN": d["url"], "OBS_KEY": f"fx-owner-{o}"}, f"fx-owner-{o}")
               for o, d in ((oa, da), (ob, db))}

    print("C1 ONE ORG: AS BEFORE")
    g = one_org
    c = one(g, "cv_session")
    check("the owner logs in; one cookie cv_session at Path=/canvas (a caller's x-forwarded-prefix moved nothing)",
          g.get("login") == 200 and g.get("cookie") == "cv_session" and c is not None and c.get("path") == "/canvas",
          str(g))
    check("the bare /canvas bounces to /canvas/", g.get("bounce") == [308, "/canvas/"], str(g.get("bounce")))
    check("/api/me is the owner under cv_session", g.get("me") == 200, str(g))
    check("the invite link is <host>/canvas/#invite=…", str(g.get("link", "")).startswith("http://testserver/canvas/#invite="),
          str(g.get("link")))
    lo = [attrs(x) for x in g.get("logout", [])]
    check("logout clears cv_session at Path=/canvas", any(n == "cv_session" and a.get("path") == "/canvas" for n, a in lo),
          str(g.get("logout")))
    check("main.py: this org's canvas is :8091, and its bounce /canvas/",
          g.get("main_up") == "http://127.0.0.1:8091" and g.get("main_bounce") == "/canvas/", str(g))

    for o, port, label in ((oa, 18091, "C2 HOME A"), (ob, 28091, "C3 HOME B")):
        print(f"\n{label}: ITS OWN NAME, ITS OWN PATH")
        g = cog[o]
        name, path = f"cv_session-{o}", f"/o/{o}/canvas"
        c = one(g, name)
        check(f"the owner logs in; one cookie {name} at Path={path} (never the caller's /o/evil)",
              g.get("login") == 200 and g.get("cookie") == name and c is not None and c.get("path") == path
              and not any(x.startswith("cv_session=") for x in g.get("set", [])), str(g))
        check(f"the bare /canvas bounces to {path}/", g.get("bounce") == [308, f"{path}/"], str(g.get("bounce")))
        check(f"/api/me is the owner under {name}, and 401 under the one-org name cv_session",
              g.get("me") == 200 and g.get("me_plain") == 401, str(g))
        check(f"the invite link is <host>{path}/#invite=…", str(g.get("link", "")).startswith(f"http://testserver{path}/#invite="),
              str(g.get("link")))
        lo = [attrs(x) for x in g.get("logout", [])]
        check(f"logout clears {name} at Path={path}", any(n == name and a.get("path") == path for n, a in lo),
              str(g.get("logout")))
        check(f"main.py: this org's canvas is its registry port {port}, and its bounce {path}/",
              g.get("main_up") == f"http://127.0.0.1:{port}" and g.get("main_bounce") == f"{path}/", str(g))
    pa, pb = f"/o/{oa}/canvas", f"/o/{ob}/canvas"
    check("A's and B's cookies differ in name and path, and neither path is under the other (a browser sends A's to "
          "B never)", cog[oa].get("cookie") != cog[ob].get("cookie") and not pb.startswith(pa + "/")
          and not pa.startswith(pb + "/") and pa != pb, f"{cog[oa].get('cookie')} {cog[ob].get('cookie')}")


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    try:
        main()
    except FixtureUnavailable as e:
        unavailable("test_canvas_cog", REPO, e)
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
          "canvas in a cog: each org's session at its own path, under its own name; one org as before")
    sys.exit(1 if fails else 0)
