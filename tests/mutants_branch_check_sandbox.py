"""Authored mutants for nucleus/branch_check_sandbox.py (plan-4918 R3/R5), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_branch_check_sandbox.py

One per property: each probe's firing and each vacuity refusal. NOT authored: removing ONE of the two HOME fences
(HOME = run tmp; the real home never mounted). Either alone keeps ~/.pgpass out, so each single removal is an
equivalent mutant BY CONSTRUCTION; the (i) RED arm removes them (plus the network) and fires. Also not authored:
--unshare-pid (a3's nit): hiding the host process list has no in-sandbox observable the probes use today.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "branch_check_sandbox.py"
ORACLE = REPO / "tests" / "test_branch_check_sandbox.py"
ENV = "BRANCH_CHECK_SANDBOX_SRC"

MUTANTS = {
    "S2 the (i) reach result is ignored":
        ("    if inside[\"pgpass_reach\"][\"reached\"]:\n", "    if False:\n"),
    "S3 the (iv) live .env result is ignored":
        ("    if inside[\"live_env_readable\"]:\n", "    if False:\n"),
    "S4 the (vi) foreign-connect result is ignored":
        ("    if inside[\"foreign_connect\"]:\n", "    if False:\n"),
    "S5 (i) vacuity not checked (a pgpass that authenticates nowhere passes)":
        ("    if not outside[\"pgpass_reach\"][\"reached\"]:\n", "    if False:\n"),
    "S6 (vi) vacuity not checked (NOTIFY broken everywhere passes)":
        ("    if not inside[\"own_notify\"]:\n", "    if False:\n"),
    "S8 the host network is SHARED (geoloc's location fixes reachable from a branch's test)":
        ("          (\"--share-net\" if share_net else \"--unshare-net\"),", "          \"--share-net\","),
    "S9 the (vii) listener result is ignored":
        ("    if inside.get(\"listeners_reached\"):\n", "    if False:\n"),
    "S10 (vii) vacuity not checked":
        ("    if not outside.get(\"listeners_reached\"):\n", "    if False:\n"),
    "S7 (v) judged by a WRITE to a path that may be bwrap's synthetic dir":
        ("    res[\"live_repo_writable\"] = res[\"live_repo_visible\"] and os.access(lr / \"nucleus\", os.W_OK)",
         "    res[\"live_repo_writable\"] = os.access(lr, os.W_OK)"),
}
