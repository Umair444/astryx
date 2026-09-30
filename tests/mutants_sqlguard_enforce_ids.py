"""Mutants for enforce.py's RED identities (plan-4918 D4, a3 C4). The oracle is the orchestrator oracle, the
consumer of red.json: it drives the real enforce() on a fabricated report and compares identities."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "nucleus" / "sqlguard" / "enforce.py"
ORACLE = REPO / "tests" / "test_branch_check.py"
ENV = "ENFORCE_SRC"
MUTANTS = {
    "E1 an R-BLIND is keyed by its LINE too (unchanged code shifted by a line reads as a new finding)":
        ("        R(f\"R-BLIND {path}::{b['frame'][1]}::{b['t']}\",",
         "        R(f\"R-BLIND {path}::{b['frame'][1]}::{b['frame'][2]}::{b['t']}\","),
    "E2 an R-BLIND is keyed without its SQL (two different statements in one function collapse to one)":
        ("        R(f\"R-BLIND {path}::{b['frame'][1]}::{b['t']}\",", "        R(f\"R-BLIND {path}::{b['frame'][1]}\","),
}
