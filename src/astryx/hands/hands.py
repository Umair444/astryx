#!/usr/bin/env python3
"""astryx · hands — the browser-lease executor (plan-7862 "Hands", S1: the cell).

    venv/bin/python src/astryx/hands/hands.py create --agent A --allow host1,host2 --steps N --wall SECONDS
    venv/bin/python src/astryx/hands/hands.py step <lease> '<action json>'     # e.g. {"verb":"goto","url":…}
    venv/bin/python src/astryx/hands/hands.py kill <lease>
    venv/bin/python src/astryx/hands/hands.py sweep                              # kill expired leases + orphans
    venv/bin/python src/astryx/hands/hands.py status <lease>

A LEASE is one browser, used for a bounded task:
  - its OWN internal docker network (no route out);
  - its OWN default-deny proxy, the only bridge to the internet. Its allow-list is GENERATED from
    the lease row (the one writer is this file) and dies with the lease;
  - its OWN cell (astryx-hands-cell): Xvfb + chromium + playwright-core, with the profile on TMPFS.
    It has no host mount, no docker socket and no secrets, and runs read-only, cap-drop ALL,
    no-new-privileges.
A lease dies at its STEP cap or its WALL-TIME cap, whichever comes first, enforced HERE, by the
executor (seed #38260). The step count is checked under a row lock on every action. The deadline
is enforced three ways: every action checks it first, an action's exec timeout never outlives it,
and a detached REAPER kills the lease at the deadline even if nobody calls again. KILL = stop and
wipe: the cell is removed, so its tmpfs profile is gone; the proxy, the network and the
generated filter go too.

NO MODEL-API PINHOLE (a4 #38063 §1): a lease that allows a model-API host is refused. The driver
model runs OUTSIDE the cell (S1.5); the cell never needs to reach one.

THREAT MODEL (owner ruling, seed #38554): Hands stops EXTERNAL adversaries, meaning page or app
content steering the driver, and outside parties. Residents are TRUSTED by that ruling, and are not
a threat this design defends against. (Stated as fact, not as a threat: every resident is in the
docker group, so it can reach any cell.)
GRADE against the external adversary: egress is PREVENTION up to the kernel boundary (a
shared-kernel container). A kernel or browser exploit is beyond it; a VM backend is the stronger
cell (the windows-vm backend, and a1's trip).
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = repo_root(__file__)
CELL_IMG = "astryx-hands-cell"
PROXY_IMG = "astryx-hands-proxy"
EGRESS_NET = "astryx-hands-egress"          # the proxies' shared OUTBOUND leg (cells never join it)
STATE_DIR = Path(os.environ.get("HANDS_STATE_DIR") or tempfile.gettempdir()) / "astryx-hands"
# NAMESPACE: lease ids are per DATABASE, so they repeat across DBs (an oracle's fixture starts at 1).
# Every container, network and label is scoped by it, and sweep() only ever acts on its OWN
# namespace. Without that, an oracle run against a fixture DB would read the org's real leases as
# "orphans" (not live in ITS table) and kill them. 'org' is the real executor; an oracle sets its
# own, unique per run.
NS = re.sub(r"[^a-z0-9]", "", (os.environ.get("HANDS_NS") or "org").lower())[:24] or "org"
STEP_TIMEOUT_MAX = 90                      # one action's ceiling, further capped by the deadline
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
# Model-API providers. A lease may NEVER allow these (exact host or any subdomain): the driver
# model is outside the cell, so a reachable API from inside could only serve exfiltration.
MODEL_API_DOMAINS = ("anthropic.com", "claude.ai", "openai.com", "googleapis.com",
                     "generativelanguage.googleapis.com", "mistral.ai", "cohere.ai", "cohere.com",
                     "groq.com", "together.xyz", "deepseek.com", "x.ai", "openrouter.ai")


class Refused(Exception):
    pass


def dsn() -> str:
    """HANDS_DSN for an oracle's throwaway DB (set EXPLICITLY by the test), else the org's DSN."""
    if os.environ.get("HANDS_DSN"):
        return os.environ["HANDS_DSN"]
    try:
        return config.dsn(paths.estate(__file__) / ".env", env_first=False).strip('"').strip("'")
    except LookupError:
        raise SystemExit("no ASTRYX_DSN")


def _db():
    import psycopg
    return psycopg.connect(dsn(), autocommit=True, connect_timeout=5)


def _docker(*args, check=True, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout,
                          check=check)


def names(lease: int) -> dict:
    base = f"hands-{NS}-{lease}"
    return {"net": f"{base}-net", "proxy": f"{base}-proxy", "cell": f"{base}-cell",
            "dir": STATE_DIR / NS / str(lease)}


def _labels(lease: int) -> list[str]:
    return ["--label", f"astryx.hands.ns={NS}", "--label", f"astryx.hands.lease={lease}"]


def validate_allow(hosts: list[str]) -> list[str]:
    out = []
    for h in hosts:
        h = h.strip().lower().rstrip(".")
        if not HOST_RE.match(h):
            raise Refused(f"not a plain hostname: {h!r} (no schemes, ports, paths or wildcards)")
        if any(h == d or h.endswith("." + d) for d in MODEL_API_DOMAINS):
            raise Refused(f"{h} is a model-API host: a Hands cell has NO model-API pinhole")
        if h not in out:
            out.append(h)
    if not out:
        raise Refused("a lease must allow at least one host")
    return out


def filter_text(allow: list[str]) -> str:
    """tinyproxy extended-regex filter: one anchored, dot-escaped line per allowed host."""
    return "".join(f"^{re.escape(h)}$\n" for h in allow)


def create(agent: str, allow: list[str], step_cap: int, wall_cap_s: int, *,
           reaper: bool = True) -> int:
    """`reaper=False` exists for the oracle ONLY: it isolates the per-step deadline check, which
    the reaper would otherwise satisfy in its place (a fallback laundering the primary path)."""
    allow = validate_allow(allow)
    with _db() as c:
        lease = c.execute(
            "INSERT INTO hands_leases (agent, allow, step_cap, wall_cap_s, deadline) "
            "VALUES (%s, %s, %s, %s, now() + make_interval(secs => %s)) RETURNING id",
            (agent, allow, step_cap, wall_cap_s, wall_cap_s)).fetchone()[0]
    n = names(lease)
    try:
        n["dir"].mkdir(parents=True, mode=0o700)
        n["dir"].parent.chmod(0o700)
        (n["dir"] / "filter").write_text(filter_text(allow))
        (n["dir"] / "filter").chmod(0o644)               # tinyproxy reads it as its own user
        if _docker("network", "inspect", EGRESS_NET, check=False).returncode != 0:
            _docker("network", "create", EGRESS_NET)
        _docker("network", "create", "--internal", *_labels(lease), n["net"])
        _docker("run", "-d", "--name", n["proxy"], "--network", n["net"],
                *_labels(lease), "--read-only", "--tmpfs", "/run",
                "--tmpfs", "/var/log/tinyproxy", "--memory", "128m", "--pids-limit", "64",
                "-v", f"{n['dir'] / 'filter'}:/etc/tinyproxy/filter:ro", PROXY_IMG)
        _docker("network", "connect", EGRESS_NET, n["proxy"])
        _docker("run", "-d", "--name", n["cell"], "--network", n["net"],
                *_labels(lease),
                "--read-only", "--tmpfs", "/profile:rw,size=512m,uid=10001,mode=0700",
                "--tmpfs", "/tmp:rw,size=256m,mode=1777", "--tmpfs", "/home/hands:rw,size=64m,uid=10001",
                "--shm-size", "256m", "--memory", "1536m", "--pids-limit", "512",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "-e", f"HANDS_PROXY=http://{n['proxy']}:8888", CELL_IMG)
    except Exception as e:  # noqa: BLE001 — a half-built lease is torn down, never left running
        kill(lease, "error")
        raise Refused(f"lease {lease} could not be built: {type(e).__name__}: "
                      f"{getattr(e, 'stderr', '') or e}"[:400])
    # The wall cap fires even if nobody calls again.
    if not reaper:
        return lease
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "reap", str(lease)],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env={**os.environ})
    return lease


def kill(lease: int, reason: str = "killed") -> bool:
    """Stop AND wipe. Idempotent; True if this call ended a live lease. Teardown runs whatever
    the row says, so a lease whose row was lost still can't keep a browser alive."""
    n = names(lease)
    for c in (n["cell"], n["proxy"]):
        _docker("rm", "-f", c, check=False)
    _docker("network", "rm", n["net"], check=False)
    shutil.rmtree(n["dir"], ignore_errors=True)
    with _db() as c:
        row = c.execute("UPDATE hands_leases SET state='dead', ended_at=now(), end_reason=%s "
                        "WHERE id=%s AND state='live' RETURNING id", (reason, lease)).fetchone()
    return row is not None


