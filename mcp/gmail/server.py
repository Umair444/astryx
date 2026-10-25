#!/usr/bin/env python3
"""astryx · gmail MCP server — the owner's mailbox as a scoped capability.

IMAP + SMTP over a Gmail app password (GMAIL_ADDRESS / GMAIL_APP_PASSWORD in
the org's .env). Granted per charter with `Grants: gmail`; mail is personal
tier, so holders quote content meta-only in anything org-visible unless the
owner's law says otherwise, and sending is a real outward act: sign as the
agent, never as the owner, unless the charter explicitly says otherwise.

mail_search takes Gmail's own search syntax (from:, subject:, newer_than:2d,
has:attachment, label:) via IMAP X-GM-RAW, so agents search exactly like the
owner does in the Gmail search bar.
"""
from __future__ import annotations

import email
import email.header
import imaplib
import smtplib
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))   # astryx.paths: the org's estate (its HOME in a cog of several orgs), plan-11324 S3a
from astryx import config, paths  # noqa: E402


def creds() -> tuple[str, str]:
    """GMAIL_ADDRESS / GMAIL_APP_PASSWORD from the org's .env, read at use, not import."""
    env = config.read_env(paths.estate(__file__) / ".env")      # the ONE .env reader, per line (plan-10224 ENVREAD)
    return env["GMAIL_ADDRESS"], env["GMAIL_APP_PASSWORD"]


mcp = FastMCP("astryx-gmail")


def imap() -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(*creds())
    return m


def gm_search(m, query: str) -> list[bytes]:
    """X-GM-RAW with the query sent as an IMAP literal, so quotes, backslashes and
    non-ASCII reach Gmail untouched. Inlined as "{query}" it broke on any query
    containing a quote (subject:"two words" -> BAD Could not parse command)."""
    m.literal = query.encode("utf-8")
    _, data = m.search("UTF-8", "X-GM-RAW")
    return data[0].split()


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
    """Search the mailbox with Gmail's own syntax (from:, subject:, newer_than:2d,
    is:unread, has:attachment, label:x). Returns newest first: id, from, subject,
    date, unread. Use mail_read(id) for a body."""
    m = imap()
    try:
        m.select("INBOX", readonly=True)
        ids = gm_search(m, query)[-min(limit, 50):]
        return list(reversed(fetch_headers(m, ids)))
    finally:
        m.logout()


@mcp.tool()
def mail_recent(limit: int = 10) -> list[dict]:
    """The newest inbox messages: id, from, subject, date, unread."""
    m = imap()
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
    m = imap()
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
def mail_send(to: str, subject: str, body: str, cc: str = "") -> dict:
    """Send a plain-text email from the owner's address. OUTWARD ACT: unless your
    charter says otherwise, sign the body as yourself (the agent), never as the
    owner. Args: to (comma-separated ok), subject, body, optional cc."""
    addr, pw = creds()
    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(addr, pw)
        s.send_message(msg)
    return {"sent": True, "to": to, "subject": subject}


if __name__ == "__main__":
    mcp.run()
