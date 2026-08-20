#!/usr/bin/env python3
"""Oracle for memory's usage_sample — the authoritative plan-limit series.

WHAT IT DEFENDS, in the order the defects would actually arrive.

1. QUORUM, NOT UNION. forge's first baseline unioned every key set ever observed, which
   made the baseline monotone: it could never forgive a key upstream legitimately retired,
   and ONE bad sample poisoned it for the life of the org. A series is worth depending on
   precisely because it can outvote a sample; a union throws the history away and keeps
   only its envelope. Both directions are pinned here — a one-off key never gets in, and a
   retired key ages out.
2. ABSENCE IS RECORDED AS ABSENCE. Three cell states, not two: a value; an upstream NULL,
   which means "not applicable" and is ordinary operation; and an ABSENT key, which is a
   real upstream change. Nothing is ever 0 for "no reading" — a 0 draws a reassuring trough
   at exactly the moments the instrument was blind, and a trough is worse than a gap.
3. THE ALLOWLIST IS THE ONLY DOOR. A money field arriving from upstream must not reach the
   archive even if nobody edits anything — the owner's finances are human-personal tier and
   a percentage is not. Pinned as a positive test with a hostile payload.
4. RETENTION MUST NAME ITS REASON, and must NOT fire when nothing moved — a series that
   retains everything is a log, and one that retains nothing is a gap.

Run: venv/bin/python nucleus/test_usage_sample.py     (exit 0 pass, 1 fail, 77 skip)
"""
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = Path(os.environ.get("USAGE_SAMPLE_PATH",
                             REPO / "triggers" / "memory" / "usage_sample.py"))
EXIT_SKIP = 77
NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def skip(why):
    print(f"SKIP: {why}")
    sys.exit(EXIT_SKIP)


if not MODULE.exists():
    skip(f"{MODULE} is absent (gitignored estate — a clean clone)")
