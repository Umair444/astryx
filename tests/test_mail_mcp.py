#!/usr/bin/env python3
"""Oracle: the mail tool (mcp/mail/server.py over src/astryx/mail.py) on ANY mail server: a Gmail query reaches IMAP
byte-exact, whatever it contains; another server gets IMAP criteria or a TEXT search; SMTP speaks by the port and logs
in only when there is a password (owner 11-15: "it should be general … here we have our own servers").

    venv/bin/python tests/test_mail_mcp.py

Hermetic. A fake IMAP server on loopback speaks enough of RFC 3501 to parse a SEARCH
command the way a strict server does: atoms, quoted strings with \\" and \\\\ escapes, and
{n} literals with their "+" continuation. It answers BAD on a malformed command, which is
what Gmail did to an inlined "{query}" holding a quote. The real imaplib client is driven
against it, so the test sees the bytes the tool really sends. The mutant arm puts the old
inline form back and requires the quote arm to fail. SMTP is driven through a recording stand-in for smtplib's two
classes (S arms). Neutral fixtures only.
"""
import importlib.util
import imaplib
import smtplib
import shutil
import socket
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_mail_mcp", REPO, deps=("mcp.server",), env=False)   # a committed-only tree (no venv): 77, not an import crash
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {str(detail)[:300]}")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeImap:
    """One connection at a time. `seen` holds each SEARCH's argument, decoded: the X-GM-RAW query on a Gmail-like
    fake (gm=True), else the criteria as sent ("TEXT <word>" for a literal)."""

    def __init__(self, gm: bool = True):
        self.gm = gm
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.seen: list[str] = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.conn, args=(c,), daemon=True).start()

    def conn(self, c):
        f = c.makefile("rb")
        c.sendall(b"* OK fake ready\r\n")
        while True:
            line = f.readline()
            if not line:
                return
            raw = line
            while raw.rstrip(b"\r\n").endswith(b"}") and b"{" in raw:   # literal continuation
                head = raw.rstrip(b"\r\n")
                n = int(head.rsplit(b"{", 1)[1][:-1])
                c.sendall(b"+ go ahead\r\n")
                raw = head[:head.rfind(b"{")] + b"\x00LIT" + f.read(n) + f.readline()
            tag, _, rest = raw.partition(b" ")
            cmd, _, args = rest.partition(b" ")
            cmd = cmd.strip().upper()
            if cmd == b"CAPABILITY":
                c.sendall(b"* CAPABILITY IMAP4rev1" + (b" X-GM-EXT-1" if self.gm else b"") + b"\r\n" + tag + b" OK done\r\n")
            elif cmd == b"LOGIN":
                c.sendall(tag + b" OK logged in\r\n")
            elif cmd in (b"SELECT", b"EXAMINE"):
                c.sendall(b"* 3 EXISTS\r\n" + tag + b" OK [READ-ONLY] selected\r\n")
            elif cmd == b"LOGOUT":
                c.sendall(b"* BYE\r\n" + tag + b" OK bye\r\n")
                return
            elif cmd == b"SEARCH":
                q = self.parse_search(args.rstrip(b"\r\n"))
                if q is None:
                    c.sendall(tag + b" BAD Could not parse command\r\n")
                else:
                    self.seen.append(q)
                    c.sendall(b"* SEARCH 1 2 3\r\n" + tag + b" OK search done\r\n")
            else:
                c.sendall(tag + b" BAD unknown\r\n")

    @staticmethod
    def tokens(b: bytes):
        """Strict RFC 3501 tokens: atom | quoted | literal. None on any malformation."""
        out, i = [], 0
        while i < len(b):
            if b[i:i + 1] == b" ":
                i += 1
            elif b[i:i + 4] == b"\x00LIT":
                out.append(b[i + 4:].removesuffix(b"\r\n"))          # a literal runs to the end of what we framed
                return out
            elif b[i:i + 1] == b'"':
                i, s = i + 1, bytearray()
                while True:
                    if i >= len(b):
                        return None
                    ch = b[i:i + 1]
                    if ch == b"\\":
                        if b[i + 1:i + 2] not in (b'"', b"\\"):
                            return None
                        s += b[i + 1:i + 2]
                        i += 2
                    elif ch == b'"':
                        i += 1
                        break
                    elif ord(ch) > 0x7f:
                        return None
                    else:
                        s += ch
                        i += 1
                if i < len(b) and b[i:i + 1] != b" ":
                    return None                # text glued after a closing quote
                out.append(bytes(s))
            elif b[i:i + 1] == b"{":
                return None                    # a literal marker we did not frame
            else:
                j = b.find(b" ", i)
                j = len(b) if j < 0 else j
                atom = b[i:j]
                if b'"' in atom or b"\\" in atom:
                    return None
                out.append(atom)
                i = j
        return out

    def parse_search(self, args: bytes):
        t = self.tokens(args)
        if not t:
            return None
        if t[0].upper() == b"CHARSET":
            t = t[2:]
        if not self.gm:
            return b" ".join(t).decode("utf-8", errors="replace")
        if len(t) != 2 or t[0].upper() != b"X-GM-RAW":
            return None
        try:
            return t[1].decode("utf-8")
        except UnicodeDecodeError:
            return None


