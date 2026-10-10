#!/usr/bin/env python3
"""test_turns_retention — old turns lose image bytes, keep everything else (owner 10-10 retention).

On a throwaway fixture DB (schema.sql applied whole):
  (a) an OLD turn with an image → the image becomes image_omitted{sha256, bytes}; its text stays
  (b) a RECENT turn with an image → untouched (inside the retention window)
  (c) an OLD turn with no image → untouched, and never selected
  (d) a second run changes nothing (idempotent: 0 turns)
  (e) --dry-run reports without writing
NOT RUN (77) without a reachable admin DSN.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402
from nucleus import turns_retention as tr  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    fails += 0 if ok else 1


def payload(with_image: bool):
    content = [{"type": "text", "text": "kept words"}]
    if with_image:
        content.append({"type": "image", "source": {"type": "base64", "data": "QUJDREVG" * 50}})
    return {"messages": [{"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "r1", "content": content}]}}], "usage": {"tokens_in": 7}}


try:
    with fixture_db() as fx:
        import psycopg
        from psycopg.types.json import Jsonb
        with psycopg.connect(fx["dsn"]) as c:
            ids = {}
            for name, age, img in [("old_img", "30 days", True), ("new_img", "1 day", True),
                                   ("old_txt", "30 days", False)]:
                ids[name] = c.execute(
                    "INSERT INTO turns (agent, ended_at, raw_payload) VALUES ('t', now() - %s::interval, %s) "
                    "RETURNING id", (age, Jsonb(payload(img)))).fetchone()[0]
            c.commit()
            dry = tr.run(c, 7, dry=True)
            still = c.execute("SELECT raw_payload::text FROM turns WHERE id=%s", (ids["old_img"],)).fetchone()[0]
            arm("(e) a dry run reports 1 turn and writes nothing", dry["turns"] == 1 and "QUJD" in still, dry)
            r = tr.run(c, 7)
            get = lambda k: json.dumps(c.execute("SELECT raw_payload FROM turns WHERE id=%s", (ids[k],)).fetchone()[0])  # noqa: E731
            old = get("old_img")
            arm("(a) the old turn's image is gone, replaced by image_omitted with its sha",
                "QUJD" not in old and "image_omitted" in old and '"sha256"' in old, old[:200])
            arm("(a) its words and usage stay", "kept words" in old and '"tokens_in": 7' in old)
            arm("(b) a recent turn's image is untouched (inside the window)", "QUJD" in get("new_img"))
            arm("(c) an old turn with no image is untouched",
                json.loads(get("old_txt")) == payload(False))
            arm("(a) exactly one turn was changed", r["turns"] == 1, r)
            arm("(d) a second run changes nothing", tr.run(c, 7)["turns"] == 0)
except FixtureUnavailable as e:
    print(f"NOT RUN: {e}")
    sys.exit(77)
if fails:
    print(f"FAIL ({fails})")
    sys.exit(1)
print("PASS")
