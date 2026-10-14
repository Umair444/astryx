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
        config.get("ASTRYX_DSN", path=f, environ={"ASTRYX_DSN": "env-dsn"}) == "env-dsn")
    arm("get: an EMPTY environment variable falls through to the file",
        config.get("DUP", path=f, environ={"DUP": ""}) == "first")
    arm("dsn(): from the file", config.dsn(path=f, environ={}) == "postgresql://u:p=q@127.0.0.1:5432/astryx")
    try:
        config.dsn(path=t / "nope", environ={})
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
    arm("set_env replaces the FIRST occurrence in place (same line number)",
        lines[4] == "DUP=new" and lines[5] == "DUP=second" and config.read_env(f)["DUP"] == "new", str(lines[3:7]))
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
    print(f"\n{'FAIL' if fails else 'ALL PASS'}: astryx config ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
