#!/usr/bin/env python3
"""The sqlguard ledger: the org's KNOWN SQL-observation debt, machine-written (goal 4243, T3 + R4 + a3's C3).

    venv/bin/python -m nucleus.sqlguard.ledger seed <trace_dir>     # ONE-TIME seed, from a clean run's report

Every site below RESPONSIVE in the seed run becomes a row: its debt rung (UNEXECUTED / EXECUTED / FIXTURE-DDL)
or NOT-SEARCHED-AT-SEED, which is recorded, clocked, and never hidden. The header stamps what the seed was
generated FROM:
  commit        the committed tree's sha (a clean worktree, C3)
  estate_hash   sha256 over the sorted (path, sha256(content)) of the gitignored estate COPIED into that worktree
                (triggers/ sensors/ agents/ memory/ local.md). The estate isn't in git, so this is the only thing
                that lets anyone audit the seed against its inputs later (a3 #22254).
  counts        per rung.
B1 turns the rules on:
- RED on a NEW site below RESPONSIVE; RED on a listed row whose site has since climbed (forces shrink).
- The generator only ever SHRINKS; growth needs `--admit <site> <reason>`.
Graded DETECTION: a same-uid actor can hand-edit this file.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from nucleus.sqlguard import judge

REPO = judge.REPO
LEDGER = REPO / "nucleus" / "sqlguard" / "ledger.json"
ESTATE = ("triggers", "sensors", "agents", "memory", "local.md")


def estate_hash(root: Path = REPO) -> dict:
    files = []
    for name in ESTATE:
        p = root / name
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and "__pycache__" not in f.parts]
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: str(x.relative_to(root))):
        h.update(f"{f.relative_to(root)}\0{hashlib.sha256(f.read_bytes()).hexdigest()}\n".encode())
    return {"estate_hash": h.hexdigest(), "estate_files": len(files)}


def seed(trace_dir: str) -> dict:
    rep = judge.judge(trace_dir)
    if rep["run_not_searched"]:
        raise SystemExit(f"refusing to seed from a run that is NOT SEARCHED: {rep['run_not_searched']}")
    rows = {}
    for key, s in rep["sites"].items():
        if s["rung"] != "RESPONSIVE":
            rung = "NOT-SEARCHED-AT-SEED" if s["rung"] == "NOT SEARCHED" else s["rung"]
            rows[key] = {"debt": rung, "reason": "seed"}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                            text=True).stdout.strip()
    header = {"commit": commit, "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
              "run": os.environ.get("ASTRYX_SQLGUARD_RUN", ""), **estate_hash(),
              "sites_total": len(rep["sites"]), "debt_rows": len(rows), "counts": rep["counts"],
              "untraced_children": rep["untraced_children"]}
    doc = {"header": header, "covering": {k: v for k, v in rep["covering"].items() if v}, "rows": rows}
    LEDGER.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return header


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "seed":
        print(json.dumps(seed(sys.argv[2]), indent=1))
    else:
        print(__doc__.strip().splitlines()[2])
        sys.exit(2)
