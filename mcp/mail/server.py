#!/usr/bin/env python3
"""astryx · mail MCP server — the org's mailbox as a scoped capability, on any mail server.

SMTP to send, IMAP to read, both configured by the MAIL_* keys in the org's .env (src/astryx/mail.py says which:
an office relay with no login, Gmail with an app password, any host between). Granted per charter with
`Grants: mail` (`gmail` is read as the same grant). Mail is personal tier, so holders quote content meta-only in
anything org-visible unless the owner's law says otherwise, and sending is a real outward act: sign as the agent,
never as the owner, unless the charter explicitly says otherwise.
"""
from __future__ import annotations

import email
import email.header
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))   # astryx.paths: the org's estate (its HOME in a cog of several orgs), plan-11324 S3a
from astryx import config, mail, paths  # noqa: E402


def env() -> dict:
    """The org's .env, read at use, not import (the ONE .env reader, plan-10224 ENVREAD)."""
    return config.read_env(paths.estate(__file__) / ".env")


mcp = FastMCP("astryx-mail")


def dec(v) -> str:
    if not v:
        return ""
    return "".join(p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes)
                   else p for p, c in email.header.decode_header(v))


def body_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace")
        return "(no text part)"
    return msg.get_payload(decode=True).decode(
        msg.get_content_charset() or "utf-8", errors="replace")


def fetch_headers(m, ids: list[bytes]) -> list[dict]:
    out = []
    for i in ids:
        _, data = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] FLAGS)")
        raw = next((d[1] for d in data if isinstance(d, tuple)), b"")
        msg = email.message_from_bytes(raw)
        try:
            ts = parsedate_to_datetime(msg["Date"]).isoformat()
        except Exception:
            ts = msg["Date"] or ""
        flags = b" ".join(d for d in data if isinstance(d, bytes))
        out.append({"id": i.decode(), "from": dec(msg["From"]), "subject": dec(msg["Subject"]),
                    "date": ts, "unread": b"\\Seen" not in flags})
    return out


@mcp.tool()
def mail_search(query: str, limit: int = 10) -> list[dict]:
    """Search the inbox. On Gmail, Gmail's own syntax (from:, subject:, newer_than:2d, is:unread, has:attachment);
    on any other server, IMAP criteria (FROM "x" SINCE 1-Nov-2026 UNSEEN) or a plain word to find in the text.
    Returns newest first: id, from, subject, date, unread. Use mail_read(id) for a body."""
    m = mail.imap(env())
    try:
        m.select("INBOX", readonly=True)
        ids = mail.search(m, query)[-min(limit, 50):]
        return list(reversed(fetch_headers(m, ids)))
    finally:
        m.logout()


@mcp.tool()
def mail_recent(limit: int = 10) -> list[dict]:
    """The newest inbox messages: id, from, subject, date, unread."""
    m = mail.imap(env())
    try:
        m.select("INBOX", readonly=True)
        _, data = m.search(None, "ALL")
        ids = data[0].split()[-min(limit, 50):]
        return list(reversed(fetch_headers(m, ids)))
    finally:
        m.logout()


@mcp.tool()
def mail_read(id: str) -> dict:
    """One full message by id (from mail_search/mail_recent): headers + plain body."""
    m = mail.imap(env())
    try:
        m.select("INBOX", readonly=True)
        _, data = m.fetch(id.encode(), "(BODY.PEEK[])")
        raw = next((d[1] for d in data if isinstance(d, tuple)), b"")
        msg = email.message_from_bytes(raw)
        return {"id": id, "from": dec(msg["From"]), "to": dec(msg["To"]),
                "subject": dec(msg["Subject"]), "date": msg["Date"],
                "body": body_text(msg)[:8000]}
    finally:
        m.logout()


@mcp.tool()
def mail_send(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    """Send a plain-text email from the org's address. OUTWARD ACT: unless your charter says otherwise, sign the body
    as yourself (the agent), never as the owner. Args: to (comma-separated ok), subject, body, optional cc and bcc."""
    e = env()
    mail.send(e, to, subject, body, cc=cc, bcc=bcc)
    return {"sent": True, "from": e["MAIL_FROM"], "to": to, "subject": subject}


if __name__ == "__main__":
    mcp.run()
