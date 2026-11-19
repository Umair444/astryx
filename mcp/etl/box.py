"""astryx · etl box door — run one fixed snippet on the ETL host's Jupyter kernel and get its stdout.

The ETL host (a Windows box) is reached through its Jupyter server (ETL_JUPYTER, host:port, default the SMS bridge's
SMS_JUPYTER: the same box). One kernel per server process, kept and reused; a kernel that is gone is replaced. Every
snippet the etl server sends is a constant of the server's own; the caller's arguments travel as one JSON value the
snippet decodes, never pasted into code. WinRM will replace this door when IT enables it: the tools above stay.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import websockets

_kernel: str | None = None
_lock = asyncio.Lock()


def host() -> str:
    return os.environ.get("ETL_JUPYTER") or os.environ.get("SMS_JUPYTER") or ""


async def _drop(h: str) -> None:
    """Forget the kernel and shut it down (best effort), as bridges/providers/sms.py does: a stalled snippet (a hung
    schtasks, git or prefect) must not keep running on the box in a kernel nothing will reuse (medic 14956)."""
    global _kernel
    kid, _kernel = _kernel, None
    if not kid:
        return
    try:
        async with httpx.AsyncClient(base_url=f"http://{h}", timeout=10, follow_redirects=True) as http:
            await http.get("/")
            x = http.cookies.get("_xsrf")
            await http.delete(f"/api/kernels/{kid}", headers={"X-XSRFToken": x} if x else {})
    except Exception:
        pass


async def run(snippet: str, args: dict, timeout: float = 120) -> dict:
    """Run `snippet` with ARGS bound to `args`; the snippet prints ONE json line (its result). Returns that value, or
    {"error": …}. Serialised: one kernel, one request at a time."""
    global _kernel
    h = host()
    if not h:
        return {"error": "no ETL box configured (ETL_JUPYTER or SMS_JUPYTER in .env)"}
    code = f"import json as _j\nARGS = _j.loads({json.dumps(json.dumps(args))})\n{snippet}"
    async with _lock:
        try:
            async with httpx.AsyncClient(base_url=f"http://{h}", timeout=20, follow_redirects=True) as http:
                await http.get("/")
                xsrf = http.cookies.get("_xsrf")
                hdr = {"X-XSRFToken": xsrf} if xsrf else {}
                if _kernel and (await http.get(f"/api/kernels/{_kernel}", headers=hdr)).status_code != 200:
                    _kernel = None
                if not _kernel:
                    r = await http.post("/api/kernels", json={"name": "python3"}, headers=hdr)
                    r.raise_for_status()
                    _kernel = r.json()["id"]
                cookie = "; ".join(f"{k}={v}" for k, v in http.cookies.items())
            mid, out, err = uuid.uuid4().hex, [], []
            async with websockets.connect(f"ws://{h}/api/kernels/{_kernel}/channels",
                                          additional_headers={"Cookie": cookie} if cookie else None,
                                          open_timeout=20, max_size=None) as ws:
                await ws.send(json.dumps({
                    "header": {"msg_id": mid, "username": "astryx-etl", "session": uuid.uuid4().hex,
                               "msg_type": "execute_request", "version": "5.3"},
                    "parent_header": {}, "metadata": {}, "channel": "shell",
                    "content": {"code": code, "silent": False, "store_history": False, "user_expressions": {},
                                "allow_stdin": False, "stop_on_error": True}}))
                async def drain():
                    while True:
                        m = json.loads(await ws.recv())
                        if m.get("parent_header", {}).get("msg_id") != mid:
                            continue
                        kind, c = m["msg_type"], m["content"]
                        if kind == "stream":
                            out.append(c.get("text", ""))
                        elif kind == "error":
                            err.append(f"{c.get('ename')}: {c.get('evalue')}")
                        elif kind == "status" and c.get("execution_state") == "idle":
                            return
                await asyncio.wait_for(drain(), timeout)
        except asyncio.TimeoutError:
            await _drop(h)          # a stalled kernel is shut down, never reused and queued behind
            return {"error": f"the box did not answer within {timeout:.0f}s"}
        except Exception as e:      # the box dark, Jupyter down: one plain line
            await _drop(h)
            return {"error": f"the ETL box is unreachable: {type(e).__name__}: {str(e)[:200]}"}
    if err:
        return {"error": "; ".join(err)[:500]}
    lines = [l for l in "".join(out).splitlines() if l.strip()]
    try:
        return json.loads(lines[-1]) if lines else {"error": "the snippet printed nothing"}
    except ValueError:
        return {"error": "the snippet's last line was not json", "tail": lines[-3:]}
