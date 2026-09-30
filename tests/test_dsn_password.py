"""Oracle for nucleus/dsn_password.py, the S1c switch (plan-5497). Hermetic: fixture files only.

Each arm can ALONE go red:
  P1 strip REFUSES, writing nothing, when ~/.pgpass has no entry for the DSN's host LITERALLY (a
     localhost entry does not cover 127.0.0.1: BC-a).
  P2 strip REFUSES when the matching entry holds a DIFFERENT password (the stripped DSN would lock
     its consumer out). All or nothing: one refusal writes no file at all.
  P3 strip --apply: every URL_CONFIG DSN loses only its password (user, host, port, db kept), every
     other line is byte-identical, the file mode is kept, and the output names keys, never values.
     Without --apply nothing is written.
  P4 restore --apply rebuilds each DSN from ~/.pgpass: strip then restore is byte-identical.
  P5 a SYMLINKED target: the real file is rewritten and the link stays a link.
  P6 only LIVE holders (fate keep) are switched: a retired copy is left alone.
  P7 only URL_CONFIG keys: an unclassified URL carrying a password is not touched.

Run: venv/bin/python tests/test_dsn_password.py
"""
import io
import sys
import tempfile
import urllib.parse
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
    from nucleus import dsn_password as dp
    from nucleus import secretset as ss
except Exception as exc:                                    # noqa: BLE001
    check("nucleus.dsn_password imports", False, f"{type(exc).__name__}: {exc}")
    print(f"\nFAIL: {len(fails)} arm(s) red")
    sys.exit(1)

PW = "pw:FAKE/9+x"                                           # needs URL-encoding AND pgpass escaping
ENC = urllib.parse.quote(PW, safe="")


def run(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = dp.main(list(argv))
    return rc, buf.getvalue()


def setup(tmp: Path, pg: str):
    env = tmp / ".env"
    env.write_text(f"# header\nASTRYX_DSN=postgresql://genesis:{ENC}@127.0.0.1:5432/astryx\n"
                   f"OPENAI_API_KEY=tok_FAKE_123456789\n"
                   f"OTHER_URL=https://u:{ENC}@example.invalid/x\n")
    env.chmod(0o600)
    real = tmp / "real_geo.env"
    real.write_text(f"GEOLOC_TOKEN=gt_FAKE_0987654321\nGEOLOC_DSN=postgresql://genesis:{ENC}@127.0.0.1:5432/geo\n")
    (tmp / "cfg").mkdir(exist_ok=True)
    link = tmp / "cfg" / "geoloc.env"
    if not link.exists():
        link.symlink_to(real)
    dead = tmp / "dead.env"
    dead.write_text(f"OBSERVER_DSN=postgresql://genesis:{ENC}@127.0.0.1:5432/genesis\n")
    (tmp / "pgpass").write_text(pg)
    manifest = {"holders": [{"path": str(link), "fate": "keep"}, {"path": str(dead), "fate": "retire"}],
                "expiring": [], "scan_roots": []}
    ss.ENV_FILE = env
    ss.holders = lambda path=None: manifest
    return env, real, link, dead


def esc(v):
    return v.replace("\\", "\\\\").replace(":", "\\:")


def main():
    saved = (ss.ENV_FILE, ss.holders)
    try:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            env, real, link, dead = setup(tmp, f"localhost:5432:*:genesis:{esc(PW)}\n")
            before = {p: p.read_bytes() for p in (env, real, dead)}
            rc, out = run("strip", "--apply", "--pgpass", str(tmp / "pgpass"))
            check("P1 strip REFUSES without a literal-host pgpass entry, writing nothing",
                  rc == 77 and "BC-a" in out and all(p.read_bytes() == b for p, b in before.items()),
                  f"rc={rc}")

            (tmp / "pgpass").write_text(f"127.0.0.1:5432:*:genesis:{esc('other_FAKE_pw')}\n")
            rc, out = run("strip", "--apply", "--pgpass", str(tmp / "pgpass"))
            check("P2 a DIFFERENT pgpass password REFUSES, all or nothing",
                  rc == 77 and "DIFFERENT" in out and all(p.read_bytes() == b for p, b in before.items()))

            (tmp / "pgpass").write_text(f"localhost:5432:*:genesis:{esc(PW)}\n"
                                        f"127.0.0.1:5432:*:genesis:{esc(PW)}\n")
            rc, out = run("strip", "--pgpass", str(tmp / "pgpass"))
            check("P3a without --apply nothing is written",
                  rc == 0 and "would strip" in out and all(p.read_bytes() == b for p, b in before.items()))
            rc, out = run("strip", "--apply", "--pgpass", str(tmp / "pgpass"))
            e = env.read_text()
            check("P3 --apply strips only the password; other lines byte-identical; mode kept",
                  rc == 0 and "ASTRYX_DSN=postgresql://genesis@127.0.0.1:5432/astryx\n" in e
                  and e.startswith("# header\n") and "OPENAI_API_KEY=tok_FAKE_123456789\n" in e
                  and oct(env.stat().st_mode & 0o777) == "0o600", e)
            check("P3b the output names keys, never a value",
                  PW not in out and ENC not in out and "ASTRYX_DSN" in out)
            check("P5 a SYMLINKED target: the real file is rewritten, the link stays a link",
                  link.is_symlink() and "GEOLOC_DSN=postgresql://genesis@127.0.0.1:5432/geo" in real.read_text()
                  and real.read_text().startswith("GEOLOC_TOKEN=gt_FAKE_0987654321\n"))
            check("P6 a RETIRED holder is not switched", dead.read_bytes() == before[dead])
            check("P7 an unclassified URL with a password is not touched", f"OTHER_URL=https://u:{ENC}@" in e)

            rc, out = run("restore", "--apply", "--pgpass", str(tmp / "pgpass"))
            check("P4 strip then restore is byte-identical (rebuilt from pgpass, no copy kept)",
                  rc == 0 and env.read_bytes() == before[env] and real.read_bytes() == before[real],
                  out[-200:])
    finally:
        ss.ENV_FILE, ss.holders = saved
    if fails:
        print(f"\nFAIL: {len(fails)} arm(s) red")
        return 1
    print("\nPASS: the S1c switch strips and restores DSN passwords with no copy (plan-5497)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
