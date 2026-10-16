#!/usr/bin/env python3
"""Oracle: mcp/gmail/server.py sends a Gmail query to IMAP byte-exact, whatever it contains.

    venv/bin/python tests/test_gmail_mcp.py

Hermetic. A fake IMAP server on loopback speaks enough of RFC 3501 to parse a SEARCH
command the way a strict server does: atoms, quoted strings with \\" and \\\\ escapes, and
{n} literals with their "+" continuation. It answers BAD on a malformed command, which is
what Gmail did to an inlined "{query}" holding a quote. The real imaplib client is driven
against it, so the test sees the bytes the tool really sends. The mutant arm puts the old
inline form back and requires the quote arm to fail. Neutral fixtures only.
"""
import importlib.util
import imaplib
import shutil
import socket
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_gmail_mcp", REPO, deps=("mcp.server",), env=False)   # a committed-only tree (no venv): 77, not an import crash
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
    """One connection at a time. `seen` holds each SEARCH's X-GM-RAW argument, decoded."""

    def __init__(self):
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
                c.sendall(b"* CAPABILITY IMAP4rev1 X-GM-EXT-1\r\n" + tag + b" OK done\r\n")
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
        if len(t) != 2 or t[0].upper() != b"X-GM-RAW":
            return None
        try:
            return t[1].decode("utf-8")
        except UnicodeDecodeError:
            return None


def run_arms(S, label: str) -> dict:
    """Each query through the real imaplib to the fake; returns {query: ok?}."""
    fake = FakeImap()
    S.imap = lambda: _client(fake.port)
    S.fetch_headers = lambda m, ids: [{"id": i.decode()} for i in ids]
    res = {}
    for q in QUERIES:
        before = len(fake.seen)
        try:
            got = S.mail_search(q, limit=10)
            res[q] = (len(fake.seen) == before + 1 and fake.seen[-1] == q and len(got) == 3)
        except Exception as e:
            res[q] = False
            res[q + " :err"] = str(e)[:120]
    fake.sock.close()
    return res


def _client(port):
    m = imaplib.IMAP4("127.0.0.1", port)
    m.login("u", "p")
    return m


QUERIES = [
    "newer_than:2d",                               # the form that always worked
    'subject:"two words" newer_than:30d',          # the form that broke: a quote
    'from:a@example.com subject:"x \\ y"',         # a backslash
    'subject:"für Sie" newer_than:7d',             # non-ASCII
    "{from:a.example from:b.example} newer_than:14d",   # Gmail OR braces
]

SRC = REPO / "mcp" / "gmail" / "server.py"
tmp = Path(tempfile.mkdtemp(prefix="gmail-oracle."))
try:
    # A tree with no .env: the module imports; credentials are read only at use.
    (tmp / "mcp" / "gmail").mkdir(parents=True)
    shutil.copy(SRC, tmp / "mcp" / "gmail" / "server.py")
    try:
        S = load(tmp / "mcp" / "gmail" / "server.py", "gmail_noenv")
        check("I0 imports in a tree without .env", True)
    except Exception as e:
        S = None
        check("I0 imports in a tree without .env", False, e)
    if S:
        try:
            S.creds()
            check("I1 creds() without .env fails at use", False, "returned")
        except (FileNotFoundError, KeyError):
            check("I1 creds() without .env fails at use", True)

    print("live code:")
    S = load(tmp / "mcp" / "gmail" / "server.py", "gmail_live")
    r = run_arms(S, "live")
    for i, q in enumerate(QUERIES):
        check(f"G{i} byte-exact query: {q!r}", r[q], r.get(q + " :err", ""))

    print("mutant: the old inline quoting must break the quote arm:")
    src = SRC.read_text()
    old = '''    m.literal = query.encode("utf-8")
    _, data = m.search("UTF-8", "X-GM-RAW")'''
    check("M0 mutation site present", old in src)
    (tmp / "mutant.py").write_text(src.replace(old, '''    _, data = m.search(None, "X-GM-RAW", f'"{query}"')'''))
    M = load(tmp / "mutant.py", "gmail_mutant")
    mr = run_arms(M, "mutant")
    check("M1 mutant keeps the plain query (fake is not just refusing everything)", mr[QUERIES[0]])
    check("M2 mutant FAILS the quote query (the fake catches the real bug)", not mr[QUERIES[1]])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{'FAIL' if fails else 'OK'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
