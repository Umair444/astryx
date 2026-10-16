#!/usr/bin/env python3
"""sqlguard enforce: a hashed absent ledger row says its own admitted date and reason, never a private path raw
(seed #56874, a3 #56878). On 10-16 "R-STALE a hashed (gitignored-origin) site" named nothing an owner could act on,
and tracing it to steward's outbound_stuck took a cross-report diff.

Hermetic: it drives the real enforce() on a fabricated report and ledger. The DSN is unreachable, so the state
and leak half reports NOT SEARCHED, and only the RED lines are read. privacy.ignored asks git about the repo's own
.gitignore. mutation_probe points ENFORCE_SRC at a mutant (tests/mutants_sqlguard_stale_reason.py)."""
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
esrc = os.environ.get("ENFORCE_SRC")
if esrc:
    spec = importlib.util.spec_from_file_location("enforce_under_test", esrc)
    enf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(enf)
else:
    from astryx.security.sqlguard import enforce as enf

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  — {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


RMAX = getattr(enf, "REASON_MAX", 160)          # main has no constant: the red control fails on arms, not a crash
DSN = "postgresql://nobody@127.0.0.1:1/x?connect_timeout=2"
CAN = enf.CANARY + "\x1fselect 1"
H = "sha256:" + "ab" * 32                         # a hashed (gitignored-origin) key that this run never sees
PLAIN = "src/astryx/core/gone.py::f\x1fselect 2"  # a tracked-origin key, also absent


def stale(rows):
    rep = {"sites": {CAN: {"rung": "RESPONSIVE"}}, "run_not_searched": [], "gates": {}, "covering": {},
           "extractors": {}, "blind": []}
    out = enf.enforce("/nonexistent", ledger={"rows": rows, "extractors": {}}, dsn=DSN, rep=rep)
    return [r for r in out["red"] if r.startswith("R-STALE")], out


print("a hashed absent row names its own ledger text:")
red, _ = stale({H: {"debt": "EXECUTED", "admitted": "2026-10-01", "reason": "steward's outbound_stuck body reads the wire"}})
check("(a) the R-STALE line carries the row's admitted date", len(red) == 1 and "admitted 2026-10-01" in red[0], red)
check("(a) …and its reason", red and "steward's outbound_stuck body reads the wire" in red[0], red)
check("(a) …and still says it is a hashed site", red and "a hashed (gitignored-origin) site" in red[0], red)

print("a reason never echoes a private path raw:")
PRIVATE = ["triggers/steward/outbound_stuck.py", "tier/owner/x.md", "memory/graph/ingest.py",
           "homes/medic/probes/x.py", "/home/umair/astryx/.env", "~/.ssh/id_ed25519"]
TRACKED = "src/astryx/core/pulse_run.py"
red, _ = stale({H: {"debt": "UNEXECUTED", "admitted": "2026-10-02",
                    "reason": f"beside {TRACKED}; moved from " + ", ".join(PRIVATE)}})
line = red[0] if red else ""
for p in PRIVATE:
    check(f"(b) {p.split('/')[0] or '/'}… is not in the output", p not in line, line)
check("(b) the triggers/ path's directory isn't either", "triggers/steward" not in line, line)
check("(b) each private path prints as <gitignored path>", line.count("<gitignored path>") == len(PRIVATE), line)
check("(b) a home-relative path leaves no stray ~ behind", "~<" not in line, line)
check("(b) control: a TRACKED path stays readable (the mask is not blanket)", TRACKED in line, line)

print("the cut runs after the mask:")
red, _ = stale({H: {"debt": "UNEXECUTED", "admitted": "2026-10-03",
                    "reason": "x" * (RMAX - 20) + " triggers/steward/outbound_stuck.py and more"}})
line = red[0] if red else ""
check("(c) a private path straddling the cut leaves no raw prefix", "triggers/" not in line and "trig" not in line, line)
check("(c) the reason is cut to REASON_MAX", line and len(line.split("admitted 2026-10-03: ", 1)[-1].split("]")[0]) <= RMAX, line)

print("a seed row and a tracked row:")
red, _ = stale({H: {"debt": "UNEXECUTED", "reason": "seed"}})
check("(d) a seed row says no reason was recorded, with its debt", red and "a seed row (UNEXECUTED), no reason recorded" in red[0], red)
check("(d) …and invents no admitted date", red and "admitted" not in red[0], red)
red, _ = stale({PLAIN: {"debt": "UNEXECUTED", "admitted": "2026-10-04", "reason": "tracked reason"}})
check("(e) a tracked absent row keeps its readable label, unchanged", red and red[0].startswith("R-STALE src/astryx/core/gone.py::f :: select 2: listed"), red)

print("identity is unchanged:")
_, out = stale({H: {"debt": "EXECUTED", "admitted": "2026-10-01", "reason": "anything"}})
want = hashlib.sha256(f"R-STALE absent {H}".encode()).hexdigest()[:24]
check("(f) the red id is still the key's alone, so new text never reads as a new finding", out.get("red_ids") == [want], out.get("red_ids"))

print("ALL PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
