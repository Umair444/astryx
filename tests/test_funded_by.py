#!/usr/bin/env python3
"""Oracle for the 3499 economy-integrity CORE — funded_by ATTRIBUTION (naming, NOT prevention).

The economy's W is born when goals.done_at is stamped (econ.py). 3499's buildable-now core does
NOT try to PREVENT a forged stamp (a genesis superuser forges any in-DB gate — ratified
DO-NOT-BUILD); it makes the funding of each W-mint ATTRIBUTABLE and labels the boundary honestly.

This proves, on a throwaway postgres (never the org's own):
  MIGRATION   · schema.sql adds goals.funded_by + the funded_by_watermark, and is IDEMPOTENT
                (re-applying it never errors, never moves the watermark, never dups the column).
  WATERMARK   · the legacy sentinel is max(goals.id) at migration → on a FRESH clone (empty
                goals) it is 0 (nothing is legacy); it separates legacy-NULL from new-unfunded.
  W-BIRTH     · the →done/shipped transition STILL stamps done_at — the funder-naming must not
                break the mint (this is seed's live-probe invariant, proven hermetically here).
  NAMING      · a NEW goal (id > watermark) shipped with no funder is recorded '(unfunded)';
                a funded new goal keeps its funder; a LEGACY goal (id <= watermark) stays NULL,
                not revised. All three still stamp done_at.
  NOT-PREVENTION · the trigger never REJECTS a transition (a superuser is unstoppable here) — a
                direct done_at write and an unfunded ship both succeed; the goal is NAMED, not
                blocked. The honesty is in the label, checked by test_funded_by_labeling parity.

Throwaway DB only (role must CREATE DATABASE, else SKIP 77). Run by check.sh; RED-first against
the pre-migration schema (funded_by absent), GREEN after.
"""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXIT_SKIP = 77


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(EXIT_SKIP)


try:
    import psycopg
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — needs the org runtime")

SCHEMA = REPO / "nucleus" / "schema.sql"
if not SCHEMA.exists():
    skip("nucleus/schema.sql absent")

fails: list[str] = []


def want(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        fails.append(label)


def dsn():
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"].strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_DSN="):
                return line[len("ASTRYX_DSN="):].strip().strip('"').strip("'")
    return None


ADMIN_DSN = dsn()
if not ADMIN_DSN:
    skip("no ASTRYX_DSN — no substrate")
try:
    admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
except Exception as e:                                              # noqa: BLE001
    skip(f"database unreachable ({type(e).__name__})")
row = admin.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
if not row or not row[0]:
    admin.close()
    skip("role cannot CREATE DATABASE — a throwaway is the only safe substrate")

PROBE_DB = f"astryx_fundedby_{os.getpid()}"
PROBE_DSN = re.sub(r"/[^/?]+(\?|$)", f"/{PROBE_DB}\\1", ADMIN_DSN, count=1)
if PROBE_DB not in PROBE_DSN:
    admin.close()
    skip("could not derive a throwaway DSN")

SCHEMA_SQL = SCHEMA.read_text()


def cleanup():
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    except Exception:                                              # noqa: BLE001
        pass
    admin.close()


def col_exists(conn, table, col):
    return conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
        (table, col)).fetchone() is not None


def ship(conn, gid):
    """Transition a goal to done (the W-birth path) and return (done_at, funded_by)."""
    conn.execute("UPDATE goals SET state='done' WHERE id=%s", (gid,))
    return conn.execute("SELECT done_at, funded_by FROM goals WHERE id=%s", (gid,)).fetchone()


try:
    admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    admin.execute(f'CREATE DATABASE "{PROBE_DB}"')

    # ── MIGRATION + idempotency: apply schema.sql TWICE, on an empty DB (fresh-clone path) ──
    with psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5) as sc:
        sc.execute(SCHEMA_SQL)
        errored = False
        try:
            sc.execute(SCHEMA_SQL)                                  # re-run: must be idempotent
        except Exception as e:                                      # noqa: BLE001
            errored = True
            print(f"    (second apply raised: {type(e).__name__}: {e})")

    with psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5) as conn:
        want("MIGRATION: goals.funded_by column exists", col_exists(conn, "goals", "funded_by"))
        want("MIGRATION: re-applying schema.sql is idempotent (no error)", not errored)
        wm_rows = conn.execute("SELECT count(*), coalesce(max(legacy_max_id),-1) FROM funded_by_watermark").fetchone()
        want("WATERMARK: exactly one watermark row after double-apply", wm_rows[0] == 1)
        want("WATERMARK: fresh clone (empty goals) → watermark 0 (nothing legacy)", wm_rows[1] == 0)

        # ── NAMING + W-BIRTH: control the watermark, straddle it with legacy & new goals ──
        # simulate a populated migration: watermark = 100, so id<=100 is legacy, id>100 is new.
        conn.execute("UPDATE funded_by_watermark SET legacy_max_id = 100")

        def mkgoal(gid, funder=None):
            conn.execute("INSERT INTO goals (id,title,owner,state,budget_tokens) "
                         "VALUES (%s,%s,'forge','active',1000)", (gid, f"g{gid}"))
            if funder is not None:
                conn.execute("UPDATE goals SET funded_by=%s WHERE id=%s", (funder, gid))

        mkgoal(50)                 # LEGACY (<=100), no funder
        mkgoal(150)                # NEW (>100), no funder
        mkgoal(160, "steward")     # NEW (>100), funded

        d50, f50 = ship(conn, 50)
        d150, f150 = ship(conn, 150)
        d160, f160 = ship(conn, 160)

        want("W-BIRTH: legacy goal ship stamps done_at", d50 is not None)
        want("W-BIRTH: new-unfunded goal ship stamps done_at", d150 is not None)
        want("W-BIRTH: funded goal ship stamps done_at", d160 is not None)
        want("NAMING: LEGACY goal (id<=watermark) stays NULL, not revised", f50 is None)
        want("NAMING: NEW unfunded goal recorded '(unfunded)' at W-birth", f150 == "(unfunded)")
        want("NAMING: funded goal keeps its attributed funder", f160 == "steward")

        # ── NOT-PREVENTION: the trigger names, it never REJECTS the transition ──
        mkgoal(170)
        raised = False
        try:
            ship(conn, 170)
        except Exception:                                          # noqa: BLE001
            raised = True
        want("NOT-PREVENTION: an unfunded ship is NAMED, never blocked", not raised)
        # a direct done_at write (the second forgeable path) is not prevented either
        conn.execute("INSERT INTO goals (id,title,owner,state,budget_tokens) VALUES (200,'g200','forge','active',1000)")
        blocked = False
        try:
            conn.execute("UPDATE goals SET done_at=now() WHERE id=200")
        except Exception:                                          # noqa: BLE001
            blocked = True
        want("NOT-PREVENTION: a direct done_at write still succeeds (attribution, not a gate)", not blocked)
finally:
    cleanup()

print()
if fails:
    print(f"test_funded_by: {len(fails)} FAIL — {fails}")
    sys.exit(1)
print("test_funded_by: ALL PASS — funded_by names every W-mint's funder; W-birth intact; nothing prevented")
sys.exit(0)
