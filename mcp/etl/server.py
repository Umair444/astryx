#!/usr/bin/env python3
"""astryx · etl MCP server — the ETL box as typed tools (owner 14837/14915: "create the tools").

An ETL estate of this shape: a Windows box running Task Scheduler jobs and Prefect deployments, reached through its
Jupyter (box.py), with Prefect's own database readable as a Postgres key. Reads come from Prefect's database directly
(typed, cheap) and from fixed snippets on the box; acts are fixed snippets too, the caller's arguments only ever a
JSON value the snippet decodes and checks.

Reads are open to every seat granted `etl`. Acts are the etl seats' (local.md, the etl composite exception): their
deploy gate (a second seat's PASS on the thread) is law, not this server's to enforce; the ledger records every call.

Config (.env): ETL_JUPYTER (default SMS_JUPYTER), ETL_ROOT (the repo on the box), ETL_TASK_FOLDER (e.g. \\BI Jobs\\),
ETL_PREFECT (prefect.exe on the box), ETL_GIT (git.exe on the box), ETL_PF_KEY (the creds key of Prefect's database).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import box  # noqa: E402

mcp = FastMCP("etl")
SEATS = {"etl-architect", "etl-reviewer", "etl-ops"}
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _env() -> dict:
    """The org's .env (only the ETL_* and SMS_JUPYTER lines), read once; the process env wins."""
    out = {}
    try:
        for line in (REPO / ".env").read_text().splitlines():
            k, _, v = line.partition("=")
            if k.startswith("ETL_") or k == "SMS_JUPYTER":
                out[k] = v.strip()
    except OSError:
        pass
    out.update({k: v for k, v in os.environ.items() if k.startswith("ETL_")})
    for k, v in out.items():
        os.environ.setdefault(k, v)
    return out


CFG = _env()
ROOT = CFG.get("ETL_ROOT", "")
FOLDER = CFG.get("ETL_TASK_FOLDER", "\\BI Jobs\\")
PREFECT = CFG.get("ETL_PREFECT", "prefect")
GIT = CFG.get("ETL_GIT", "git")


def _me() -> str:
    return os.environ.get("ASTRYX_AGENT", "unknown")


def _refuse() -> str | None:
    return None if _me() in SEATS else f"refused: acting on the ETL is the etl seats' ({', '.join(sorted(SEATS))})"


def _pf():
    """Prefect's database, read-only."""
    import psycopg
    c = json.loads((REPO / "creds/database_creds.json").read_text())[CFG.get("ETL_PF_KEY", "pf")]
    cn = psycopg.connect(host=c["host"], port=c["port"], dbname=c["database"], user=c["user"],
                         password=c["password"], connect_timeout=10, autocommit=True)
    cn.execute("SET default_transaction_read_only = on; SET statement_timeout = '60s'")
    return cn


def _rows(sql: str, params: dict) -> list[dict]:
    with _pf() as cn:
        cur = cn.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [{k: _plain(v) for k, v in zip(cols, r)} for r in cur.fetchall()]


def _plain(v):
    """A value the wire carries: times as ISO text, uuids/decimals/intervals as text, json as itself."""
    if v is None or isinstance(v, (str, int, float, bool, list, dict)):
        return v
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


# ------------------------------------------------------------------ Prefect (from its database)

@mcp.tool()
def etl_deployments(name_like: str = "", days: int = 30, only_failing: bool = False) -> list[dict] | str:
    """Every Prefect deployment ('flow/deployment') with its schedules, paused flag, entrypoint and path, and its last
    `days` of runs: runs, fails (FAILED or CRASHED), last state, last run and last success. name_like filters by
    substring. Failing first."""
    try:
        rows = _rows("""
            WITH r AS (
              SELECT deployment_id, count(*) AS runs,
                     count(*) FILTER (WHERE state_type IN ('FAILED','CRASHED')) AS fails,
                     max(start_time) FILTER (WHERE state_type = 'COMPLETED') AS last_success,
                     (array_agg(state_type ORDER BY coalesce(start_time, expected_start_time) DESC))[1] AS last_state,
                     max(coalesce(start_time, expected_start_time)) AS last_run
                FROM prefect.flow_run
               WHERE coalesce(start_time, expected_start_time) BETWEEN now() - make_interval(days => %(days)s) AND now()
               GROUP BY deployment_id)
            SELECT f.name || '/' || d.name AS deployment, d.paused, d.entrypoint, d.path, d.work_queue_name,
                   coalesce((SELECT json_agg(json_build_object('schedule', s.schedule, 'active', s.active))
                               FROM prefect.deployment_schedule s WHERE s.deployment_id = d.id), '[]') AS schedules,
                   coalesce(r.runs, 0) AS runs, coalesce(r.fails, 0) AS fails, r.last_state, r.last_run, r.last_success
              FROM prefect.deployment d JOIN prefect.flow f ON f.id = d.flow_id LEFT JOIN r ON r.deployment_id = d.id
             WHERE (f.name || '/' || d.name) ILIKE %(like)s
             ORDER BY coalesce(r.fails, 0) DESC, 1""", {"days": max(1, min(days, 365)), "like": f"%{name_like}%"})
        return [r for r in rows if r["fails"]] if only_failing else rows
    except Exception as e:
        return f"error: Prefect's database: {type(e).__name__}: {str(e)[:300]}"


