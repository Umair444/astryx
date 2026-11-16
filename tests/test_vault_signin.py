#!/usr/bin/env python3
"""Oracle: signing a Claude login in from the Agents tab (observatory/api/vault.py, medic 12364 R3). A FAKE `claude`
on PATH stands in for Claude Code's setup-token: it prints an OSC-8 sign-in link, waits for a code, and prints a
synthetic token. No network, temp estate.
  S1 start: the answer is the sign-in URL and nothing else of the terminal's text
  S2 a code of the wrong shape (a newline, a control byte, empty): 400, nothing written
  S6 the token arriving in two writes, a styled word right after it: the WHOLE token, no suffix (medic 12472)
  S7 a login Claude doesn't accept (the proof call fails): 400, nothing in .env
  S3 the right code: the login lands in .env under the derived key and in the vault as a login; no response carries the
     token; the throwaway home is gone; the fake saw HOME and CLAUDE_CONFIG_DIR inside that home, never the real one
  S4 a code for a sign-in that isn't running: 409
  S5 not the owner: 403 before anything runs
Exit 0 · 1."""
import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "src"))
from astryx import config  # noqa: E402
from astryx.core import vault as V  # noqa: E402
from observatory.api import vault as API  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


TOKEN = "sk-ant-oat01-" + "T" * 60
FAKE = f'''#!/usr/bin/env python3
import os, sys
open(os.environ["FAKE_SEEN"], "w").write(os.environ.get("HOME", "") + "\\n" + os.environ.get("CLAUDE_CONFIG_DIR", ""))
sys.stdout.write("Welcome\\r\\n\\x1b]8;id=1;https://claude.com/cai/oauth/authorize?code=true&state=abc\\x1b\\\\link\\x1b]8;;\\x1b\\\\\\r\\nPaste code here if prompted > ")
sys.stdout.flush()
code = sys.stdin.readline().strip()
import time
if code == "GOOD-CODE-123":                  # the token in two writes 200 ms apart, then a styled word right after it
    sys.stdout.write("\\r\\nYour OAuth token (valid for 1 year):\\r\\n{TOKEN[:30]}")
    sys.stdout.flush()
    time.sleep(0.2)
    sys.stdout.write("{TOKEN[30:]}\\x1b[1mStore it safely\\x1b[0m\\r\\n")
else:
    sys.stdout.write("\\r\\nOAuth error\\r\\n")
sys.stdout.flush()
'''


class Req:
    pass


def call(fn, *a, owner=True):
    API.bind(lambda r: owner, EST)
    r = asyncio.run(fn(*a, Req()))
    return (200, r) if isinstance(r, dict) else (r.status_code, json.loads(r.body))


with tempfile.TemporaryDirectory() as td:
    EST = Path(td) / "estate"
    EST.mkdir()
    (EST / ".env").write_text("ASTRYX_DSN=postgres://x\n")
    bindir = Path(td) / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text(FAKE)
    (bindir / "claude").chmod(0o755)
    seen = Path(td) / "seen"
    os.environ["FAKE_SEEN"] = str(seen)
    API._shutil.which = lambda n: str(bindir / "claude")
    st, b = call(API.vault_signin_start, "Second", owner=False)
    arm("S5 not the owner: 403", st == 403)
    import subprocess as _sp
    real_popen = _sp.Popen
    _sp.Popen = lambda *a, **k: real_popen(*a, **{**k, "env": {**k["env"], "FAKE_SEEN": str(seen)}})
    try:
        st, b = call(API.vault_signin_start, "Second")
        arm("S1 start answers the sign-in URL and nothing else", st == 200 and set(b) == {"url"} and b["url"].startswith("https://claude.com/cai/oauth/authorize?"), (st, b))
        home = API._SIGNIN["now"]["home"]
        for bad in ("", "a\nb", "x\x1b[A", "has space"):
            st2, b2 = call(API.vault_signin_code, "Second", API.Code(code=bad))
            arm(f"S2 a code of the wrong shape is refused: {bad!r}", st2 == 400 and "ASTRYX_CRED_SECOND" not in config.read_env(EST / ".env"), (st2, b2))
        API._proves = lambda home, token: False
        st, b = call(API.vault_signin_code, "Second", API.Code(code="GOOD-CODE-123"))
        arm("S7 a login the proof call rejects: 400, nothing in .env", st == 400 and "ASTRYX_CRED_SECOND" not in config.read_env(EST / ".env"), (st, b))
        proved = []
        API._proves = lambda home, token: proved.append(token) or True
        st, b = call(API.vault_signin_start, "Second")
        home = API._SIGNIN["now"]["home"]
        st, b = call(API.vault_signin_code, "Second", API.Code(code="GOOD-CODE-123"))
        env = config.read_env(EST / ".env")
        arm("S6 the token in two writes with a styled word after it: stored WHOLE, no suffix", env.get("ASTRYX_CRED_SECOND") == TOKEN and proved == [TOKEN], (env.get("ASTRYX_CRED_SECOND", "")[-20:], len(proved)))
        arm("S3 the login lands under the derived key, and the vault holds it as a login", st == 200 and env.get("ASTRYX_CRED_SECOND") == TOKEN and V.load(EST).get("Second", {}).get("kind") == "login", (st, b))
        arm("S3 no response carries the token", TOKEN not in json.dumps(b))
        arm("S3 the throwaway home is removed", not Path(home).exists())
        h, cfg = seen.read_text().split("\n")
        arm("S3 setup-token ran with HOME and its config inside the throwaway home, never the real one",
            h == home and cfg == os.path.join(home, "cfg") and h != os.path.expanduser("~"), (h, cfg))
        st, b = call(API.vault_signin_code, "Second", API.Code(code="GOOD-CODE-123"))
        arm("S4 a code for a sign-in that isn't running: 409", st == 409, (st, b))
    finally:
        _sp.Popen = real_popen
        API._signin_end()

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a Claude login signs in from the tab, its token only in .env")
sys.exit(1 if fails else 0)
