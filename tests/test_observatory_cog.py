#!/usr/bin/env python3
"""plan-11324 S3c 3/n (seed #60433, design B): the cog's observatory FRONT (observatory/front.py) is one place for
every org of the cog, and a byte pipe to each org's own observatory; it holds no org's key and adds no authority.

Two FAKE backends (a recording echo app each, real uvicorn, ephemeral loopback ports: no database, no observatory
build) behind the real front (uvicorn front:app, ephemeral port), a fixture registry naming both with their
`astryx-observatory-org` ports. Nothing binds 8090.

  O1 /api/cog lists both orgs (sorted), each its federation name (its HOME's ASTRYX_ORG) and /o/<org>/ base, home
     null, no port leaked; it is the front's own (no backend saw it)
  O2 /o/<a>/… reaches A's backend ONLY, as /…: method, query, body, the caller's x-obs-key and cookie exactly; the
     backend's status and headers come back
  O3 an org the registry doesn't hold is a 404 (no backend hit); a dotted path under /o/<a>/ never reaches B
  O4 the root /api/* goes to the org the viewer chose: header x-astryx-org, else cookie astryx_org (the header wins);
     none, or one not in the cog: 409 naming /api/cog, no backend hit
  O5 no authority added: a caller with no x-obs-key reaches the backend with none; a Set-Cookie from a backend is
     never replayed to the next caller (the front's jar stores nothing)
  O6 /api/cog/stream fans in both backends' /api/events, each event wrapped {org, name, event}, ?key= forwarded to
     each; a backend that dies is announced {"type": "cog_backend", "up": false} for its org, and a call to it is
     REFUSED at once (502), never left in a listen backlog the oracle still holds (a2 #60728 A-1)
  O7 the client a backend's per-visitor cap counts (a2 #60582 A-1): the front names the client IT saw in
     x-astryx-front-client, overwriting one the caller sent; and every header the front SETS (x-forwarded-prefix:
     /o/<org>) is the backend's only copy, never behind a caller's (S3c canvas)
  O8 main.py's _client (read from the source, run alone): one org, the peer exactly as before (the header ignored);
     in a cog, the front's header, and only from 127.0.0.1
  O9 main.py's _upstream (read from the source, run with the REAL orgs module): one org, the fixed loopback port; in a
     cog, the org's registry port, and None for a unit its entry declares no port for, never a raise at import (step 4
     live, 10-19: lab declares no ear and its observatory crash-looped on EAR_UP)
Seams: OBS_FRONT_SRC (a mutant front.py), OBS_MAIN_SRC (a mutant main.py, O8). Exit 0 · 1 · 77 (no uvicorn/httpx).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
fails = []

BACKEND = r"""
import asyncio, json, os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
tag, log = os.environ["FX_TAG"], os.environ["FX_LOG"]
app = FastAPI()

def note(d):
    with open(log, "a") as f:
        f.write(json.dumps(d) + "\n")