@mcp.tool()
def etl_flow_run_logs(flow_run_id: str, tail: int = 100, min_level: int = 0) -> dict | str:
    """One flow run: its deployment, state and times, and its last `tail` log lines (min_level 40 = errors only)."""
    if not UUID.match(flow_run_id or ""):
        return "error: flow_run_id is a uuid"
    try:
        run = _rows("""SELECT fr.id, fr.name, f.name || '/' || coalesce(d.name, '?') AS deployment, fr.state_type,
                              fr.state_name, fr.start_time, fr.end_time, fr.total_run_time::text AS run_time
                         FROM prefect.flow_run fr JOIN prefect.flow f ON f.id = fr.flow_id
                         LEFT JOIN prefect.deployment d ON d.id = fr.deployment_id WHERE fr.id = %(id)s""",
                    {"id": flow_run_id})
        if not run:
            return "error: no such flow run"
        logs = _rows("""SELECT timestamp, level, name, left(message, 2000) AS message FROM prefect.log
                         WHERE flow_run_id = %(id)s AND level >= %(lv)s ORDER BY timestamp DESC LIMIT %(n)s""",
                     {"id": flow_run_id, "lv": min_level, "n": max(1, min(tail, 1000))})
        return {**run[0], "logs": logs[::-1]}
    except Exception as e:
        return f"error: Prefect's database: {type(e).__name__}: {str(e)[:300]}"


@mcp.tool()
def etl_failures(hours: int = 24) -> dict | str:
    """Everything that failed in the last `hours`, in one call: Prefect flow runs FAILED or CRASHED (with the last
    error line of each) and run.bat reports whose status in prefect.reporting_logs isn't success."""
    try:
        h = {"h": max(1, min(hours, 24 * 30))}
        flows = _rows("""
            SELECT f.name || '/' || coalesce(d.name, '?') AS deployment, fr.id AS flow_run_id, fr.state_type,
                   fr.start_time, fr.end_time,
                   (SELECT left(l.message, 400) FROM prefect.log l WHERE l.flow_run_id = fr.id AND l.level >= 40
                     ORDER BY l.timestamp DESC LIMIT 1) AS last_error
              FROM prefect.flow_run fr JOIN prefect.flow f ON f.id = fr.flow_id
              LEFT JOIN prefect.deployment d ON d.id = fr.deployment_id
             WHERE fr.state_type IN ('FAILED','CRASHED')
               AND coalesce(fr.end_time, fr.state_timestamp) > now() - make_interval(hours => %(h)s)
             ORDER BY coalesce(fr.end_time, fr.state_timestamp) DESC""", h)
        reports = _rows("""
            SELECT report_name, start_time, end_time, exit_code, status, left(error_message, 400) AS error
              FROM prefect.reporting_logs
             WHERE lower(coalesce(status, '')) NOT IN ('success', 'succeeded', 'completed', 'ok')
               AND start_time > now() - make_interval(hours => %(h)s)
             ORDER BY start_time DESC""", h)
        return {"flow_runs": flows, "reports": reports}
    except Exception as e:
        return f"error: Prefect's database: {type(e).__name__}: {str(e)[:300]}"


# ------------------------------------------------------------------ the box (fixed snippets through Jupyter)

