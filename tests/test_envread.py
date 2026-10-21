#!/usr/bin/env python3
"""Oracle: every Python .env reader reads through config.read_env, which decodes PER LINE (plan-10224 ENVREAD, seed
#61855): a line that is not UTF-8 is skipped and said on stderr as file:line (never its bytes or value), every other
key reads, and a key whose first line is the bad one reads as absent.

The package is copied into a temp tree T (T/src/astryx/…), so paths.estate() of each seated module is T and its .env
is the fixture's. Each arm runs in a child under a pinned absent registry, with no ASTRYX_*/HANDS_*/ANDROID_* inherited.
  E0 read_env itself: an unrelated bad line → the other keys read; the asked key's bad line → absent (its later line
     not taken); stderr names file:line, never the planted value
  E1 contrib/canopus_inbound.py   GMAIL_ADDRESS at import          E2 federation/card_assert.py   _env("ASTRYX_ORG")
  E3 hands/android.py             sdk() from ANDROID_SDK_ROOT       E4 hands/hands_desktop.py      _env_int("HANDS_STEP_CAP")
  E5 pulse/shipped_triggers/org_backup.py   _org(estate)
     each: the asked key reads past a non-UTF-8 line, and the skip is said on stderr without the value
  E6 NAMES' clash check (`orgs.py dupnames`) over a non-UTF-8 .env: never rc 2; two orgs under one name still rc 1
Seams: ENVREAD_SEAT="<path under src/astryx>=<file>[;…]" seats that file in place of the checkout's (the RED: an old
site), ENVREAD_CONFIG_SRC=<file> seats a config.py (tests/mutants_envread.py). Residuals, not migrated: shell `grep '^KEY=' .env`, home.mjs.
Exit 0 · 1.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "astryx"
PLANTED = "fx-PLANTED-77a1"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def seat(t: Path) -> None:
    shutil.copytree(PKG, t / "src" / "astryx", ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
    (t / "mcp").symlink_to(REPO / "mcp")      # hands/android.py imports mcp/phone/surface.py from its tree (code, no estate)
    for pair in filter(None, (os.environ.get("ENVREAD_SEAT") or "").split(";")):
        rel, src = pair.split("=", 1)
        shutil.copyfile(src, t / "src" / "astryx" / rel)
    if os.environ.get("ENVREAD_CONFIG_SRC"):                       # the probe's seam: a mutant config.py
        shutil.copyfile(os.environ["ENVREAD_CONFIG_SRC"], t / "src" / "astryx" / "config.py")


def child(t: Path, code: str, *args, reg=None):
    # own-env: the child's registry and package path are named here; ASTRYX_*, HANDS_*, ANDROID_* are dropped
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ASTRYX_", "HANDS_", "ANDROID_"))}
    env.update(ASTRYX_COG_REGISTRY=str(reg or t / "no-registry" / "cog.json"), PYTHONPATH=str(t / "src"))
    r = subprocess.run([sys.executable, "-c", code, *args] if code else list(args), cwd=t, env=env,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout.strip(), r.stderr


BAD = b"NOTE=\xff\xfe " + PLANTED.encode() + b"\n"       # line 2 of every fixture .env
ENV = (b"ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/astryx_fx_envread\n" + BAD
       + b"ASTRYX_ORG=envread.fixture.test\nGMAIL_ADDRESS=fixture@example.invalid\n"
       b"GMAIL_APP_PASSWORD=fx-not-a-password\nANDROID_SDK_ROOT=/fx/sdk\nHANDS_STEP_CAP=7\n")
SITES = [
    ("E1", "contrib/canopus_inbound.py", "import sys, types; sys.modules.setdefault('psycopg', types.ModuleType('psycopg'));"
     " import astryx.contrib.canopus_inbound as m; print(m.ADDR)",   # psycopg is only main()'s: a stub where it's absent
     "fixture@example.invalid"),
    ("E2", "federation/card_assert.py", "import astryx.federation.card_assert as m; print(m._env('ASTRYX_ORG'))",
     "envread.fixture.test"),
    ("E3", "hands/android.py", "import astryx.hands.android as m; print(m.sdk())", "/fx/sdk"),
    ("E4", "hands/hands_desktop.py", "import astryx.hands.hands_desktop as m; print(m._env_int('HANDS_STEP_CAP', 300))",
     "7"),
    ("E5", "pulse/shipped_triggers/org_backup.py",
     "import pathlib, astryx.pulse.shipped_triggers.org_backup as m; print(m._org(pathlib.Path.cwd()))",
     "envread.fixture.test"),
]


def said(err: str, f: Path, n: int) -> bool:
    return f"{f}:{n}: not UTF-8, line skipped" in err and PLANTED not in err and "�" not in err


with tempfile.TemporaryDirectory() as td:
    t = Path(td).resolve()
    seat(t)
    (t / ".env").write_bytes(ENV)

    print("E0 read_env ITSELF")
    e0 = t / "e0.env"
    e0.write_bytes(b"A=1\n" + BAD + b"K=\xfe" + PLANTED.encode() + b"\nK=later\nB=2\n")
    rc, out, err = child(t, "import json, sys; from astryx import config; print(json.dumps(config.read_env(sys.argv[1])))",
                         str(e0))
    try:
        got = json.loads(out) if rc == 0 else None        # stdout is the dict alone: a word printed there is a FAIL
    except ValueError:
        got = None
    check("an unrelated bad line: the keys before and after it read", got is not None and got.get("A") == "1"
          and got.get("B") == "2", f"rc {rc} {out!r} {err[-200:]!r}")
    check("the asked key's bad FIRST line: absent, its later line not taken in its place",
          got is not None and "K" not in got and "NOTE" not in got, f"{got}")
    check("stderr says each bad line as file:line and names the absent key, never the value",
          said(err, e0, 2) and said(err, e0, 3) and "(K reads as absent)" in err, err[-300:])

    for tag, rel, code, want in SITES:
        print(f"\n{tag} {rel}")
        rc, out, err = child(t, code)
        check(f"the asked key reads past a non-UTF-8 line ({want})", rc == 0 and out == want,
              f"rc {rc} {out!r} {err.strip().splitlines()[-1:] if err.strip() else ''}")
        check("the skip is said on stderr as file:line, without the value", said(err, t / ".env", 2), err[-200:])

    print("\nE6 NAMES' CLASH CHECK OVER A NON-UTF-8 .env")
    homes = {}
    for o, name, bad in (("fxa", "a.fixture.test", True), ("fxb", "b.fixture.test", False),
                         ("fxc", "A.fixture.test", True)):
        h = t / f"home-{o}"
        h.mkdir()
        (h / ".env").write_bytes(b"ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/fx\n" + (BAD if bad else b"")
                                 + f"ASTRYX_ORG={name}\n".encode())
        homes[o] = h

    def reg(keys, fn):
        f = t / fn
        f.write_text(json.dumps({"orgs": {o: {"home": str(homes[o]), "db": f"fxenvread_{o}"} for o in keys}}))
        return f

    orgs_py = str(t / "src" / "astryx" / "orgs.py")
    rc, out, err = child(t, None, sys.executable, orgs_py, "dupnames", reg=reg(["fxa", "fxb"], "r2.json"))
    check("distinct names, one .env not UTF-8: rc 0 (never 2, the clash check is not blinded)", rc == 0 and out == "",
          f"rc {rc} {out!r} {err[-200:]!r}")
    rc, out, err = child(t, None, sys.executable, orgs_py, "dupnames", reg=reg(["fxa", "fxb", "fxc"], "r3.json"))
    check("two orgs under one name, both .env not UTF-8: rc 1 naming both (the clash is still seen)",
          rc == 1 and out == "a.fixture.test\tfxa fxc", f"rc {rc} {out!r} {err[-200:]!r}")

print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
      "ALL PASS: every Python .env reader reads through config.read_env, per line, a bad line skipped loudly")
sys.exit(1 if fails else 0)
