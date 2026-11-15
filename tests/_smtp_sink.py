"""A loopback SMTP sink for the tests that mail (tests/test_signup.py, tests/test_admin_panel.py): enough of RFC 5321
for smtplib, delivering nothing."""
import socket
import threading


class SmtpSink:
    """A loopback SMTP server just big enough for smtplib: it keeps each mail's (recipients, text)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.mails: list[tuple[list[str], str]] = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.conn, args=(c,), daemon=True).start()

    def conn(self, c):
        f, rcpt = c.makefile("rb"), []
        c.sendall(b"220 fx-sink ready\r\n")
        while (line := f.readline()):
            cmd = line[:4].upper()
            if cmd == b"EHLO":
                c.sendall(b"250-fx-sink\r\n250 8BITMIME\r\n")
            elif cmd == b"RCPT":
                rcpt.append(line.split(b"<", 1)[1].split(b">", 1)[0].decode())
                c.sendall(b"250 ok\r\n")
            elif cmd == b"DATA":
                c.sendall(b"354 go\r\n")
                body = b""
                while (ln := f.readline()) not in (b".\r\n", b""):
                    body += ln
                self.mails.append((rcpt, body.decode("utf-8", "replace")))
                rcpt = []
                c.sendall(b"250 queued\r\n")
            elif cmd == b"QUIT":
                c.sendall(b"221 bye\r\n")
                return
            else:
                c.sendall(b"250 ok\r\n")


def dead_port() -> int:
    """A loopback port nothing listens on (bound, then closed): a connect to it is refused."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