def box(port: int) -> dict:
    return {"MAIL_FROM": "agent@example.invalid", "MAIL_IMAP": f"127.0.0.1:{port}", "MAIL_SECURITY": "plain",
            "MAIL_PASSWORD": "p"}


def run_arms(S, label: str, queries=None, gm=True, want=lambda q: q) -> dict:
    """Each query through the real imaplib, by the server's own env and mail.imap, to the fake; {query: ok?}."""
    fake = FakeImap(gm)
    S.env = lambda: box(fake.port)
    S.fetch_headers = lambda m, ids: [{"id": i.decode()} for i in ids]
    res = {}
    for q in queries or QUERIES:
        before = len(fake.seen)
        try:
            got = S.mail_search(q, limit=10)
            res[q] = (len(fake.seen) == before + 1 and fake.seen[-1] == want(q) and len(got) == 3)
            if not res[q]:
                res[q + " :err"] = fake.seen[before:]
        except Exception as e:
            res[q] = False
            res[q + " :err"] = str(e)[:120]
    fake.sock.close()
    return res


class Rec:
    """Stands in for smtplib.SMTP / SMTP_SSL: records what one send did, delivers nothing."""
    log: list = []

    def __init__(self, host, port, timeout=None):
        self.ev = [type(self).__name__, host, port]
        Rec.log.append(self.ev)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.ev.append("starttls")

    def login(self, u, p):
        self.ev.append(("login", u))

    def send_message(self, msg, to_addrs=None):
        self.ev.append(("send", sorted(to_addrs), msg["Bcc"], msg["From"], bool(msg["Message-ID"]), bool(msg["Date"])))


class SMTP(Rec):
    pass


class SMTP_SSL(Rec):
    pass


def smtp_arms(mail):
    smtplib.SMTP, smtplib.SMTP_SSL = SMTP, SMTP_SSL
    relay = {"MAIL_FROM": "team@example.invalid", "MAIL_SMTP": "relay.example.invalid:25"}

    def one(env, **kw):
        Rec.log.clear()
        mail.send(env, "a@example.invalid", "s", "b", **kw)
        return Rec.log[0]
    ev = one(relay, cc="c@example.invalid", bcc="z@example.invalid")
    check("S1 a relay with no password: plain SMTP on its port, no STARTTLS, NO login; bcc a recipient, never a header",
          ev == ["SMTP", "relay.example.invalid", 25,
                 ("send", ["a@example.invalid", "c@example.invalid", "z@example.invalid"], None, "team@example.invalid",
                  True, True)], ev)
    ev = one({**relay, "MAIL_SMTP": "smtp.example.invalid:465", "MAIL_PASSWORD": "app"})
    check("S2 port 465: TLS from the start, login as MAIL_FROM", ev[:3] == ["SMTP_SSL", "smtp.example.invalid", 465]
          and ev[3] == ("login", "team@example.invalid") and "starttls" not in ev, ev)
    ev = one({**relay, "MAIL_SMTP": "smtp.example.invalid:587", "MAIL_PASSWORD": "app", "MAIL_USER": "login-name"})
    check("S3 port 587: STARTTLS, then login as MAIL_USER", ev[:5] == ["SMTP", "smtp.example.invalid", 587, "starttls",
          ("login", "login-name")], ev)
    ev = one({**relay, "MAIL_SECURITY": "starttls", "MAIL_SMTP": "relay.example.invalid"})
    check("S4 MAIL_SECURITY overrides the port; a bare host is port 25", ev[:4] == ["SMTP", "relay.example.invalid", 25,
          "starttls"], ev)
    for name, env, err in (("S5 no mailbox is NotConfigured, not a crash", {}, mail.NotConfigured),
                           ("S6 an unknown MAIL_SECURITY is refused by name", {**relay, "MAIL_SECURITY": "tls"}, ValueError)):
        try:
            one(env)
            check(name, False, "sent")
        except err:
            check(name, True)
    for to in ("a@example.invalid,b@example.invalid", "a@example.invalid;b@example.invalid", "A <a@example.invalid>"):
        Rec.log.clear()
        try:
            mail.send(relay, to, "s", "b", one=True)
            check(f"S9 one=True refuses {to!r}", False, Rec.log)
        except ValueError:
            check(f"S9 one=True refuses {to!r}, before any connection", Rec.log == [], Rec.log)
    try:
        mail.search(None, "UNSEEN\r\nA1 LOGOUT")
        check("S10 a search query with a line break is refused", False, "passed")
    except ValueError:
        check("S10 a search query with a line break is refused", True)
    check("S7 a send-only mailbox doesn't claim to read", mail.configured(relay) and not mail.configured(relay, read=True))
    try:
        mail.imap({**relay, "MAIL_IMAP": "127.0.0.1:1", "MAIL_SECURITY": "plain"})   # nothing listens on port 1
        check("S8 reading with no password is refused before any connection", False, "returned")
    except mail.NotConfigured:
        check("S8 reading with no password is refused before any connection", True)
    except OSError as e:
        check("S8 reading with no password is refused before any connection", False, f"it dialled: {e}")