_JOBS = r'''
import subprocess, csv, io, json
r = subprocess.run(["schtasks", "/query", "/fo", "csv", "/v"], capture_output=True, text=True, timeout=180)
jobs = {}
for row in csv.DictReader(io.StringIO(r.stdout)):
    n = row.get("TaskName") or ""
    if n == "TaskName" or not n.lower().startswith(ARGS["folder"].lower()) or ARGS["like"].lower() not in n.lower():
        continue
    j = jobs.setdefault(n, {"name": n, "state": row.get("Scheduled Task State"), "status": row.get("Status"),
        "next_run": row.get("Next Run Time"), "last_run": row.get("Last Run Time"), "last_result": row.get("Last Result"),
        "run_as": row.get("Run As User"), "task_to_run": row.get("Task To Run"), "start_in": row.get("Start In"),
        "schedules": []})
    j["schedules"].append({k: row.get(k) for k in ("Schedule Type", "Start Time", "Days", "Repeat: Every") if row.get(k)})
print(json.dumps({"jobs": sorted(jobs.values(), key=lambda j: j["name"]), "rc": r.returncode}))
'''


@mcp.tool()
async def etl_jobs(name_like: str = "") -> dict:
    """The Task Scheduler jobs under the ETL folder (ETL_TASK_FOLDER), one row each: state (Enabled/Disabled), status,
    next and last run, last result (0 = success), the command it runs, its start-in dir and its schedule(s)."""
    return await box.run(_JOBS, {"folder": FOLDER, "like": name_like or ""}, timeout=200)


_BOX = r'''
import shutil, subprocess, json
out = {"disks": {}}
for d in ("C:\\", "D:\\"):
    try:
        u = shutil.disk_usage(d); out["disks"][d[0]] = {"free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1)}
    except Exception as e:
        out["disks"][d[0]] = str(e)
ps = lambda c: subprocess.run(["powershell", "-NoProfile", "-Command", c], capture_output=True, text=True, timeout=60).stdout
try:
    o = json.loads(ps("Get-CimInstance Win32_OperatingSystem | Select-Object FreePhysicalMemory,TotalVisibleMemorySize,"
                      "@{n='boot';e={$_.LastBootUpTime.ToString('s')}} | ConvertTo-Json"))
    out["memory_free_gb"] = round(int(o["FreePhysicalMemory"]) / 2**20, 1)
    out["memory_total_gb"] = round(int(o["TotalVisibleMemorySize"]) / 2**20, 1)
    out["booted"] = o["boot"]
except Exception as e:
    out["memory"] = f"unread: {e}"
try:
    p = json.loads(ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='prefect.exe'\" | "
                      "Select-Object ProcessId,CommandLine | ConvertTo-Json") or "[]")
    p = p if isinstance(p, list) else [p]
    w = [x for x in p if "worker" in (x.get("CommandLine") or "") and "prefect" in (x.get("CommandLine") or "").lower()]
    out["prefect_workers"] = [{"pid": x["ProcessId"], "cmd": (x.get("CommandLine") or "")[-160:]} for x in w]
except Exception as e:
    out["prefect_workers"] = f"unread: {e}"
if ARGS["root"]:
    g = lambda *a: subprocess.run([ARGS["git"], "-C", ARGS["root"]] + list(a), capture_output=True, text=True, timeout=60)
    st = g("status", "--porcelain", "--untracked-files=no").stdout.splitlines()
    out["repo"] = {"head": g("rev-parse", "HEAD").stdout.strip(), "branch": g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
                   "modified_tracked": len(st), "files": [l[3:] for l in st[:20]]}
print(json.dumps(out))
'''


@mcp.tool()
async def etl_box() -> dict:
    """The ETL box's health: free/total GB per drive, memory, boot time, the Prefect worker processes alive, and its ETL
    repo: HEAD, branch, and the tracked files modified on the box (a pull is fast-forward only: edits there block it)."""
    return await box.run(_BOX, {"git": GIT, "root": ROOT}, timeout=180)


_TAIL = r'''
import json, os
root = os.path.realpath(ARGS["root"]); p = os.path.realpath(os.path.join(root, ARGS["path"]))
if not root or not (p == root or p.startswith(root + os.sep)):
    print(json.dumps({"error": "the path is outside the ETL root"}))
elif not os.path.isfile(p):
    print(json.dumps({"error": "no such file"}))
else:
    with open(p, "rb") as f:
        f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 262144)); data = f.read().decode("utf-8", "replace")
    print(json.dumps({"path": p, "bytes": size, "lines": data.splitlines()[-ARGS["n"]:]}))
'''


