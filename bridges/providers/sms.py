"""SMS provider — the org's SMS gateway queue behind the channel protocol.

The gateway sends whatever lands in its outbound queue table (a row with status 'N'; it flips the row to 'Y' once the
message left, within a second or two). So a send is ONE parameterized INSERT into that table, then a short wait for the
flip: the row's id and its status are the receipt.

The queue's database is reached from the ETL host, whose own connection layer already holds it (our side's driver
cannot log in to it): the insert runs as a fixed snippet on that host's Jupyter kernel, with the number and the text
passed as data, never spliced into SQL. Configured by the org's .env:
  SMS_JUPYTER    host:port of the ETL host's Jupyter
  SMS_ETL_DIR    the ETL checkout there (its OPERATIONS package opens the database)
  SMS_DB         the ETL's connection alias for the gateway's database
  SMS_SHORTCODE  the sender code the gateway sends from
  SMS_IPADDRESS  the source address the gateway records
  SMS_TABLE      the gateway's outbound queue table (schema.table)

SMS has no address book and no chat list, so the reads raise NotSupported and a cross-channel search skips SMS.
"""
from __future__ import annotations

import json
import re
import uuid

import httpx
import websockets

from ..common import env
from .base import ChannelProvider, Chat, Contact, NotSupported, Poll, SendResult

MAX_BYTES = 4000                      # the queue's MESSAGE column: VARCHAR2(4000), in bytes
TABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*")

# Runs on the ETL host. P is the only input, a JSON literal; the SQL carries bind variables only (the table name, which
# cannot be bound, is the org's own config and is checked to be a plain schema.table before it goes).
REMOTE = r'''
import os, sys, json, time
P = json.loads(%s)
if P["dir"] not in sys.path:
    os.chdir(P["dir"]); sys.path.insert(0, P["dir"])
from OPERATIONS.CONNECTION.connection import establish_connection_db
con = establish_connection_db(P["db"])
cur = con.cursor()
rid = cur.var(int)
cur.execute("INSERT INTO " + P["table"] + " (mobilenum, shortcode, message, timein, status, ipaddress, type) "
            "VALUES (:n, :s, :m, SYSDATE, 'N', :ip, 'R') RETURNING id INTO :rid",
            n=P["to"], s=P["shortcode"], m=P["text"], ip=P["ip"], rid=rid)
con.commit()
rid = rid.getvalue()[0]
status = "N"
for _ in range(P["wait"] * 2):
    time.sleep(0.5)
    cur.execute("SELECT status FROM " + P["table"] + " WHERE id = :i", i=rid)
    status = cur.fetchone()[0]
    if status != "N":
        break
cur.close()
print("SMSRESULT " + json.dumps({"id": rid, "status": status}))
'''


def number(dest: str) -> str | None:
    """A Pakistani mobile number as the gateway takes it (92 + ten digits), from 03…, 3…, 92… or +92…; else None."""
    d = re.sub(r"[\s+-]", "", str(dest or ""))
    m = re.fullmatch(r"(?:92|0)?(3\d{9})", d)
    return f"92{m.group(1)}" if m else None