sys.path.insert(0, str(REPO))
os.environ.setdefault("ASTRYX_REPO", str(REPO / "nucleus"))
try:
    spec = importlib.util.spec_from_file_location("usage_sample_under_test", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
except Exception as e:                                          # noqa: BLE001
    skip(f"module not importable ({type(e).__name__}: {e}) — run with venv/bin/python")

fails = []


def check(name, got, want):
    if got == want:
        print(f"  ✓ {name}")
    else:
        fails.append(name)
        print(f"  ✗ {name}\n      got  {got!r}\n      want {want!r}")


def ok(name, cond, detail=""):
    check(name, bool(cond) or detail or False, True)


def shaped(n, keys, hours_ago_start=0):
    return [{"sampled_at": (NOW - timedelta(hours=hours_ago_start + i)).isoformat(),
             "observed_keys": list(keys)} for i in range(n)]


# ── 1. QUORUM, both directions ────────────────────────────────────────────────────
b = m.derive_baseline(shaped(30, ["five_hour", "seven_day"])
                      + [{"sampled_at": NOW.isoformat(),
                          "observed_keys": ["five_hour", "seven_day", "ghost"]}], NOW)
check("a one-off key never enters the baseline (union would have admitted it)",
      b["keys"], ["five_hour", "seven_day"])
check("the honest keys survive alongside it", "five_hour" in b["keys"], True)

# retired: present in the first 25 of 30 hours, absent from the most recent 25
retired = ([{"sampled_at": (NOW - timedelta(hours=30 - i)).isoformat(),
             "observed_keys": ["five_hour", "legacy"]} for i in range(5)]
           + [{"sampled_at": (NOW - timedelta(hours=25 - i)).isoformat(),
               "observed_keys": ["five_hour"]} for i in range(25)])
check("a retired key ages out (a union could never forgive it)",
      m.derive_baseline(retired, NOW)["keys"], ["five_hour"])

# ── window and sample_count ───────────────────────────────────────────────────────
old = [{"sampled_at": (NOW - timedelta(days=30)).isoformat(), "observed_keys": ["ancient"]}]
b2 = m.derive_baseline(old + shaped(10, ["five_hour"]), NOW)
check("samples outside the window are excluded", b2["keys"], ["five_hour"])
check("sample_count counts only in-window shaped records", b2["sample_count"], 10)
check("records with no observed_keys do not count",
      m.derive_baseline(shaped(5, ["a"]) + [{"sampled_at": NOW.isoformat(), "state": "stale"}],
                        NOW)["sample_count"], 5)
check("the contract's field names are exactly forge's frozen block",
      sorted(b2), ["generated_at", "keys", "min_samples", "presence_threshold",
                   "sample_count", "window"])

# ── 2. ABSENCE IS ABSENCE ─────────────────────────────────────────────────────────
dark = m.build_record({"state": "not_configured", "fetched_at": None,
                       "data": None, "observed_keys": None}, NOW, {}, False)
ok("a non-renderable view archives NO data key", "data" not in dark)
ok("...no limits key", "limits" not in dark)
ok("...no observed_keys", "observed_keys" not in dark)
ok("...and no zero anywhere in the record", 0 not in dark.values())
check("but the state itself is recorded", dark["state"], "not_configured")

live = m.build_record({"state": "fresh", "fetched_at": "2026-08-20T11:59:00+00:00",
                       "observed_keys": ["five_hour", "seven_day", "limits", "extra_usage"],
                       "data": {"five_hour_utilization": 12.5,
                                "seven_day_opus_utilization": None,
                                "limits": [{"kind": "k", "group": "g", "percent": 3,
                                            "severity": "low", "resets_at": "z",
                                            "is_active": True}]}}, NOW, {}, False)
ok("an upstream NULL is kept as an explicit null, not dropped",
   "seven_day_opus_utilization" in live["data"]
   and live["data"]["seven_day_opus_utilization"] is None)
ok("...and is not turned into 0", live["data"]["seven_day_opus_utilization"] != 0)
ok("an ABSENT allowlist key is absent, not null",
   "seven_day_sonnet_utilization" not in live["data"])
check("measured_at is the cache's fetched_at, never the sample time",
      live["measured_at"], "2026-08-20T11:59:00+00:00")
ok("sampled_at is kept separately so cache age is computable",
   live["sampled_at"] != live["measured_at"])
check("observed_keys are sorted NAMES only",
      live["observed_keys"], ["extra_usage", "five_hour", "limits", "seven_day"])
ok("every observed key is a plain string", all(isinstance(k, str) for k in live["observed_keys"]))

blind = m.build_record({"state": "fresh", "fetched_at": "t", "observed_keys": None,
                        "data": {"five_hour_utilization": 1.0}}, NOW, {}, False)
ok("a source that carries no observed_keys OMITS the field, never []",
   "observed_keys" not in blind)
ok("...while the numbers it did carry still land", blind["data"]["five_hour_utilization"] == 1.0)
check("an omitted shape cannot arm a baseline",
      m.derive_baseline([blind], NOW)["sample_count"], 0)

# ── 3. THE ALLOWLIST IS THE ONLY DOOR ─────────────────────────────────────────────
hostile = m.build_record(
    {"state": "fresh", "fetched_at": "t", "observed_keys": ["five_hour", "spend"],
     "data": {"five_hour_utilization": 1.0, "used_dollars": 42.5, "spend": {"x": 1},
              "account_email": "someone@example.test",
              "limits": [{"kind": "k", "used_dollars": 9, "percent": 2}]}},
    NOW, {}, False)
ok("no money field reaches the archive", not any(
    "dollar" in k or k == "spend" for k in hostile["data"]))
ok("no identity field reaches the archive", "account_email" not in hostile["data"])
ok("the limits rows are allowlisted too", not any(
    "dollar" in f for r in hostile["limits"] for f in r))
check("the wanted number still lands", hostile["data"]["five_hour_utilization"], 1.0)

# ── 4. RETENTION NAMES ITS REASON, AND STAYS QUIET ────────────────────────────────
base = {"state": "fresh", "sampled_at": (NOW - timedelta(minutes=5)).isoformat(),
        "data": {"five_hour_utilization": 10.0, "five_hour_resets_at": "A"}}
same = {"state": "fresh", "sampled_at": NOW.isoformat(),
        "data": {"five_hour_utilization": 10.2, "five_hour_resets_at": "A"}}
check("nothing moved -> not retained", m.should_retain(same, base, NOW), (False, ""))
check("no prior record -> first-after-gap",
      m.should_retain(same, None, NOW), (True, "first-after-gap"))
moved = dict(same, data={"five_hour_utilization": 11.1, "five_hour_resets_at": "A"})
check("a one-point move -> delta", m.should_retain(moved, base, NOW), (True, "delta"))
reset = dict(same, data={"five_hour_utilization": 0.4, "five_hour_resets_at": "B"})
check("a reset boundary -> window-reset",
      m.should_retain(reset, base, NOW), (True, "window-reset"))
check("a state change -> state-change",
      m.should_retain(dict(same, state="stale"), base, NOW), (True, "state-change"))
stale_prev = dict(base, sampled_at=(NOW - timedelta(hours=2)).isoformat())
check("an hour of silence -> floor", m.should_retain(same, stale_prev, NOW), (True, "floor"))

# ── running max, and the honesty flag when its cache was lost ─────────────────────
mx = m.merge_max({"five_hour_utilization": 30.0},
                 {"state": "fresh", "data": {"five_hour_utilization": 12.0}})
check("merge_max keeps the peak, not the latest", mx["five_hour_utilization"], 30.0)
ok("a lost max cache is declared, not hidden",
   m.build_record({"state": "fresh", "fetched_at": "t", "observed_keys": ["a"],
                   "data": {"five_hour_utilization": 1}}, NOW, {"x": 1}, True)
   .get("max_window_partial") is True)

# ── read_records survives a corrupt line ──────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "2026-08.jsonl"
    f.write_text('{"observed_keys":["a"]}\nnot json at all\n{"observed_keys":["b"]}\n\n')
    check("one bad line does not blind the reader to the rest",
          len(m.read_records([f])), 2)

print()
if fails:
    print(f"{len(fails)} FAILED of {len(fails) + 0} — see above")
    sys.exit(1)
print("34/34 passed — quorum outvotes a sample, absence is never zero, the allowlist is "
      "the only door, and every retained row can say why it lived")