@mcp.tool()
async def etl_log_tail(path: str, lines: int = 100) -> dict:
    """The last `lines` of a file on the box, under the ETL root (ETL_ROOT; a relative path is taken from it): a job's
    log, a run.bat's <REPORT>_log.txt, ETL_log.txt."""
    if not ROOT:
        return {"error": "ETL_ROOT is not configured"}
    return await box.run(_TAIL, {"root": ROOT, "path": path, "n": max(1, min(lines, 2000))})


# ------------------------------------------------------------------ acts (the etl seats)

_TASK = r'''
import subprocess, json
n, op = ARGS["name"], ARGS["op"]
if not n.lower().startswith(ARGS["folder"].lower()):
    print(json.dumps({"error": "the job is outside the ETL folder"}))
elif subprocess.run(["schtasks", "/query", "/tn", n], capture_output=True, text=True).returncode != 0:
    print(json.dumps({"error": "no such job"}))
else:
    argv = {"run": ["/run", "/tn", n], "stop": ["/end", "/tn", n], "enable": ["/change", "/tn", n, "/enable"],
            "disable": ["/change", "/tn", n, "/disable"]}[op]
    r = subprocess.run(["schtasks"] + argv, capture_output=True, text=True, timeout=60)
    print(json.dumps({"job": n, "op": op, "rc": r.returncode, "out": (r.stdout + r.stderr).strip()[-500:]}))
'''


async def _task(name: str, op: str) -> dict | str:
    return _refuse() or await box.run(_TASK, {"name": name or "", "op": op, "folder": FOLDER})


@mcp.tool()
async def etl_job_run(name: str) -> dict | str:
    """Start a Task Scheduler job now (its full name, e.g. '\\BI Jobs\\umair.fiaz\\merchant_active'). etl seats only."""
    return await _task(name, "run")


@mcp.tool()
async def etl_job_stop(name: str) -> dict | str:
    """Stop a running Task Scheduler job. etl seats only."""
    return await _task(name, "stop")


@mcp.tool()
async def etl_job_enable(name: str, on: bool) -> dict | str:
    """Enable (on=true) or disable (on=false) a Task Scheduler job. Retiring a job disables it for 7 days first
    (local.md). etl seats only."""
    return await _task(name, "enable" if on else "disable")


_PREFECT = r'''
import subprocess, json
r = subprocess.run([ARGS["exe"]] + ARGS["argv"], capture_output=True, text=True, timeout=120)
print(json.dumps({"rc": r.returncode, "out": (r.stdout + r.stderr).strip()[-1500:]}))
'''


@mcp.tool()
async def etl_flow_run(deployment: str) -> dict | str:
    """Start a Prefect deployment now ('flow/deployment', as etl_deployments names it). etl seats only."""
    no = _refuse()
    if no:
        return no
    known = etl_deployments(name_like=deployment, days=1)
    if isinstance(known, str):
        return known
    if deployment not in {d["deployment"] for d in known}:
        return f"error: no deployment named {deployment!r}"
    return await box.run(_PREFECT, {"exe": PREFECT, "argv": ["deployment", "run", deployment]}, timeout=150)


@mcp.tool()
async def etl_flow_cancel(flow_run_id: str) -> dict | str:
    """Cancel a running Prefect flow run (by its uuid). etl seats only."""
    no = _refuse()
    if no:
        return no
    if not UUID.match(flow_run_id or ""):
        return "error: flow_run_id is a uuid"
    return await box.run(_PREFECT, {"exe": PREFECT, "argv": ["flow-run", "cancel", flow_run_id]}, timeout=150)


_PULL = r'''
import subprocess, json
g = lambda *a: subprocess.run([ARGS["git"], "-C", ARGS["root"]] + list(a), capture_output=True, text=True, timeout=180)
before = g("rev-parse", "HEAD").stdout.strip()
r = g("pull", "--ff-only")
after = g("rev-parse", "HEAD").stdout.strip()
print(json.dumps({"before": before, "after": after, "rc": r.returncode, "out": (r.stdout + r.stderr).strip()[-1500:]}))
'''


@mcp.tool()
async def etl_box_pull() -> dict | str:
    """Deploy merged code: `git pull --ff-only` in the box's ETL repo (ETL_ROOT). Returns the head before and after.
    A deploy follows a second etl seat's PASS (local.md). etl seats only."""
    no = _refuse()
    if no:
        return no
    if not ROOT:
        return "error: ETL_ROOT is not configured"
    return await box.run(_PULL, {"git": GIT, "root": ROOT}, timeout=240)


if __name__ == "__main__":
    mcp.run()
