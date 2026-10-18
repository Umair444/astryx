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
     each; a backend that dies is announced {"type": "cog_backend", "up": false} for its org
Exit 0 · 1 · 77 (no uvicorn/httpx).
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
         "cookie": request.headers.get("cookie"), "prefix": request.headers.get("x-forwarded-prefix")}
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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        pa, pb, pf = free_port(), free_port(), free_port()
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
        for o, p in ((oa, pa), (ob, pb)):
            backs[o] = subprocess.Popen([PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(p)],
                                        cwd=t, env={**env, "PYTHONPATH": str(t), "FX_TAG": o, "FX_LOG": str(logs[o])},
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(backs[o])
        front_src = os.environ.get("OBS_FRONT_SRC")          # a mutant front.py (tests/mutants_observatory_cog.py)
        fdir = REPO / "observatory"
        if front_src:
            fdir = t / "observatory"
            fdir.mkdir()
            (fdir / "front.py").write_text(Path(front_src).read_text().replace(
                'ROOT = Path(__file__).resolve().parent', f'ROOT = Path({str(REPO / "observatory")!r})'))
        front = subprocess.Popen([PY, "-m", "uvicorn", "front:app", "--host", "127.0.0.1", "--port", str(pf)],
                                 cwd=fdir, env={**env, "ASTRYX_COG_REGISTRY": str(t / "cog.json")},
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append(front)
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
