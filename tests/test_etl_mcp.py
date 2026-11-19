#!/usr/bin/env python3
"""tests/test_etl_mcp.py — the etl MCP server (mcp/etl) without the box or Prefect's database.

The box door (box.run) and the pf reads are stubbed; each snippet that guards an argument is executed here under
Windows path rules (ntpath) with spies on what it would open or run. Arms (medic 14956):
  A1 every act refuses a seat outside the etl composite, and nothing reaches the box
  A2 etl_flow_run takes only an exact deployment name
  A3 etl_log_tail: an absolute, drive, UNC or '..' path is refused BEFORE realpath (realpath opens it on Windows)
  A4 box.run: a kernel that stalls past its timeout is shut down (DELETE /api/kernels/<id>), not just forgotten
  A5 the job acts: a name must be in the folder's listing, exactly; '<folder>..\\<task>' is refused
Seam: ETL_SERVER_SRC / ETL_BOX_SRC (a mutant copy). Exit 0 · 1.
"""
import asyncio
import importlib.util
import ntpath
import os
import re
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRV = Path(os.environ.get("ETL_SERVER_SRC") or REPO / "mcp/etl/server.py")
BOX = Path(os.environ.get("ETL_BOX_SRC") or REPO / "mcp/etl/box.py")
os.environ.update(ETL_ROOT="D:\\etl_system", ETL_TASK_FOLDER="\\BI Jobs\\team\\", ETL_JUPYTER="box.test:8950")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        fails.append(name)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


box = load("box", BOX)
srv = load("etl_server", SRV)
run = asyncio.run
box_run = box.run          # the real door, kept before A1 stubs it (the server holds the same module)

# ---- A1, A2: the acts' gate, with the box and pf stubbed
sent = []


async def fake_run(snippet, args, timeout=120):
    sent.append(args)
    return {"ok": 1}

srv.box.run = fake_run
srv.etl_deployments = lambda **k: [{"deployment": "a/b"}, {"deployment": "a/bc"}]
UID = "0" * 8 + "-0000-0000-0000-" + "0" * 12
acts = [(srv.etl_job_run, ("\\BI Jobs\\team\\x",)), (srv.etl_job_stop, ("x",)), (srv.etl_job_enable, ("x", True)),
        (srv.etl_flow_run, ("a/b",)), (srv.etl_flow_cancel, (UID,)), (srv.etl_box_pull, ())]
os.environ["ASTRYX_AGENT"] = "db"
outs = [run(f(*a)) for f, a in acts]
check("A1 every act refuses a seat outside the etl composite", all(str(o).startswith("refused") for o in outs), str(outs))
check("A1 ...and nothing reached the box", sent == [], str(sent))
os.environ["ASTRYX_AGENT"] = "etl-ops"
check("A2 flow_run refuses a pattern ('a/b%')", "no deployment" in str(run(srv.etl_flow_run("a/b%"))))
check("A2 ...and a prefix of a real name ('a/')", "no deployment" in str(run(srv.etl_flow_run("a/"))))
sent.clear()
run(srv.etl_flow_run("a/b"))
check("A2 ...and takes the exact name", sent and sent[-1]["argv"] == ["deployment", "run", "a/b"], str(sent))


# ---- A3: the tail snippet under Windows path rules, realpath spied
def tail(path):
    seen, out = [], []
    fake_os = types.SimpleNamespace(sep="\\", path=types.SimpleNamespace(
        join=ntpath.join, isfile=lambda p: False, realpath=lambda p: (seen.append(p), ntpath.normpath(p))[1]))
    g = {"ARGS": {"root": "D:\\etl_system", "path": path, "n": 5}, "print": out.append, "os": fake_os}
    exec(re.sub(r"^import (.*)$", lambda m: "import " + ", ".join(x for x in m.group(1).split(", ") if x != "os"),
                srv._TAIL, count=1, flags=re.M), g)     # the snippet's own `os` is the spy, whatever else it imports
    return seen, out[0] if out else ""


for p in ["\\\\evil.host\\share\\x", "//evil.host/share/x", "C:\\Windows\\win.ini", "C:win.ini", "\\Windows\\win.ini",
          "..\\..\\Windows\\win.ini", "logs\\..\\..\\x", ""]:
    seen, out = tail(p)
    check(f"A3 {p!r} is refused before realpath opens anything", seen == [] and "outside" in out, f"realpath on {seen}: {out}")
seen, out = tail("logs\\ETL_log.txt")
check("A3 a path inside the root reaches realpath, joined to the root",
      seen and seen[-1] == "D:\\etl_system\\logs\\ETL_log.txt", str(seen))


# ---- A4: a stalled kernel is shut down
class Stall:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, m):
        pass

    async def recv(self):
        await asyncio.sleep(3600)


def a4():
    import httpx
    hits = []

    def handler(req):
        hits.append((req.method, req.url.path))
        if req.method == "POST" and req.url.path == "/api/kernels":
            return httpx.Response(201, json={"id": "k-stalled"})
        return httpx.Response(200, json={})

    real = httpx.AsyncClient
    box.httpx = types.SimpleNamespace(AsyncClient=lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    box.websockets = types.SimpleNamespace(connect=lambda *a, **kw: Stall())
    box._kernel = None
    res = run(box_run("print(1)", {}, timeout=0.2))
    return hits, res


hits, res = a4()
check("A4 a snippet past its timeout returns a plain error", "did not answer" in str(res.get("error", "")), str(res))
check("A4 ...and the stalled kernel is shut down (DELETE /api/kernels/k-stalled)",
      ("DELETE", "/api/kernels/k-stalled") in hits, str(hits))
check("A4 ...and never reused", box._kernel is None, str(box._kernel))


# ---- A5: the job acts take only a listed name
def task(name, listing):
    calls, out = [], []

    def fake_run(argv, **kw):
        calls.append(argv)
        stdout = "".join(f'"{n}","N/A","Ready"\n' for n in listing) if argv[1:3] == ["/query", "/fo"] else ""
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    g = {"ARGS": {"name": name, "op": "run", "folder": "\\BI Jobs\\team\\"}, "print": out.append,
         "subprocess": types.SimpleNamespace(run=fake_run)}
    exec(re.sub(r"^import (.*)$", lambda m: "import " + ", ".join(x for x in m.group(1).split(", ") if x != "subprocess"),
                srv._TASK, count=1, flags=re.M), g)
    acted = [c for c in calls if "/run" in c]
    return acted, out[0] if out else ""


L = ["\\BI Jobs\\team\\daily_report", "\\Microsoft\\Windows\\Defrag\\ScheduledDefrag"]
acted, out = task("\\BI Jobs\\team\\..\\..\\Microsoft\\Windows\\Defrag\\ScheduledDefrag", L)
check("A5 '<folder>..\\..\\<task>' is refused and nothing runs", acted == [] and "outside" in out, out)
acted, out = task("\\BI Jobs\\team\\nope", L)
check("A5 a name not in the listing is refused", acted == [] and "no such job" in out, out)
acted, out = task("\\BI JOBS\\TEAM\\DAILY_REPORT", L)
check("A5 a listed name runs, as the listing spells it", acted == [["schtasks", "/run", "/tn", L[0]]], f"{acted} {out}")

print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else "PASS: the etl server's guards hold without the box")
sys.exit(1 if fails else 0)