def step(lease: int, action: dict) -> dict:
    """One driver action. The caps are checked and the step is counted in ONE atomic UPDATE whose
    WHERE carries every condition (live, under the step cap, before the deadline). Two concurrent
    callers can't both take the last step, and a refused step is never counted. Only on a refusal
    does a second read say WHY, so the right end_reason is recorded."""
    with _db() as c:
        row = c.execute(
            "UPDATE hands_leases SET steps_used = steps_used + 1 "
            "WHERE id=%s AND state='live' AND steps_used < step_cap AND deadline > now() "
            "RETURNING steps_used, step_cap, extract(epoch FROM deadline - now())",
            (lease,)).fetchone()
        if row is None:
            why = c.execute("SELECT state, extract(epoch FROM deadline - now()) FROM hands_leases "
                            "WHERE id=%s", (lease,)).fetchone()
    if row is None:
        if not why:
            raise Refused(f"no lease {lease}")
        if why[0] != "live":
            raise Refused(f"lease {lease} is dead")
        if float(why[1]) <= 0:
            kill(lease, "wall_cap")
            raise Refused(f"lease {lease} hit its wall cap; killed")
        # The STEP cap is reached, but the step that reached it may still be RUNNING, and it kills
        # the lease itself when it finishes (dies AT the cap). Killing here would abort that
        # legitimate last action mid-flight (a race the oracle caught, H9b). If that step never
        # finishes, the wall cap still ends the lease.
        raise Refused(f"lease {lease} has used its step cap")
    used, cap, left = row[0], row[1], float(row[2])
    timeout = max(1.0, min(STEP_TIMEOUT_MAX, left))
    try:
        r = _docker("exec", names(lease)["cell"], "node", "/hands/drive.mjs", json.dumps(action),
                    check=False, timeout=timeout)
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):           # no or partial output (a killed cell, a crash)
            out = {"ok": False, "error": (r.stderr or r.stdout or "no output")[-300:]}
    except subprocess.TimeoutExpired:
        kill(lease, "wall_cap" if timeout >= left else "error")
        raise Refused(f"lease {lease}: the action outlived its time; killed")
    if used >= cap:                                   # the lease dies AT its step cap
        kill(lease, "step_cap")
        out["lease"] = "ended: step cap reached"
    return out


