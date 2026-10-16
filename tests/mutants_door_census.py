"""Mutants for triggers/steward/door_census.py (plan-9139 S1c-2). The body is gitignored: DOOR_CENSUS_STAGED names
a staged copy to probe before it is applied. The oracle is tests/test_door_census.py."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("DOOR_CENSUS_STAGED") or REPO / "triggers" / "steward" / "door_census.py")
ORACLE = REPO / "tests" / "test_door_census.py"
ENV = "DOOR_CENSUS_SRC"
MUTANTS = {
    "N1 dedup on the COUNTS, not the writer set (every count change re-fires)":
        ("    cur = sorted(writers)\n", "    cur = sorted(f\"{a}={n}\" for a, n in writers.items())\n"),
    "N2 warn-once: a standing set never re-nags":
        ("        if b > st.get(\"band\", -1):", "        if False:"),
    "N3 'reads 0' with nothing marked (the door not yet deployed reads as a pass)":
        ("    if not cur and not bypass and marked and not st.get(\"zero_said\"):",
         "    if not cur and not bypass and not st.get(\"zero_said\"):"),
    "N4 'reads 0' while a bypass stands":
        ("    if not cur and not bypass and marked and not st.get(\"zero_said\"):",
         "    if not cur and marked and not st.get(\"zero_said\"):"),
    "N5 'reads 0' said on every run":
        ("    if not cur and not bypass and marked and not st.get(\"zero_said\"):",
         "    if not cur and not bypass and marked:"),
    "N6 a released row counted as an unstamped writer":
        ("    writers = {r[\"from_agent\"]: int(r[\"n\"]) for r in rows if r[\"door\"] == \"org-unstamped\"}",
         "    writers = {r[\"from_agent\"]: int(r[\"n\"]) for r in rows if r[\"door\"]}"),
    "N7 the bypass measured from the FIRST mark on any channel (a deploy's restart gap reads as a bypass)":
        ("JOIN f ON split_part(m.delivery->>'handle', ':', 1) = f.ch", "JOIN f ON true"),
    "N8 a growing bypass waits for its band":
        ("        if bypass > st.get(\"bypass_n\", 0) or b > st.get(\"bypass_band\", -1):",
         "        if b > st.get(\"bypass_band\", -1):"),
}