class SmsProvider(ChannelProvider):
    NAME = "sms"
    WAIT = 15                         # seconds to wait for the gateway's flip before calling a message queued

    def __init__(self) -> None:
        self.host = env("SMS_JUPYTER")
        self.conf = {"dir": env("SMS_ETL_DIR"), "db": env("SMS_DB"), "shortcode": env("SMS_SHORTCODE"),
                     "ip": env("SMS_IPADDRESS"), "table": env("SMS_TABLE")}
        self._kernel: str | None = None

    # ---- reads: SMS has no directory -------------------------------------------
    async def search_contacts(self, query: str) -> list[Contact]:
        raise NotSupported("sms has no contact directory")

    async def resolve(self, handle: str) -> Contact | None:
        raise NotSupported("sms has no contact directory")

    async def list_chats(self) -> list[Chat]:
        raise NotSupported("sms has no chat list")

    # ---- the ETL host's kernel -------------------------------------------------
    async def _run(self, code: str) -> str:
        """Run `code` on the ETL host's kernel (one kept per process, so the database connection is reused);
        returns its stdout. A kernel that is gone is replaced once."""
        async with httpx.AsyncClient(base_url=f"http://{self.host}", timeout=20, follow_redirects=True) as http:
            await http.get("/")
            xsrf = http.cookies.get("_xsrf")
            hdr = {"X-XSRFToken": xsrf} if xsrf else {}
            if self._kernel and (await http.get(f"/api/kernels/{self._kernel}", headers=hdr)).status_code != 200:
                self._kernel = None
            if not self._kernel:
                r = await http.post("/api/kernels", json={"name": "python3"}, headers=hdr)
                r.raise_for_status()
                self._kernel = r.json()["id"]
            cookie = "; ".join(f"{k}={v}" for k, v in http.cookies.items())
        mid = uuid.uuid4().hex
        out, err = [], []
        async with websockets.connect(f"ws://{self.host}/api/kernels/{self._kernel}/channels",
                                      additional_headers={"Cookie": cookie} if cookie else None,
                                      open_timeout=20) as ws:
            await ws.send(json.dumps({
                "header": {"msg_id": mid, "username": "astryx-sms", "session": uuid.uuid4().hex,
                           "msg_type": "execute_request", "version": "5.3"},
                "parent_header": {}, "metadata": {}, "channel": "shell",
                "content": {"code": code, "silent": False, "store_history": False, "user_expressions": {},
                            "allow_stdin": False, "stop_on_error": True}}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("parent_header", {}).get("msg_id") != mid:
                    continue
                kind, c = msg["msg_type"], msg["content"]
                if kind == "stream":
                    out.append(c.get("text", ""))
                elif kind == "error":
                    err.append(f"{c.get('ename')}: {c.get('evalue')}")
                elif kind == "status" and c.get("execution_state") == "idle":
                    break
        if err:
            raise RuntimeError("; ".join(err)[:300])
        return "".join(out)

    # ---- write -----------------------------------------------------------------
    async def send(self, dest: str, text: str | None = None, *,
                   files: tuple[str, ...] = (),
                   poll: Poll | None = None) -> SendResult:
        to = number(dest)
        handle = f"{self.NAME}:{to or dest}"
        if not to:
            return SendResult(self.NAME, False, handle, error="not a mobile number (92 + ten digits)")
        if not (text or "").strip():
            return SendResult(self.NAME, False, handle, error="no text: an SMS carries text only")
        if len(text.encode()) > MAX_BYTES:
            return SendResult(self.NAME, False, handle, error=f"text is {len(text.encode())} bytes; the gateway takes "
                                                              f"{MAX_BYTES}")
        if not (self.host and all(self.conf.values()) and TABLE.fullmatch(self.conf["table"])):
            return SendResult(self.NAME, False, handle, error="SMS is not configured (SMS_* in .env)")
        try:
            got = await self._run(REMOTE % repr(json.dumps({**self.conf, "to": to, "text": text, "wait": self.WAIT})))
            res = json.loads(got.rsplit("SMSRESULT ", 1)[1].strip())
        except Exception as e:  # noqa: BLE001 — a send reports its failure, never raises
            return SendResult(self.NAME, False, handle, rendered=text, error=f"{type(e).__name__}: {e}"[:300])
        # a row the gateway has not flipped yet is still in its queue and still goes out: reporting it as failed would
        # invite a resend, a second SMS. Only a status other than N or Y is the gateway refusing it.
        ok = res["status"] in ("Y", "N")
        return SendResult(self.NAME, ok, handle, message_id=str(res["id"]), rendered=text,
                          error=None if ok else f"the gateway marked row {res['id']} '{res['status']}'")