def reap(lease: int) -> None:
    """Detached at create: sleep to the deadline, then kill if the lease is still live."""
    while True:
        with _db() as c:
            row = c.execute("SELECT state, extract(epoch FROM deadline - now()) FROM hands_leases "
                            "WHERE id=%s", (lease,)).fetchone()
        if not row or row[0] != "live":
            return
        left = float(row[1])
        if left <= 0:
            kill(lease, "wall_cap")
            return
        time.sleep(min(left, 30))


def sweep() -> list[str]:
    """Kill expired leases, and any hands container or network of THIS namespace whose lease isn't
    live (orphans). Another namespace's resources are never touched: its ids mean another table."""
    done = []
    with _db() as c:
        expired = [r[0] for r in c.execute("SELECT id FROM hands_leases WHERE state='live' "
                                           "AND deadline <= now()").fetchall()]
        live = {r[0] for r in c.execute("SELECT id FROM hands_leases WHERE state='live'").fetchall()}
    for lease in expired:
        kill(lease, "wall_cap")
        done.append(f"expired {lease}")
    labelled = set()
    for kind in (["ps", "-a"], ["network", "ls"]):
        r = _docker(*kind, "--filter", f"label=astryx.hands.ns={NS}",
                    "--filter", "label=astryx.hands.lease",
                    "--format", '{{.Label "astryx.hands.lease"}}', check=False)
        labelled |= {int(x) for x in r.stdout.split() if x.isdigit()}
    for lease in sorted(labelled - live):
        kill(lease, "error")
        done.append(f"orphan {lease}")
    return done


def status(lease: int) -> dict:
    with _db() as c:
        row = c.execute("SELECT state, steps_used, step_cap, wall_cap_s, deadline, end_reason, "
                        "allow FROM hands_leases WHERE id=%s", (lease,)).fetchone()
    if not row:
        return {"lease": lease, "exists": False}
    keys = ("state", "steps_used", "step_cap", "wall_cap_s", "deadline", "end_reason", "allow")
    return {"lease": lease, **{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                                for k, v in zip(keys, row)}}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip().splitlines()[0])
        return 2
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "create":
            import argparse
            p = argparse.ArgumentParser(prog="hands.py create")
            p.add_argument("--agent", required=True)
            p.add_argument("--allow", required=True)
            p.add_argument("--steps", type=int, required=True)
            p.add_argument("--wall", type=int, required=True)
            a = p.parse_args(rest)
            print(create(a.agent, a.allow.split(","), a.steps, a.wall))
        elif cmd == "step":
            print(json.dumps(step(int(rest[0]), json.loads(rest[1]))))
        elif cmd == "kill":
            print("killed" if kill(int(rest[0])) else "already dead")
        elif cmd == "reap":
            reap(int(rest[0]))
        elif cmd == "sweep":
            print("\n".join(sweep()) or "nothing to sweep")
        elif cmd == "status":
            print(json.dumps(status(int(rest[0]))))
        else:
            print(f"unknown command {cmd}")
            return 2
    except Refused as e:
        print(f"refused: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
