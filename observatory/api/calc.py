"""astryx observatory · the chat's calculator (owner 11-15: "press = in chat and Qalculate it … 10 usd to pkr …
only the answer goes to the agent").

    POST /api/chat/calc   {expr}  ->  {result}  |  {error}

One evaluation by Qalculate's CLI (qalc, the Ubuntu package), in qsand.sh's sandbox: a user + mount + network
namespace, CHROOTED into an empty tmpfs holding only qalc, its libraries and data (read-only) and the rates: no host
file to read, no program to run, no network, 5 s. Before it: an expression of at most
EXPR_MAX characters, never a control character, never one of Qalculate's system functions (FORBIDDEN: export and save
write files, load reads one, command runs one), always passed after a space so it can't be read as a qalc option.
Exchange rates: qalc -e refreshes them into this user's Qalculate data dir (the one fetch, fixed arguments, outside
the sandbox) when they are older than RATES_MAX_AGE, in the background; an evaluation copies that dir in.
Reached by the org's humans (main.MEMBER), RATE per minute per viewer.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter()

QALC = "/usr/bin/qalc"
SANDBOX = Path(__file__).resolve().parent / "qsand.sh"
RATES = Path.home() / ".local" / "share" / "qalculate"
RATES_FILE = RATES / "eurofxref-daily.xml"
RATES_MAX_AGE = 6 * 3600
EXPR_MAX = 300
OUT_MAX = 200
TIMEOUT = 5
RATE = 30                                          # evaluations a minute, per viewer
# the system functions BY NAME, called with or without parentheses (qalc reads `load "x"` as a call: medic 12192). The
# chroot jail (qsand.sh) is the layer that holds; this one keeps the attempt from running at all
FORBIDDEN = re.compile(r"\b(export|save|load|command)\b", re.I)
_me = lambda request: "owner"                      # noqa: E731 — main.wire_handle
_seen: dict[str, list[float]] = {}
_refreshing = False


def bind(me=None) -> None:
    global _me
    if me is not None:
        _me = me


class Calc(BaseModel):
    expr: str = Field(max_length=EXPR_MAX)


def judge(expr: str) -> str:
    """'' when the expression may be evaluated, else the reason."""
    e = expr.strip()
    if not e:
        return "nothing to calculate"
    if len(e) > EXPR_MAX:
        return f"at most {EXPR_MAX} characters"
    if re.search(r"[\x00-\x1f\x7f]", e):
        return "one line, no control characters"
    if FORBIDDEN.search(e):
        return "that function isn't available here"
    return ""


def tidy(out: str) -> str:
    """qalc's answer as a line an agent reads: the first line, a plain minus sign, capped."""
    line = (out or "").strip().splitlines()[0].strip() if (out or "").strip() else ""
    return line.replace("−", "-")[:OUT_MAX]


def evaluate(expr: str) -> str:
    """The sandboxed evaluation (blocking). Raises on a failure."""
    r = subprocess.run(["timeout", str(TIMEOUT), "unshare", "-rnm", "--propagation", "private", str(SANDBOX),
                        str(RATES), " " + expr.strip()], capture_output=True, text=True, timeout=TIMEOUT + 2)
    out = tidy(r.stdout)
    if r.returncode != 0 or not out:
        raise RuntimeError("Qalculate gave no answer")
    return out


def _refresh_rates() -> None:
    global _refreshing
    try:
        subprocess.run([QALC, "-e", "-t", "1"], capture_output=True, timeout=60, cwd="/tmp")
    except Exception:
        pass
    finally:
        _refreshing = False


def rates_stale() -> bool:
    try:
        return time.time() - RATES_FILE.stat().st_mtime > RATES_MAX_AGE
    except OSError:
        return True


@router.post("/api/chat/calc")
async def calc(body: Calc, request: Request):
    global _refreshing
    who = _me(request) or "?"
    now = time.time()
    seen = [t for t in _seen.get(who, []) if now - t < 60]
    if len(seen) >= RATE:
        return JSONResponse({"error": "too many calculations this minute"}, status_code=429)
    _seen[who] = seen + [now]
    why = judge(body.expr)
    if why:
        return JSONResponse({"error": why}, status_code=400)
    if rates_stale() and not _refreshing:
        _refreshing = True
        asyncio.get_running_loop().run_in_executor(None, _refresh_rates)
    try:
        return {"result": await asyncio.to_thread(evaluate, body.expr)}
    except Exception:
        return JSONResponse({"error": "Qalculate couldn't evaluate that"}, status_code=422)
