"""astryx · mail — the ONE mail client: any SMTP server to send, any IMAP server to read (owner 11-15: "it should be
general … here we have our own servers; for gmail an application code is required").

A mailbox is five keys in an .env (the org's for agents, the cog home's for the front's sign-in codes):
  MAIL_FROM       the address mail is sent from (and the login, unless MAIL_USER says otherwise)
  MAIL_SMTP       host:port of the server that sends; 465 speaks TLS from the start, 587 upgrades with STARTTLS,
                  any other port (25, a relay inside the network) is plain. MAIL_SECURITY=ssl|starttls|plain overrides
  MAIL_PASSWORD   empty for a relay that takes mail without a login (no login is attempted at all); for Gmail and
                  most hosted mail, an app password
  MAIL_USER       the login, when it is not MAIL_FROM
  MAIL_IMAP       host:port of the server that reads (993 TLS, 143 STARTTLS); unset = this mailbox only sends
Gmail is one setting of these: MAIL_SMTP=smtp.gmail.com:465, MAIL_IMAP=imap.gmail.com:993, MAIL_PASSWORD=<app password>.
The values are read at use, never at import. Callers pass the env they mean (config.read_env(<home>/.env)).
"""
from __future__ import annotations

import imaplib
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

TIMEOUT = 20
SECURITY = ("ssl", "starttls", "plain")


class NotConfigured(LookupError):
    """This env names no mailbox (no MAIL_FROM or no MAIL_SMTP / MAIL_IMAP for the act asked)."""


def configured(env: dict, read: bool = False) -> bool:
    return bool(env.get("MAIL_FROM") and env.get("MAIL_IMAP" if read else "MAIL_SMTP"))


def _server(env: dict, key: str, default_port: int) -> tuple[str, int]:
    if not configured(env, read=key == "MAIL_IMAP"):
        raise NotConfigured(f"no mailbox: set MAIL_FROM and {key} in the .env")
    host, sep, port = env[key].strip().rpartition(":")
    return (host, int(port)) if sep else (port, default_port)


def security(env: dict, port: int, tls_port: int, starttls_port: int) -> str:
    s = (env.get("MAIL_SECURITY") or "").strip().lower()
    if s:
        if s not in SECURITY:
            raise ValueError(f"MAIL_SECURITY is {s!r}: one of {', '.join(SECURITY)}")
        return s
    return "ssl" if port == tls_port else "starttls" if port == starttls_port else "plain"


def _login(env: dict) -> tuple[str, str] | None:
    pw = env.get("MAIL_PASSWORD") or ""
    return ((env.get("MAIL_USER") or env["MAIL_FROM"]), pw) if pw else None


def send(env: dict, to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> EmailMessage:
    """Send a plain-text mail from MAIL_FROM. to/cc/bcc take comma-separated addresses; bcc never reaches a header."""
    host, port = _server(env, "MAIL_SMTP", 25)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = env["MAIL_FROM"], to, subject
    msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid(domain=env["MAIL_FROM"].rpartition("@")[2])
    if cc:
        msg["Cc"] = cc
    msg.set_content(body)
    rcpt = [a.strip() for a in ",".join((to, cc, bcc)).split(",") if a.strip()]
    if not rcpt:
        raise ValueError("no recipient")
    sec = security(env, port, 465, 587)
    with (smtplib.SMTP_SSL if sec == "ssl" else smtplib.SMTP)(host, port, timeout=TIMEOUT) as s:
        if sec == "starttls":
            s.starttls()
        if (who := _login(env)):
            s.login(*who)
        s.send_message(msg, to_addrs=rcpt)
    return msg


def imap(env: dict) -> imaplib.IMAP4:
    """A logged-in IMAP connection to MAIL_IMAP; the caller logs out."""
    host, port = _server(env, "MAIL_IMAP", 993)
    if not (who := _login(env)):
        raise NotConfigured("reading a mailbox needs its login: set MAIL_PASSWORD")
    sec = security(env, port, 993, 143)
    m = imaplib.IMAP4_SSL(host, port, timeout=TIMEOUT) if sec == "ssl" else imaplib.IMAP4(host, port, timeout=TIMEOUT)
    if sec == "starttls":
        m.starttls()
    m.login(*who)
    return m


def search(m: imaplib.IMAP4, query: str) -> list[bytes]:
    """Message ids matching `query`. A server that speaks Gmail's extension takes Gmail's own syntax (from:,
    subject:"two words", newer_than:2d) via X-GM-RAW, sent as a literal so quotes and non-ASCII arrive untouched;
    any other server takes IMAP search criteria (FROM "x" SINCE 1-Nov-2026 UNSEEN), or a bare word as TEXT."""
    caps = getattr(m, "capabilities", ())
    if "X-GM-EXT-1" in caps:
        m.literal = query.encode("utf-8")
        _, data = m.search("UTF-8", "X-GM-RAW")
    elif query.split(" ", 1)[0].isupper():
        _, data = m.search(None, query)
    else:
        m.literal = query.encode("utf-8")
        _, data = m.search("UTF-8", "TEXT")
    return data[0].split()
