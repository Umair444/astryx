#!/usr/bin/env python3
"""Oracle: astryx.config is the ONE .env reader/writer, with the semantics the existing readers share
(bridges/common.py env(), pulse.py's DSN): a non-empty process variable wins, else the FIRST `KEY=` line, split on
the first '=', stripped, no quote handling. set_env edits in place: other lines byte for byte, mode 600, the value
never printed. Hermetic: temp files only.
"""
import contextlib
import io
import os
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from astryx import config  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-cfg-"))
    f = t / ".env"
    # host-independent: every environ names an absent registry, so a cog host's /etc/astryx/cog.json is never read
    E = {"ASTRYX_COG_REGISTRY": str(t / "no-registry" / "cog.json")}
    body = ("# a comment\nASTRYX_DSN=postgresql://u:p=q@127.0.0.1:5432/astryx  \n\nQUOTED=\"x\"\n"
            "DUP=first\nDUP=second\n  INDENTED=1\nnoequals\n")
    f.write_text(body)
    e = config.read_env(f)
    arm("value split on the FIRST '=' and stripped", e.get("ASTRYX_DSN") == "postgresql://u:p=q@127.0.0.1:5432/astryx")
    arm("quotes are kept (cut -d= -f2- semantics)", e.get("QUOTED") == '"x"', e.get("QUOTED"))
    arm("the FIRST occurrence wins", e.get("DUP") == "first")
    arm("comments, blanks, indented keys and bare words are not keys",
        "# a comment" not in e and "  INDENTED" not in e and "noequals" not in e, str(sorted(e)))
    arm("a missing file reads as empty", config.read_env(t / "nope") == {})
    arm("get: a non-empty environment variable wins",
        config.get("ASTRYX_DSN", path=f, environ={**E, "ASTRYX_DSN": "env-dsn"}) == "env-dsn")
    arm("get: an EMPTY environment variable falls through to the file",
        config.get("DUP", path=f, environ={**E, "DUP": ""}) == "first")
    arm("dsn(): from the file", config.dsn(path=f, environ={**E}) == "postgresql://u:p=q@127.0.0.1:5432/astryx")
    try:
        config.dsn(path=t / "nope", environ={**E})
        arm("dsn(): absent everywhere raises LookupError", False)
    except LookupError:
        arm("dsn(): absent everywhere raises LookupError", True)

    secret = "tok-SECRET-9f8e7d"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        config.set_env("TG_BOT_TOKEN", secret, f)
    after = f.read_text()
    arm("set_env appends a new key; every other line is kept byte for byte",
        after == body + f"TG_BOT_TOKEN={secret}\n", repr(after[-80:]))
    arm("set_env leaves the file mode 600", stat.S_IMODE(os.stat(f).st_mode) == 0o600, oct(os.stat(f).st_mode))
    arm("set_env prints nothing", buf.getvalue() == "", buf.getvalue())
    config.set_env("DUP", "new", f)
    lines = f.read_text().splitlines()
    arm("set_env replaces the FIRST occurrence in place (same line number) and drops the later one (plan-11860 BC-1)",
        lines[4] == "DUP=new" and "DUP=second" not in lines and sum(ln.startswith("DUP=") for ln in lines) == 1
        and config.read_env(f)["DUP"] == "new", str(lines[3:7]))
    g = t / "nonl"
    g.write_text("A=1")
    config.set_env("B", "2", g)
    arm("a last line without a newline gets one before the append", g.read_text() == "A=1\nB=2\n", repr(g.read_text()))
    for bad in (("K", "a\nB=evil"), ("K=V", "x"), ("", "x")):
        try:
            config.set_env(*bad, path=g)
            arm(f"set_env refuses {bad!r}", False)
        except ValueError:
            arm(f"set_env refuses {bad!r}", g.read_text() == "A=1\nB=2\n")
    arm("no temp files are left beside .env", sorted(p.name for p in t.iterdir()) == [".env", "nonl"],
        str(sorted(p.name for p in t.iterdir())))
    # ENVREAD (plan-10224, seed #61855): decoded per line; a line that is not UTF-8 is skipped LOUDLY, never its value
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        e = config.read_env(f)
    arm("a valid file reads with NOTHING on stderr", buf.getvalue() == "" and e.get("DUP") == "new", buf.getvalue())
    planted = "pw-PLANTED-4c3b"
    h = t / "bad"
    h.write_bytes(b"ASTRYX_ORG=a.fixture.test\nNOTE=\xff\xfe " + planted.encode() + b"\n# \xff a comment\n"
                  b"GMAIL_APP_PASSWORD=\xfe" + planted.encode() + b"\nGMAIL_APP_PASSWORD=second\nTAIL=1\n")
    raw = h.read_bytes()
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        e = config.read_env(h)
    w = buf.getvalue()
    arm("a bad byte on an UNRELATED line: the asked keys before and after it read",
        e.get("ASTRYX_ORG") == "a.fixture.test" and e.get("TAIL") == "1", str(sorted(e)))
    arm("a bad byte on the ASKED key's first line: it reads as ABSENT (its later line is not taken in its place)",
        "GMAIL_APP_PASSWORD" not in e and "NOTE" not in e, str(sorted(e)))
    arm("each bad line is said on stderr as file:line, and the absent key named",
        f"{h}:2: not UTF-8" in w and f"{h}:4: not UTF-8" in w and "(GMAIL_APP_PASSWORD reads as absent)" in w
        and ":3:" not in w, w)
    arm("...never the line's bytes or value", planted not in w and "\ufffd" not in w, w)
    try:
        config.set_env("TAIL", "2", h)
        arm("set_env on a non-UTF-8 .env raises (a skipping writer would drop the line)", False)
    except UnicodeDecodeError:
        arm("set_env on a non-UTF-8 .env raises (a skipping writer would drop the line), the file unchanged",
            h.read_bytes() == raw)
    print(f"\n{'FAIL' if fails else 'ALL PASS'}: astryx config ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
