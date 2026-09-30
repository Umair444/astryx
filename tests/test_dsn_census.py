"""Oracle for nucleus/dsn_census.py, the S1c-0 gate (plan-5497). Hermetic: no DB, no processes.

The census decides whether the org may switch to password-less DSNs, so its OWN logic must not be
able to pass vacuously. Each arm can ALONE go red:
  D1 passwordless() drops the password and keeps user, host (literally: localhost != 127.0.0.1),
     port and database.
  D2 dsns() derives every *_DSN from the files it reads, password-less; nothing else.
  D3 census() adds a localhost POSITIVE CONTROL for every non-localhost DSN (a failing control
     means the instrument is broken, not the pgpass).
  D4 a bare `env -i` runner is REPORTED, never required; every other runner is required.
  D5 main() fails on ANY required failure, and on ZERO probes (a census that observed nothing).
  D6 probe() returns an error CLASS, never the error text (which can quote a DSN).

Run: venv/bin/python tests/test_dsn_census.py
"""
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
fails = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


try:
    from nucleus import dsn_census as c
except Exception as exc:                                    # noqa: BLE001
    check("nucleus.dsn_census imports", False, f"{type(exc).__name__}: {exc}")
    print(f"\nFAIL: {len(fails)} arm(s) red")
    sys.exit(1)

FAKE = "pw_FAKE_d1e2f3"


def main():
    got = c.passwordless(f"postgresql://genesis:{FAKE}@127.0.0.1:5432/astryx")
    check("D1 passwordless keeps user/host/port/db, drops the password",
          got == "postgresql://genesis@127.0.0.1:5432/astryx", got)

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / ".env"
        f.write_text(f"ASTRYX_DSN=postgresql://genesis:{FAKE}@127.0.0.1:5432/astryx\n"
                     f"OPENAI_API_KEY=not-a-dsn\nGEO_DSN=postgresql://genesis:{FAKE}@localhost/geo\n")
        saved = c.DSN_FILES
        c.DSN_FILES = (f,)
        try:
            ds = c.dsns()
        finally:
            c.DSN_FILES = saved
    check("D2 dsns() derives every *_DSN, password-less, nothing else",
          sorted(k.split("/")[1] for k in ds) == ["ASTRYX_DSN", "GEO_DSN"]
          and not any(FAKE in v for v in ds.values()), str(ds))

    saved = (c.dsns, c.runners, c.probe)
    try:
        c.dsns = lambda: {"x/ASTRYX_DSN": "postgresql://genesis@127.0.0.1:5432/astryx"}
        c.runners = lambda: {"unit:a": {"HOME": "/h"}, "bare:env -i": {}}
        seen = []
        c.probe = lambda cmd, env: (seen.append(cmd) or
                                    ("genesis" if any("localhost" in x for x in cmd) else "FAIL:x"))
        rows = c.census()
        ctrl = [r for r in rows if r["dsn"].startswith("control:")]
        check("D3 every non-localhost DSN gets a localhost positive control",
              ctrl and all(r["host"] == "localhost" and r["ok"] for r in ctrl),
              str([(r['dsn'], r['host'], r['ok']) for r in ctrl][:3]))
        check("D4 bare env is reported, never required; real runners are required",
              all(not r["required"] for r in rows if r["runner"].startswith("bare:"))
              and all(r["required"] for r in rows if r["runner"].startswith("unit:")))
        with redirect_stdout(io.StringIO()):
            rc_fail = c.main([])
        c.probe = lambda cmd, env: "genesis"
        with redirect_stdout(io.StringIO()):
            rc_ok = c.main([])
        c.dsns = lambda: {}
        with redirect_stdout(io.StringIO()):
            rc_empty = c.main([])
        check("D5 exit 1 on a required failure, 0 when all pass, 1 on ZERO probes",
              (rc_fail, rc_ok, rc_empty) == (1, 0, 1), str((rc_fail, rc_ok, rc_empty)))
    finally:
        c.dsns, c.runners, c.probe = saved

    out = c.probe([sys.executable, "-c",
                   f"import sys; sys.stderr.write('fe_sendauth: no password supplied {FAKE}'); sys.exit(2)"],
                  {"PATH": "/usr/bin:/bin"})
    check("D6 probe returns an error CLASS, never the error text",
          out == "FAIL:no password supplied" and FAKE not in out, out)

    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    print("\nPASS: the S1c-0 census can't pass vacuously (plan-5497)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
