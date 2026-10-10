#!/usr/bin/env python3
"""astryx · turns retention — old turns keep their words, not their pictures (owner, 2026-10-10).

Since hooks/step.py's strip_pixels() (a3 #42088 L1) no NEW turn stores an image: each image block is
written as {"type": "image_omitted", "sha256", "bytes"}. The turns written before it still carry
base64 screenshots (~34 MB measured on 10-10). The owner: "it's fine, this is a private server —
add retention to save space". So this applies the SAME strip_pixels to turns older than --days,
in place: text, tool calls, token counts and usage stay; only image bytes (and laptop-screen tool
output, and typed text) go.

    venv/bin/python -m nucleus.turns_retention [--days 7] [--dry-run] [--limit N]

Idempotent: a stripped turn has no image block left, so it's never selected again. Run nightly by
nucleus/backup.sh BEFORE its pg_dump, so the dump shrinks with it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _strip():
    spec = importlib.util.spec_from_file_location("astryx_step_hook", REPO / "hooks" / "step.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.strip_pixels


def dsn() -> str:
    v = os.environ.get("ASTRYX_DSN")
    if v:
        return v
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("ASTRYX_DSN="):
            return line.split("=", 1)[1]
    raise SystemExit("no ASTRYX_DSN")


def run(conn, days: int, dry: bool = False, limit: int = 500) -> dict:
    """Strip image bytes from turns older than `days`. Returns counts; commits unless dry."""
    strip = _strip()
    rows = conn.execute(
        """SELECT id, raw_payload FROM turns
           WHERE ended_at < now() - make_interval(days => %s)
             AND raw_payload::text LIKE '%%"type": "image"%%'
           ORDER BY id LIMIT %s""", (days, limit)).fetchall()
    out = {"turns": 0, "bytes_before": 0, "bytes_after": 0}
    for tid, payload in rows:
        before = json.dumps(payload)
        new = {**payload, "messages": strip(payload.get("messages", []))}
        after = json.dumps(new)
        if after == before:
            continue
        out["turns"] += 1
        out["bytes_before"] += len(before)
        out["bytes_after"] += len(after)
        if not dry:
            from psycopg.types.json import Jsonb
            conn.execute("UPDATE turns SET raw_payload = %s WHERE id = %s", (Jsonb(new), tid))
    if not dry:
        conn.commit()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=500)
    a = ap.parse_args(argv)
    import psycopg
    with psycopg.connect(dsn()) as conn:
        r = run(conn, a.days, a.dry_run, a.limit)
    saved = r["bytes_before"] - r["bytes_after"]
    print(f"turns retention ({'dry run' if a.dry_run else 'applied'}, older than {a.days}d): "
          f"{r['turns']} turn(s), {saved / 1e6:.1f} MB of image bytes "
          f"{'would be' if a.dry_run else ''} removed".replace("  ", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
