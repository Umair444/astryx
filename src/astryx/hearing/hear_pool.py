"""astryx · hear_pool — the dispatcher's side of hearing (plan-8674 S2, a4 #42048 D3 + D5).

One worker per agent that OPTS IN by having sensors/<agent>/hear.py (a1 F9: the file existing is the opt-in). Each
utterance goes to each worker over a pipe with a deadline. A worker that overruns or dies is killed and respawned,
and that is counted, so a catastrophic regex chosen by whoever is talking near the mic (a TV) stalls one agent's
ear for EAR_HEAR_MS, never the room. Edit hear.py and the next utterance runs the new code (respawn on mtime).

The worker is bwrap'd (src/astryx/hearing/hear_worker.py says what it can't reach). Without bwrap there is no sandbox to
promise, so the pool refuses to run hear() at all and says so in status: fail open for the room (utterances are
still stored), fail closed for the agents.

validate() is the dispatcher's check on a decision. A worker's answer is data from code that read text an
outsider chose, so nothing in it is trusted: the name must be this agent's own name and must actually occur in
the utterance, and the span is clamped to ≤ SPAN_MAX words starting AT the name.
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
import select
import shutil
import signal
import subprocess
import time
from pathlib import Path

REPO = repo_root(__file__)
WORKER = Path(__file__).resolve().parent / "hear_worker.py"
SPAN_MAX = 30
START_S = 5.0
BENCH_AFTER, BENCH_S = 3, 60.0        # 3 overruns in a row → skipped for a minute, counted, then tried again
_WORD = re.compile(r"[^\w-]+")


def hear_files(sensors: Path) -> dict[str, Path]:
    return {p.parent.name: p for p in sorted(sensors.glob("*/hear.py")) if ".example" not in p.parent.name}


def bwrap_argv(hear: Path, fd: int) -> list[str]:
    return ["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--ro-bind", str(WORKER), "/w/hear_worker.py", "--ro-bind", str(hear.parent), "/w/s",
            "--unshare-all", "--die-with-parent", "--new-session", "--chdir", "/w",
            "/usr/bin/python3", "-I", "/w/hear_worker.py", f"/w/s/{hear.name}", str(fd)]


def tokens(text: str) -> list[str]:
    return text.split()


def validate(agent: str, text: str, d) -> tuple[dict | None, str]:
    """(pointer fields | None, reason). Pointer fields: matched_name, span_start, span_end (word indexes)."""
    if not isinstance(d, dict) or "error" in d:
        return None, "error"
    if d.get("decision") != "pass":
        return None, "ignore"                     # S2 knows pass and ignore; gist is S3 and reads as ignore here
    name = d.get("matched_name")
    if not isinstance(name, str) or name.lower() != agent.lower():
        return None, "not its name"
    words = tokens(text)
    at = [i for i, w in enumerate(words) if _WORD.sub("", w).lower() == agent.lower()]
    if not at:
        return None, "name not in utterance"
    span = d.get("span")
    start = span[0] if isinstance(span, list) and len(span) == 2 and span[0] in at else at[0]
    end = start + SPAN_MAX
    if isinstance(span, list) and len(span) == 2 and isinstance(span[1], int) and span[1] > start:
        end = min(end, span[1])
    return {"matched_name": agent, "span_start": start, "span_end": min(end, len(words))}, "pass"


class Worker:
    def __init__(self, agent: str, hear: Path):
        self.agent, self.hear, self.p, self.r, self.mtime = agent, hear, None, None, 0.0
        self.n = {"pass": 0, "ignore": 0, "overrun": 0, "error": 0, "rejected": 0, "benched": 0}
        self.streak, self.bench_until = 0, 0.0

    def _start(self):
        r, w = os.pipe()
        self.mtime = self.hear.stat().st_mtime
        self.p = subprocess.Popen(bwrap_argv(self.hear, w), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, pass_fds=(w,), env={"PATH": "/usr/bin", "LANG": "C.UTF-8"},
                                  start_new_session=True)
        os.close(w)
        self.r = r
        if self._line(START_S) is None:                  # bwrap + python cold start, allowed once per spawn
            self.stop()
            raise OSError("worker never ready")

    def _line(self, within: float) -> dict | None:
        buf, until = b"", time.monotonic() + within
        while not buf.endswith(b"\n"):
            left = until - time.monotonic()
            if left <= 0 or not select.select([self.r], [], [], left)[0]:
                return None
            chunk = os.read(self.r, 65536)
            if not chunk:
                return {"error": "worker died"}
            buf += chunk
        try:
            return json.loads(buf)
        except ValueError:
            return {"error": "bad json"}

    def stop(self):
        if self.p:
            try:
                os.killpg(self.p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            self.p.wait()
            self.p = None
        if self.r is not None:
            os.close(self.r)
            self.r = None

    def ask(self, utt: dict, deadline_s: float) -> dict:
        try:
            if self.p is None or self.p.poll() is not None or self.hear.stat().st_mtime != self.mtime:
                self.stop()
                self._start()
            self.p.stdin.write((json.dumps(utt) + "\n").encode())
            self.p.stdin.flush()
        except (OSError, ValueError):
            self.stop()
            return {"error": "worker down"}
        d = self._line(deadline_s)
        if d is None or d.get("error") == "worker died":
            self.stop()                                  # can't kill a thread; can kill a process
            return {"error": "overrun" if d is None else "worker died"}
        return d


class Pool:
    def __init__(self, sensors: Path = paths.estate(__file__) / "sensors", deadline_ms: int = 200):
        self.sensors, self.deadline_s = sensors, deadline_ms / 1000
        self.workers: dict[str, Worker] = {}
        self.sandbox = shutil.which("bwrap") is not None

    def attending(self) -> list[str]:
        return sorted(hear_files(self.sensors)) if self.sandbox else []

    def hear(self, utt: dict) -> list[tuple[str, dict]]:
        """[(agent, pointer fields)] for every agent whose hear() passed and whose decision validated."""
        if not self.sandbox:
            return []
        files, out = hear_files(self.sensors), []
        for gone in set(self.workers) - set(files):
            self.workers.pop(gone).stop()
        for agent, path in files.items():
            w = self.workers.get(agent) or self.workers.setdefault(agent, Worker(agent, path))
            if time.monotonic() < w.bench_until:
                w.n["benched"] += 1
                continue
            d = w.ask(utt, self.deadline_s)
            w.streak = w.streak + 1 if d.get("error") == "overrun" else 0
            if w.streak >= BENCH_AFTER:
                w.streak, w.bench_until = 0, time.monotonic() + BENCH_S
            ptr, why = validate(agent, utt["text"], d)
            if ptr:
                w.n["pass"] += 1
                out.append((agent, ptr))
            elif why == "error":
                w.n["overrun" if d.get("error") == "overrun" else "error"] += 1
            else:
                w.n["ignore" if why == "ignore" else "rejected"] += 1
        return out

    def counts(self) -> dict:
        now = time.monotonic()
        return {a: {**w.n, "benched_now": now < w.bench_until} for a, w in self.workers.items()}

    def close(self):
        for w in self.workers.values():
            w.stop()