@app.get("/api/events")
async def events(request: Request):
    note({"path": "/api/events", "query": dict(request.query_params)})
    async def gen():
        yield ": hello\n\n"
        for i in range(3):
            yield "data: " + json.dumps({"type": "message", "from_org": "local", "to_org": "x", "n": i, "who": tag}) + "\n\n"
            await asyncio.sleep(0.2)
        while True:
            await asyncio.sleep(1)
            yield ": ping\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def echo(path: str, request: Request):
    d = {"tag": tag, "method": request.method, "path": "/" + path, "query": dict(request.query_params),
         "body": (await request.body()).decode(), "key": request.headers.get("x-obs-key"),
         "cookie": request.headers.get("cookie"), "prefix": request.headers.get("x-forwarded-prefix"),
         "client": request.headers.get("x-astryx-front-client")}
    note(d)
    r = JSONResponse(d, status_code=201 if path == "made" else 200, headers={"x-backend": tag})
    if path == "login":
        r.set_cookie("backend_session", "secret-" + tag)
    return r
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def listener() -> socket.socket:
    """A loopback socket, bound and LISTENING, that its uvicorn inherits (--fd): the port is never released for a
    concurrent gate to take (the gate census, plan-10108 D4 (b))."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(64)
    return s


def wait_up(port: int, proc, t: float = 30) -> bool:
    end = time.time() + t
    while time.time() < end and proc.poll() is None:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cog", timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            time.sleep(0.3)
    return False


def call(port, path, method="GET", body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=body,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def lines(log: Path) -> list:
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def main():
    try:
        import httpx  # noqa: F401  (the front's and the backends' deps)
        import uvicorn  # noqa: F401
    except ImportError as e:
        print(f"SKIP (77): {e}")
        return 77
    t = Path(tempfile.mkdtemp(prefix="astryx-obscog-")).resolve()
    procs = []
    try:
        pid = os.getpid()
        oa, ob = f"fxobs-a-{pid}", f"fxobs-b-{pid}"
        na, nb = f"fxobs-fed-a-{pid}", f"fxobs-fed-b-{pid}"
        socks = [listener() for _ in range(3)]
        sa, sb, sf = socks
        pa, pb, pf = (s.getsockname()[1] for s in socks)
        (t / "app.py").write_text(BACKEND)
        reg = {"orgs": {}}
        for o, n, p in ((oa, na, pa), (ob, nb, pb)):
            h = t / o
            h.mkdir()
            (h / ".env").write_text(f"ASTRYX_ORG={n}\nOBS_KEY=never-read-by-the-front\n")
            reg["orgs"][o] = {"home": str(h), "db": f"fxobsdb_{o.replace('-', '_')}",
                              "ports": {"astryx-observatory-org": p}}
        (t / "cog.json").write_text(json.dumps(reg))
        logs = {oa: t / "a.log", ob: t / "b.log"}
        env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
        backs = {}
        for o, s in ((oa, sa), (ob, sb)):
            # own-env: a fixture stub app this oracle wrote (t/app.py), not repo code
            backs[o] = subprocess.Popen([PY, "-m", "uvicorn", "app:app", "--fd", str(s.fileno())],
                                        pass_fds=(s.fileno(),), cwd=t, env={**env, "PYTHONPATH": str(t), "FX_TAG": o, "FX_LOG": str(logs[o])},
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(backs[o])
        front_src = os.environ.get("OBS_FRONT_SRC")          # a mutant front.py (tests/mutants_observatory_cog.py)
        fdir = REPO / "observatory"
        if front_src:
            fdir = t / "observatory"
            fdir.mkdir()
            (fdir / "front.py").write_text(Path(front_src).read_text().replace(
                'ROOT = Path(__file__).resolve().parent', f'ROOT = Path({str(REPO / "observatory")!r})'))
        front = subprocess.Popen([PY, "-m", "uvicorn", "front:app", "--fd", str(sf.fileno())],
                                 pass_fds=(sf.fileno(),), cwd=fdir, env={**env, "ASTRYX_COG_REGISTRY": str(t / "cog.json")},
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append(front)
        for s in socks:          # the children hold them now; a backend that dies must REFUSE, not queue (O-stream)
            s.close()
        up = wait_up(pf, front)
        for o, p in ((oa, pa), (ob, pb)):
            end = time.time() + 20
            while time.time() < end:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{p}/ready", timeout=2)
                    break
                except OSError:
                    time.sleep(0.3)
        for lg in logs.values():
            lg.write_text("")
        check("the front starts under uvicorn", up, "" if up else (front.stdout.read() if front.poll() is not None else ""))

        print("\nO1 /api/cog IS THE COG")
        st, _, body = call(pf, "/api/cog")
        d = json.loads(body) if st == 200 else {}
        want = [{"org": oa, "name": na, "base": f"/o/{oa}/"}, {"org": ob, "name": nb, "base": f"/o/{ob}/"}]
        check("both orgs, sorted, federation names from each HOME's .env, /o/<org>/ bases, home null, no port",
              d == {"cog": True, "home": None, "orgs": want}, body[:300])
        check("the front's own: no backend saw /api/cog", not lines(logs[oa]) and not lines(logs[ob]))

        print("\nO2 /o/<a>/ IS A'S BACKEND, AND ONLY A'S")
        st, hd, body = call(pf, f"/o/{oa}/made?x=1&y=two", "POST", b"payload-bytes",
                            {"x-obs-key": "the-callers-key", "cookie": "astryx_org=zzz; other=1"})
        la, lb = lines(logs[oa]), lines(logs[ob])
        e = la[-1] if la else {}
        check("A's backend got POST /made?x=1&y=two with the body, the caller's x-obs-key and cookie exactly",
              e.get("method") == "POST" and e.get("path") == "/made" and e.get("query") == {"x": "1", "y": "two"}
              and e.get("body") == "payload-bytes" and e.get("key") == "the-callers-key"
              and e.get("cookie") == "astryx_org=zzz; other=1" and e.get("prefix") == f"/o/{oa}", str(e))
        check("the backend's status (201) and header come back", st == 201 and hd.get("x-backend") == oa, f"{st} {hd}")
        check("B's backend saw nothing", not lb, str(lb))

        print("\nO3 UNKNOWN ORGS AND DOTTED PATHS")
        st, _, _ = call(pf, "/o/no-such-org/api/overview")
        check("an org the registry doesn't hold: 404, no backend hit", st == 404 and len(lines(logs[oa])) == 1
              and not lines(logs[ob]), str(st))
        call(pf, f"/o/{oa}/x/../{ob}/api/overview")
        check("a dotted path under /o/<a>/ never reaches B", not lines(logs[ob]), str(lines(logs[ob])))

        print("\nO4 THE ROOT API FOLLOWS THE VIEWER'S CHOICE, NEVER A DEFAULT")
        n0a, n0b = len(lines(logs[oa])), len(lines(logs[ob]))
        st, _, body = call(pf, "/api/agents")
        check("nothing chosen: 409 naming /api/cog, no backend hit",
              st == 409 and '"/api/cog"' in body and len(lines(logs[oa])) == n0a and len(lines(logs[ob])) == n0b,
              f"{st} {body[:120]}")
        st, _, body = call(pf, "/api/agents", headers={"cookie": "astryx_org=no-such-org"})
        check("a cookie naming no org of this cog: 409", st == 409, str(st))
        st, _, body = call(pf, "/api/agents?z=9", headers={"cookie": f"astryx_org={ob}"})
        e = json.loads(body) if st == 200 else {}
        check("cookie astryx_org=<b>: B's backend, as /api/agents?z=9",
              e.get("tag") == ob and e.get("path") == "/api/agents" and e.get("query") == {"z": "9"}, body[:200])
        st, _, body = call(pf, "/api/agents", headers={"cookie": f"astryx_org={ob}", "x-astryx-org": oa})
        check("the x-astryx-org header wins over the cookie", st == 200 and json.loads(body).get("tag") == oa, body[:200])

        print("\nO5 NO AUTHORITY ADDED")
        call(pf, f"/o/{oa}/plain")
        e = lines(logs[oa])[-1]
        check("a caller with no x-obs-key reaches the backend with none", e.get("key") is None, str(e))
        call(pf, f"/o/{oa}/login")
        call(pf, f"/o/{oa}/after")
        e = lines(logs[oa])[-1]
        check("a backend's Set-Cookie is never replayed to the next caller (the jar stores nothing)",
              e.get("path") == "/after" and not (e.get("cookie") or ""), str(e))

        print("\nO7 THE FRONT NAMES THE CLIENT IT SAW")
        call(pf, f"/o/{oa}/who", headers={"x-astryx-front-client": "203.0.113.66"})
        e = lines(logs[oa])[-1]
        check("a caller's own x-astryx-front-client is overwritten with the address the front saw (127.0.0.1 here)",
              e.get("path") == "/who" and e.get("client") == "127.0.0.1", str(e))
        call(pf, f"/o/{oa}/pre", headers={"x-forwarded-prefix": "/o/evil"})
        e = lines(logs[oa])[-1]
        check(f"a caller's own x-forwarded-prefix never reaches the backend: it reads the front's /o/{oa}",
              e.get("path") == "/pre" and e.get("prefix") == f"/o/{oa}", str(e))

        print("\nO8 main.py's _client")
        import ast
        src = Path(os.environ.get("OBS_MAIN_SRC") or REPO / "observatory" / "api" / "main.py").read_text()
        fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_client")

        class Req:
            def __init__(self, peer, hdr=None):
                self.client = type("C", (), {"host": peer})()
                self.headers = hdr or {}

        def client_of(cog, peer, hdr=None):
            ns = {"Request": object, "_COG": cog}
            exec(compile(ast.Module([fn], []), "main.py", "exec"), ns)
            return ns["_client"](Req(peer, hdr))
        H = {"x-astryx-front-client": "198.51.100.4"}
        check("one org: the peer, the header ignored", client_of(False, "127.0.0.1", H) == "127.0.0.1"
              and client_of(False, "192.0.2.9", H) == "192.0.2.9")
        check("a cog, from 127.0.0.1: the front's header", client_of(True, "127.0.0.1", H) == "198.51.100.4")
        check("a cog, from anywhere else: the peer (a direct caller can't name itself)",
              client_of(True, "192.0.2.9", H) == "192.0.2.9")

        print("\nO9 main.py's _upstream: A UNIT AN ORG DOESN'T RUN")
        up = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_upstream")
        probe = ("import ast, json, sys\nsys.path.insert(0, sys.argv[1])\nfrom astryx import orgs\nns = {'orgs': orgs}\n"
                 "exec(compile(ast.Module([ast.parse(sys.argv[2]).body[0]], []), 'main.py', 'exec'), ns)\n"
                 "print(json.dumps([ns['_upstream'](s, f) for s, f in (('astryx-observatory-org', 1), ('astryx-ear', 8092))]))")

        def upstream(extra):
            r = subprocess.run([PY, "-c", probe, str(REPO / "src"), ast.unparse(up)], capture_output=True, text=True,
                               timeout=60, env={**env, **extra})
            try:
                return json.loads(r.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                return (r.stdout + r.stderr)[-300:]
        one = upstream({"ASTRYX_COG_REGISTRY": str(t / "no-registry.json"), "ASTRYX_HOME": str(t / oa)})
        check("one org: the fixed loopback port, as before", one == ["http://127.0.0.1:1", "http://127.0.0.1:8092"],
              str(one))
        cog = upstream({"ASTRYX_COG_REGISTRY": str(t / "cog.json"), "ASTRYX_HOME": str(t / oa)})
        check("a cog: the org's registry port, and None (never a raise) for the ear its entry declares no port for",
              cog == [f"http://127.0.0.1:{pa}", None], str(cog))

        print("\nO6 ONE MERGED STREAM")
        got, saw_down = [], False
        with urllib.request.urlopen(f"http://127.0.0.1:{pf}/api/cog/stream?key=K-stream", timeout=30) as r:
            end = time.time() + 20
            killed = False
            while time.time() < end:
                ln = r.readline().decode()
                if ln.startswith("data: "):
                    item = json.loads(ln[6:])
                    got.append(item)
                    ev = item.get("event", {})
                    if ev.get("type") == "cog_backend" and ev.get("up") is False and item.get("org") == ob:
                        saw_down = True
                        break
                msgs = {(i["org"], i["event"].get("n")) for i in got if i.get("event", {}).get("type") == "message"}
                if not killed and {(oa, 2), (ob, 2)} <= msgs:
                    backs[ob].kill()                 # a death, not a graceful stop (that waits on the stream)
                    killed = True
        wrapped = [i for i in got if i.get("event", {}).get("type") == "message"]
        check("both backends' events, each wrapped with its org and federation name",
              {(i["org"], i["name"], i["event"]["who"]) for i in wrapped} == {(oa, na, oa), (ob, nb, ob)}, str(got[:6]))
        q = [x["query"] for o in (oa, ob) for x in lines(logs[o]) if x.get("path") == "/api/events"]
        check("?key= forwarded to each backend's /api/events", q.count({"key": "K-stream"}) >= 2, str(q))
        check("a backend that dies is announced: cog_backend up=false for its org", saw_down, str(got[-3:]))
        t0 = time.time()
        try:
            code = call(pf, f"/o/{ob}/api/x")[0]
        except OSError as e:                         # a connect queued in a backlog nobody accepts: the timeout
            code = type(e).__name__
        took = time.time() - t0
        check("a call to the dead backend is refused at once: 502 in under 5s", code == 502 and took < 5,
              f"{code} after {took:.1f}s")
        return 1 if fails else 0
    finally:
        for pr in procs:
            if pr.poll() is None:
                pr.terminate()
                try:
                    pr.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pr.kill()
        import shutil
        shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("observatory cog: one front for every org, a byte pipe to each org's own observatory, no authority added")
    sys.exit(rc)
