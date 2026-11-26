#!/usr/bin/env python3
"""tests/test_etl_mcp.py — the etl MCP server (mcp/etl) without the box or Prefect's database.

The box door (box.run) and the pf reads are stubbed; each snippet that guards an argument is executed here under
Windows path rules (ntpath) with spies on what it would open or run. Arms (medic 14956):
  A1 every act refuses a seat outside the etl composite, and nothing reaches the box
  A2 etl_flow_run takes only an exact deployment name
  A3 etl_log_tail: an absolute, drive, UNC or '..' path is refused BEFORE realpath (realpath opens it on Windows)
  A4 box.run: a kernel that stalls past its timeout is shut down (DELETE /api/kernels/<id>), not just forgotten
  A5 the job acts: a name must be in the folder's listing, exactly; '<folder>..\\<task>' is refused
  A6 etl_failures is a digest: one row per job, a cause class from the error's tail, secrets in URLs masked; detail= one job
  A6b credential values in error tails (key=value, PWD=, quoted, a URL password holding @) are masked in both modes
  A7 etl_flow_run params: a flat object of scalars passes as --params json; anything else is refused before the box
  A8 etl_jobs: name_like matches the name, command or start-in dir; no filter gives counts per folder and state
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


# ---- A6: the failure digest, pf stubbed
ERR_RB = "Script: x.py\n====\nTraceback (most recent call last):\n  File \"y.py\", line 3\nMemoryError\n----\nScript completed\n===="
ERR_GIT = "The existing repository at D:\\T\\etl_system-main does not match the configured repository https://u:tok@github.com/o/r"
pf_rows = {"flow": [{"job": "f/a", "flow_run_id": "1", "state": "FAILED", "at": "t2", "error": ERR_GIT},
                    {"job": "f/a", "flow_run_id": "2", "state": "FAILED", "at": "t1", "error": "exited with status code: 1"}],
           "report": [{"job": "r1", "at": "t3", "exit_code": 1, "state": "FAILED", "error": ERR_RB}]}
srv._rows = lambda sql, p: pf_rows["flow" if "flow_run" in sql else "report"]
d = srv.etl_failures(hours=24)
fa = d["flows"][0]
check("A6 one row per job, counted", len(d["flows"]) == 1 and fa["fails"] == 2 and fa["first"] == "t1" and fa["last"] == "t2", str(d))
check("A6 the cause comes from the latest failure", fa["cause"] == "git", str(fa))
check("A6 a credential in a URL is masked", "tok" not in str(d) and "://***@" in fa["error"], fa["error"])
r1 = d["reports"][0]
check("A6 a run.bat log's exception line, not its banner", r1["cause"] == "memory" and r1["error"] == "MemoryError", str(r1))
check("A6 causes are counted per job", d["causes"] == {"git": 1, "memory": 1}, str(d["causes"]))
dd = srv.etl_failures(hours=24, detail="f/a")
check("A6 detail= returns that job's runs, masked", len(dd["runs"]) == 2 and "tok" not in str(dd), str(dd)[:200])
check("A6 detail= of an unknown job is a plain error", "no failure" in str(srv.etl_failures(detail="nope")))

# ---- A6b: credentials in traceback source lines never reach the wire (medic 15179)
V = "Zq7#secretval"
leaks = ['  File "x.py", line 9, in c\n    con = connect(host=h, password="' + V + '")\nOperationalError: boom',
         "Driver: PWD=" + V + ";UID=u\nDatabaseError: x",
         "connection failed: password='" + V + "'\nRuntimeError: y",
         "sqlalchemy.exc: postgresql://u:p@" + V + "@h/db\nOperationalError: z",
         'connect(password="Hun ter2x, ' + V + '")\nOperationalError: a',            # quoted, with a space and a comma
         'connect(password="x,' + V + '")\nOperationalError: b',
         "password='x;" + V + "'\nOperationalError: c",
         "{'user': 'u', 'password': 'a b, " + V + "'}\nKeyError: d",               # a dict repr
         '{"password": "a b, ' + V + '"}\nValueError: e',
         'con = connect(password="a b ' + V + '\nSyntaxError: unterminated string',
         "DB_PASSWORD=" + V + "\nKeyError: env",                                    # an env/config line
         "Authorization: Bearer " + V + "\nHTTPError: 401",
         "SECRET_KEY=" + V + "\nKeyError: a", "aws_secret_access_key = " + V + "\nKeyError: b",   # a key with a suffix
         "db_pass='" + V + "'\nKeyError: c"]                          # an HTTP error dump   # a quote cut off by the tail                           # json
pf_rows = {"flow": [], "report": [{"job": f"L{i}", "at": "t", "exit_code": 1, "state": "FAILED", "error": e}
                                  for i, e in enumerate(leaks)]}
d = srv.etl_failures(hours=24)
check("A6b no credential value in the digest", V not in str(d) and "secretval" not in str(d), str(d)[:300])
dd = [srv.etl_failures(hours=24, detail=f"L{i}") for i in range(len(leaks))]
check("A6b ...nor in any detail=", V not in str(dd) and "secretval" not in str(dd), str(dd)[:300])
check("A6b the key name stays, readable", "password=" in str(dd[0]) and "***" in str(dd[0]), str(dd[0])[:200])
check("A6b ordinary code is left alone", all(srv._mask(s) == s for s in
      ["bypass_cache=True", "compass=north", "passed=3 failed=1", "if password == stored:", "row['password']"]),
      str([srv._mask(s) for s in ["bypass_cache=True", "if password == stored:"]]))
check("A6b a plain password=password reads as itself or masked", srv._mask("password=password") in
      ("password=password", "password=***"), srv._mask("password=password"))
sent.clear()
for bad in [{"x": float("nan")}, {"x": float("inf")}]:
    check(f"A7 refused: {bad}", str(run(srv.etl_flow_run("a/b", bad))).startswith("error: params"))
check("A7 ...non-finite floats never reach the box", sent == [], str(sent))

# ---- A7: flow_run params
sent.clear()
out = run(srv.etl_flow_run("a/b", {"run_date": "2026-11-15", "full": False}))
check("A7 params pass as one --params json value",
      sent and sent[-1]["argv"] == ["deployment", "run", "a/b", "--params", '{"run_date": "2026-11-15", "full": false}'], str(sent))
sent.clear()
for bad in [{"x": {"nested": 1}}, {"x": [1]}, {"--flag": 1}, {"a b": 1}, {"x": "y" * 201}, {f"k{i}": 1 for i in range(21)}, "run_date=1"]:
    o = run(srv.etl_flow_run("a/b", bad))
    check(f"A7 refused: {str(bad)[:40]}", str(o).startswith("error: params"), str(o))
check("A7 ...and nothing reached the box", sent == [], str(sent))
os.environ["ASTRYX_AGENT"] = "db"
check("A7 params do not open the gate to other seats", str(run(srv.etl_flow_run("a/b", {"d": 1}))).startswith("refused"))
os.environ["ASTRYX_AGENT"] = "etl-ops"

# ---- A8: etl_jobs matches a name OR a path part, and with no filter returns counts, not every row
import csv as _csv, io as _io, json as _json, subprocess as _sp
_cols = ["TaskName", "Scheduled Task State", "Status", "Next Run Time", "Last Run Time", "Last Result",
         "Run As User", "Task To Run", "Start In", "Schedule Type", "Start Time", "Days", "Repeat: Every"]
_buf = _io.StringIO(); _w = _csv.writer(_buf); _w.writerow(_cols)
_w.writerow(["\\BI Jobs\\Daily Scoll Summary DAT Report", "Enabled", "Ready", "", "", "0", "SYSTEM",
             "D:\\ETL\\ADHOC\\PESCO FTP\\run_scroll_report.bat", "D:\\ETL\\ADHOC\\PESCO FTP", "Daily", "9:01", "", ""])
_w.writerow(["\\BI Jobs\\team\\lending", "Disabled", "Ready", "", "", "0", "SYSTEM", "run.bat", "D:\\ETL\\L", "Daily", "9:40", "", ""])
_w.writerow(["\\Other\\x", "Enabled", "Ready", "", "", "0", "SYSTEM", "D:\\PESCO FTP\\x.bat", "", "Daily", "1:00", "", ""])
_real_run = _sp.run


def jobs_snippet(like):
    out = _io.StringIO()
    _sp.run = lambda *a, **k: types.SimpleNamespace(stdout=_buf.getvalue(), returncode=0)
    real_stdout, sys.stdout = sys.stdout, out
    try:
        exec(srv._JOBS, {"ARGS": {"folder": "\\BI Jobs\\", "like": like}})
    finally:
        sys.stdout, _sp.run = real_stdout, _real_run
    return _json.loads(out.getvalue())


hit = jobs_snippet("pesco ftp")
check("A8 a path part finds the task (its name doesn't say PESCO FTP); the folder still bounds it",
      [j["name"] for j in hit.get("jobs", [])] == ["\\BI Jobs\\Daily Scoll Summary DAT Report"], str(hit)[:200])
summ = jobs_snippet("")
check("A8 no filter: counts per folder and state, no rows",
      "jobs" not in summ and summ.get("count") == 2 and {(r["folder"], r["state"], r["jobs"]) for r in summ["by_folder_state"]}
      == {("\\BI Jobs\\", "Enabled", 1), ("\\BI Jobs\\team\\", "Disabled", 1)}, str(summ)[:300])

# ---- A9: etl_box_pull deploys main as a bundle, on real git repos (origin, the local clone, the box), the box side
# executed here: a box already at main, a fast-forward with an unrelated local edit kept, a clash, a diverged box,
# a damaged bundle, and the bundle always removed
import base64 as _b64, contextlib as _cl, tempfile as _tf
from pathlib import Path as _P
_t = _P(_tf.mkdtemp())
G = lambda d, *a: _real_run(["git", "-C", str(d), *a], capture_output=True, text=True, check=True).stdout.strip()
_real_run(["git", "init", "-q", "--bare", "-b", "main", str(_t / "origin.git")], check=True)
for _d in ("seed", "local", "boxr"):
    _real_run(["git", "clone", "-q", str(_t / "origin.git"), str(_t / _d)], check=True, capture_output=True)
    G(_t / _d, "config", "user.email", "t@t"); G(_t / _d, "config", "user.name", "t")


def commit(msg, **files):
    for k, v in files.items():
        (_t / "seed" / k).write_text(v)
    G(_t / "seed", "add", "-A"); G(_t / "seed", "commit", "-qm", msg); G(_t / "seed", "push", "-q", "origin", "HEAD:main")


commit("c1", a="1\n", b="1\n")
G(_t / "boxr", "pull", "-q", "origin", "main")
srv.LOCAL, srv.ROOT, srv.GIT = _t / "local", str(_t / "boxr"), "git"
tamper = {"on": False}


async def box_here(snippet, args, timeout=120):
    a = dict(args)
    if tamper["on"] and "bundle" in a:
        a["bundle"] = _b64.b64encode(_b64.b64decode(a["bundle"])[:-7]).decode()   # an upload cut short
    buf = _io.StringIO()
    with _cl.redirect_stdout(buf):
        exec(snippet, {"ARGS": a})
    return _json.loads(buf.getvalue().splitlines()[-1])

srv.box.run = box_here
r = run(srv.etl_box_pull())
check("A9 a box already at main: ok, nothing sent", r.get("ok") and r.get("note") == "already at main", str(r)[:200])
commit("c2", a="2\n")
(_t / "boxr" / "b").write_text("box edit\n")
r = run(srv.etl_box_pull())
check("A9 fast-forward to main; the unrelated local edit is kept and listed",
      r.get("ok") and r["after"] == G(_t / "seed", "rev-parse", "HEAD") and r["local_edits"] == ["b"]
      and (_t / "boxr" / "b").read_text() == "box edit\n" and r.get("bundle_removed"), str(r)[:300])
commit("c3", b="3\n")
before = G(_t / "boxr", "rev-parse", "HEAD")
r = run(srv.etl_box_pull())
check("A9 a local edit on a file the deploy changes: refused, box unchanged",
      "clash" in r and r["clash"] == ["b"] and G(_t / "boxr", "rev-parse", "HEAD") == before
      and (_t / "boxr" / "b").read_text() == "box edit\n", str(r)[:300])
G(_t / "boxr", "checkout", "-q", "--", "b")
tamper["on"] = True
r = run(srv.etl_box_pull())
check("A9 a damaged upload: refused by sha256, box unchanged, no bundle left",
      "damaged" in r.get("error", "") and G(_t / "boxr", "rev-parse", "HEAD") == before and r.get("bundle_removed")
      and not list(_P(_tf.gettempdir()).glob("etl_box_pull_*.bundle")), str(r)[:300])
tamper["on"] = False
(_t / "boxr" / "z").write_text("z\n"); G(_t / "boxr", "add", "z"); G(_t / "boxr", "commit", "-qm", "box-only")
r = run(srv.etl_box_pull())
check("A9 a diverged box (a commit main doesn't have): refused before anything is sent",
      "diverged" in r.get("error", "") and "bundle_removed" not in r, str(r)[:300])
G(_t / "boxr", "reset", "-q", "--hard", "HEAD~1")
r = run(srv.etl_box_pull())
check("A9 the clean box then deploys main", r.get("ok") and r["after"] == G(_t / "seed", "rev-parse", "HEAD"), str(r)[:300])
os.environ["ASTRYX_AGENT"] = "db"
check("A9 other seats are refused", str(run(srv.etl_box_pull())).startswith("refused"))
os.environ["ASTRYX_AGENT"] = "etl-ops"

print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else "PASS: the etl server's guards hold without the box")
sys.exit(1 if fails else 0)

