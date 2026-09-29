#!/usr/bin/env python3
"""The sqlguard ledger: the org's KNOWN SQL-observation debt, machine-written (goal 4243, T3 + R4 + a3's C3).

    venv/bin/python -m nucleus.sqlguard.ledger seed <trace_dir>     # ONE-TIME seed, from a clean run's report
    venv/bin/python -m nucleus.sqlguard.ledger admit <trace_dir> <site> '<reason>'   # the ONLY growth path
    venv/bin/python -m nucleus.sqlguard.ledger shrink <trace_dir>   # settle R-STALE: drop, or re-key a moved site

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
from nucleus.sqlguard import privacy
from nucleus.sqlguard.privacy import ledger_key, text_key

REPO = judge.REPO
LEDGER = REPO / "nucleus" / "sqlguard" / "ledger.json"
# The estate is DERIVED from git (everything gitignored that the real tree holds), never hand-listed. My first
# seed hand-listed it and missed bridges/geoloc.py, mcp/geoloc/, harness/ and more (the glob-domain trap, in my
# own tooling). Only BULK NON-CODE is excluded, declared here. Anything it misses reads as a loud R-NEW in the
# real tree, never a silent absorption.
ESTATE_EXCLUDE = ("venv/", ".venv/", "homes/", "node_modules/", "backups/", "media/", "observatory/web/dist/",
                  ".env")


def estate_paths(source_root: Path = REPO) -> list:
    """Gitignored paths in the SOURCE tree (the real one: a worktree's git sees none of them)."""
    out = subprocess.run(["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
                         cwd=source_root, capture_output=True, text=True).stdout.split("\n")
    return sorted(p for p in out if p and "__pycache__" not in p and not p.endswith(".pyc")
                  and not any(p == e or p.startswith(e) or f"/{e}" in f"/{p}" for e in ESTATE_EXCLUDE))


def estate_hash(root: Path = REPO, source_root: Path = None) -> dict:
    files = []
    for name in estate_paths(source_root or root):
        p = root / name
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and "__pycache__" not in f.parts
                      and not f.name.endswith(".pyc")]
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
            rows[ledger_key(key)] = {"debt": rung, "reason": "seed", "tk": text_key(key)}     # P1: a gitignored origin → a digest
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                            text=True).stdout.strip()
    header = {"commit": commit, "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
              "run": (Path(trace_dir) / "run_id").read_text().strip() if (Path(trace_dir) / "run_id").exists() else "",
              **estate_hash(REPO, Path(os.environ.get("ASTRYX_SQLGUARD_ESTATE_SRC") or REPO)),
              "sites_total": len(rep["sites"]), "debt_rows": len(rows), "counts": rep["counts"],
              "untraced_children": rep["untraced_children"]}
    # EX1/EX2: the extractors DERIVED from this run are listed, each with its gates, a reason, an observable TRIP
    # and a listed-since date (the clock). The econ oracles wait on plan-4227 (seed #22133), and the rest migrate
    # in B1.
    today = datetime.date.today().isoformat()
    extractors = {f: {"gates": gs, "listed_since": today,
                      "reason": "seed: builds an UNSTAMPED fixture; migrate to nucleus/sqlguard/fixture.py",
                      # P2: a MACHINE-CHECKABLE trip that enforce.py evaluates, never prose. The econ oracles
                      # wait on goal 4227 (seed #22133); the rest migrate within this guard's own goal.
                      "trip": {"goal": 4227 if "econ" in f else 4243, "state": "done"}}
                  for f, gs in sorted(rep["extractors"].items())}
    header["extractors_listed"] = len(extractors)
    doc = {"header": header, "covering": {ledger_key(k): v for k, v in rep["covering"].items() if v}, "rows": rows,
           "extractors": extractors}
    if privacy.ERRORS:                       # a3 D-P: never write while the privacy authority couldn't answer
        raise SystemExit(f"refusing to write the ledger: privacy classification failed "
                         f"({len(privacy.ERRORS)}): {privacy.ERRORS[:3]}")
    LEDGER.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return header