QUERIES = [
    "newer_than:2d",                               # the form that always worked
    'subject:"two words" newer_than:30d',          # the form that broke: a quote
    'from:a@example.com subject:"x \\ y"',         # a backslash
    'subject:"für Sie" newer_than:7d',             # non-ASCII
    "{from:a.example from:b.example} newer_than:14d",   # Gmail OR braces
]

OTHER = ['FROM "a@example.com" SINCE 1-Nov-2026', "UNSEEN", "invoice"]
OTHER_WANT = {"invoice": "TEXT invoice",                             # the fake reports tokens decoded:
              OTHER[0]: "FROM a@example.com SINCE 1-Nov-2026"}         # a quoted string arrives as its text

SRC = REPO / "mcp" / "mail" / "server.py"
LIB = REPO / "src" / "astryx" / "mail.py"
tmp = Path(tempfile.mkdtemp(prefix="mail-oracle."))
try:
    # A tree with no .env: the module imports; the mailbox is read only at use.
    (tmp / "mcp" / "mail").mkdir(parents=True)
    shutil.copy(SRC, tmp / "mcp" / "mail" / "server.py")
    try:
        S = load(tmp / "mcp" / "mail" / "server.py", "mail_noenv")
        check("I0 imports in a tree without .env", True)
    except Exception as e:
        S = None
        check("I0 imports in a tree without .env", False, e)
    if S:
        try:
            S.mail_recent()
            check("I1 a tool without a mailbox fails at use", False, "returned")
        except (FileNotFoundError, KeyError, S.mail.NotConfigured):
            check("I1 a tool without a mailbox fails at use", True)

    print("live code, a Gmail-like server:")
    S = load(tmp / "mcp" / "mail" / "server.py", "mail_live")
    r = run_arms(S, "live")
    for i, q in enumerate(QUERIES):
        check(f"G{i} byte-exact query: {q!r}", r[q], r.get(q + " :err", ""))
    print("live code, any other IMAP server:")
    r = run_arms(S, "other", OTHER, gm=False, want=lambda q: OTHER_WANT.get(q, q))
    for i, q in enumerate(OTHER):
        check(f"O{i} {'a plain word is a TEXT search' if q == 'invoice' else 'criteria as sent'}: {q!r}", r[q],
              r.get(q + " :err", ""))
    print("SMTP by the port, a login only with a password:")
    smtp_arms(S.mail)

    print("mutant: the old inline quoting must break the quote arm:")
    src = LIB.read_text()
    old = '''        m.literal = query.encode("utf-8")
        _, data = m.search("UTF-8", "X-GM-RAW")'''
    check("M0 mutation site present", old in src)
    (tmp / "mutant.py").write_text(src.replace(old, '''        _, data = m.search(None, "X-GM-RAW", f'"{query}"')'''))
    S.mail = load(tmp / "mutant.py", "mail_mutant")
    mr = run_arms(S, "mutant")
    check("M1 mutant keeps the plain query (fake is not just refusing everything)", mr[QUERIES[0]])
    check("M2 mutant FAILS the quote query (the fake catches the real bug)", not mr[QUERIES[1]])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{'FAIL' if fails else 'OK'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