def admit(trace_dir: str, site: str, reason: str, path: Path = None) -> str:
    """The ONLY growth path (R4). `site` is the handle an R-NEW line prints: a sha256 digest for a gitignored
    origin, else `path::qualname :: text`. The site must exist in THIS run's report (report.json, written by
    enforce) and be below RESPONSIVE, so a typo or an already-healthy site can't be admitted. The reason is
    stored with the date and printed on every enforce run until the row shrinks."""
    path = path or LEDGER
    reason = (reason or "").strip()
    if not reason or reason == "seed":
        raise SystemExit("refusing: an admit needs a real reason (it is printed every run)")
    rep = json.loads((Path(trace_dir) / "report.json").read_text())
    hits = [k for k in rep["sites"] if site in (k, ledger_key(k), privacy.label(k))]
    if privacy.ERRORS:
        raise SystemExit(f"refusing: privacy classification failed ({len(privacy.ERRORS)})")
    if len(hits) != 1:
        raise SystemExit(f"refusing: {len(hits)} sites match {site!r} in {trace_dir}/report.json (need exactly 1)")
    key = hits[0]
    rung = rep["sites"][key]["rung"]
    if rung == "RESPONSIVE":
        raise SystemExit("refusing: that site is RESPONSIVE, so there is no debt to admit")
    doc = json.loads(path.read_text())
    lk = ledger_key(key)
    if lk in doc["rows"]:
        raise SystemExit("refusing: already listed")
    doc["rows"][lk] = {"debt": "NOT-SEARCHED-AT-ADMIT" if rung == "NOT SEARCHED" else rung, "reason": reason,
                       "admitted": datetime.date.today().isoformat(), "tk": text_key(key)}
    if rep.get("covering", {}).get(key):
        doc.setdefault("covering", {})[lk] = rep["covering"][key]
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return lk


def shrink(trace_dir: str, path: Path = None) -> tuple:
    """Settle enforce's R-STALE set against a run's report. A row whose site climbed to RESPONSIVE is dropped.
    A row whose key is absent is MOVED when exactly one unledgered live site has its text_key (same file, same
    SQL: a rename re-keyed it), keeping its debt, reason and dates (a3 #22780); otherwise it is dropped. Rows
    whose site is live get their tk backfilled, so hashed rows can be followed next time.
    Never grows the debt. Refuses a run-level NOT SEARCHED run (with triggers/ absent every gitignored site would
    read as vanished) and privacy errors. Returns (removed, moved), shown hashed for gitignored origin."""
    path = path or LEDGER
    rep = json.loads((Path(trace_dir) / "report.json").read_text())
    if privacy.ERRORS:
        raise SystemExit(f"refusing: privacy classification failed ({len(privacy.ERRORS)})")
    if rep.get("run_not_searched"):
        raise SystemExit(f"refusing: the run was NOT SEARCHED at run level {rep['run_not_searched']}, so absence "
                         f"there proves nothing")
    doc = json.loads(path.read_text())
    rows, cov = doc["rows"], doc.setdefault("covering", {})
    live = {ledger_key(k): k for k in rep["sites"]}
    by_tk = {}
    for lk, k in live.items():
        by_tk.setdefault(text_key(k), []).append(lk)
        if lk in rows:
            rows[lk].setdefault("tk", text_key(k))
    show = lambda lk: lk if lk.startswith("sha256:") else privacy.label(lk)
    removed, moved = [], []
    for lk in list(rows):
        if lk in live:
            if rep["sites"][live[lk]]["rung"] == "RESPONSIVE":
                del rows[lk]
                cov.pop(lk, None)
                removed.append(show(lk))
            continue
        tk = rows[lk].get("tk") or (None if lk.startswith("sha256:") else text_key(lk))
        cands = [c for c in by_tk.get(tk, []) if c not in rows] if tk else []
        row = rows.pop(lk)
        old_cov = cov.pop(lk, None)
        if len(cands) == 1 and rep["sites"][live[cands[0]]]["rung"] != "RESPONSIVE":
            new = cands[0]
            rows[new] = {**row, "tk": tk}
            if rep.get("covering", {}).get(live[new]) or old_cov:
                cov[new] = rep.get("covering", {}).get(live[new]) or old_cov
            moved.append(f"{show(lk)} -> {show(new)}")
        else:
            removed.append(show(lk))
    doc["header"]["debt_rows"] = len(rows)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return removed, moved


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "seed":
        print(json.dumps(seed(sys.argv[2]), indent=1))
    elif len(sys.argv) == 3 and sys.argv[1] == "shrink":
        gone, moved = shrink(sys.argv[2])
        print(f"shrank {len(gone)} row(s), re-keyed {len(moved)}" + "".join(f"\n  - {g}" for g in gone)
              + "".join(f"\n  ~ {m}" for m in moved))
    elif len(sys.argv) == 5 and sys.argv[1] == "admit":
        print(f"admitted {admit(sys.argv[2], sys.argv[3], sys.argv[4])}")
    else:
        print(__doc__.strip().splitlines()[2])
        sys.exit(2)
