#!/usr/bin/env python3
"""rekey — does a range's SQL text change come WITH its ledger move? A static pre-merge answer (a3 night-review 10-09).

    venv/bin/python -m astryx.security.sqlguard.rekey <base> <head> [--repo <path>]

The ledger keys a row on a site's NORMALIZED TEXT, so ANY edit to a listed SQL literal (even `like ?` → `~ ?`) leaves
the old row R-STALE and the new site R-NEW, and main's estate check goes RED on merge. That backed out plan-4918 twice
(seed #33150, #34264), and both reviews had PASSed from extracts, where the estate gate cannot run. This answers the
question from the two TRACKED trees alone, in under a minute, with no database and no live state.

Each revision is `git archive`d and inventoried by HEAD's src/astryx/security/sqlguard/inventory.py + normalizer, BOTH trees.
The question is "what will main's run, with HEAD's code, read?", so HEAD's normalizer is the only judge and base is
there only to assign blame. Judging base by ITS OWN normalizer gave a FALSE CLEAN exactly when a range changes
norm(): every key moves, a deleted listed site's base key sits in the OLD key space, and it read PRE-EXISTING
(a4 #34885). Then, against HEAD's ledger.json:

  STALE  (certain, rc 1): a listed row whose site EXISTED at BASE and is GONE at HEAD. The range removed or re-texted
         it and didn't move the row. Fix with the tool: `ledger shrink` / `ledger admit` from a main-tree judged run.
  NEW    (advisory, rc 0): a site at HEAD that wasn't at BASE and isn't listed. It reads R-NEW unless the run grades it
         RESPONSIVE, which only a run can tell. Make it RESPONSIVE, or admit it. A WRITE is tagged: it can reach
         RESPONSIVE only through a stamped fixture (live DML is never credited, #21938), so it usually needs an admit.
  PRE-EXISTING (advisory): a listed row absent at BOTH sides: stale before this range, not caused by it.

DOMAIN, stated: tracked .py files only. The gitignored estate (triggers/, bridges/…) isn't in an archive, and its rows
are HASHED in the ledger, so they're skipped and COUNTED, never silently. Those sites still need the estate gate.
rc: 0 clean (NEW/PRE-EXISTING may print) · 1 STALE · 2 couldn't run (a rev doesn't resolve, an inventory failed).
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__)))))))
from astryx.paths import repo_root  # noqa: E402
import argparse
import json
import os
import subprocess
import sys
import tarfile
import io
import tempfile
from pathlib import Path

SEP = "\x1f"
LIVE = repo_root(__file__)


def _tree(repo: Path, rev: str, dest: Path) -> Path:
    arc = subprocess.run(["git", "archive", rev], cwd=repo, capture_output=True)
    if arc.returncode != 0:
        raise RuntimeError(f"git archive {rev}: {arc.stderr.decode(errors='replace').strip()[:200]}")
    with tarfile.open(fileobj=io.BytesIO(arc.stdout)) as t:
        t.extractall(dest, filter="tar")
    return dest


def _sites(tree: Path, judge: Path = None) -> dict:
    """{site key: is_write} for every site `<file>::<fn><SEP><normalized text>` (and `<SEP>*` for runtime-composed) in
    `tree`, as the JUDGE tree's inventory and normalizer read it (HEAD's, for both sides: a4 #34885)."""
    judge = judge or tree
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(ASTRYX_SQLGUARD_ROOT=str(tree), PYTHONPATH=str(judge), PYTHONWARNINGS="ignore")
    r = subprocess.run([sys.executable, "-m", "astryx.security.sqlguard.inventory", "--json"], cwd=judge, env=env,
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"inventory failed in {tree.name}: {r.stderr.strip()[-300:]}")
    inv = json.loads(r.stdout)
    out = {}
    for fn, v in inv["functions"].items():
        for t, meta in v["sites"].items():
            out[f"{fn}{SEP}{t}"] = bool((meta or {}).get("write")) if isinstance(meta, dict) else False
        if v.get("unresolved"):
            out[f"{fn}{SEP}*"] = False
    return out


def check(repo: Path, base: str, head: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        ht = _tree(repo, head, Path(td) / "head")
        b, h = _sites(_tree(repo, base, Path(td) / "base"), judge=ht), _sites(ht)
        led = Path(td) / "head" / "src" / "astryx" / "security" / "sqlguard" / "ledger.json"
        rows = json.loads(led.read_text())["rows"] if led.is_file() else {}
    hashed = sum(1 for k in rows if k.startswith("sha256:"))
    listed = {k for k in rows if not k.startswith("sha256:")}
    return {"stale": sorted(k for k in listed if k in b and k not in h),
            "new": sorted(k for k in h.keys() - b.keys() if k not in listed),
            "new_writes": sorted(k for k in h.keys() - b.keys() if k not in listed and h[k]),
            "preexisting": sorted(k for k in listed if k not in b and k not in h),
            "hashed_skipped": hashed, "base_sites": len(b), "head_sites": len(h), "ledger_rows": len(rows)}


def _show(k: str) -> str:
    return k.replace(SEP, " :: ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("base")
    ap.add_argument("head")
    ap.add_argument("--repo", default=str(LIVE))
    a = ap.parse_args(argv)
    try:
        r = check(Path(a.repo), a.base, a.head)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"rekey: COULDN'T RUN — {e}")
        return 2
    print(f"rekey {a.base}..{a.head}: {r['base_sites']} → {r['head_sites']} tracked sites; HEAD ledger "
          f"{r['ledger_rows']} rows ({r['hashed_skipped']} hashed estate rows SKIPPED: the estate gate owns them)")
    for label, key, note in (("STALE", "stale", "listed, existed at base, GONE at head: move the row with the tool"),
                             ("NEW", "new", "not at base, not listed: needs a run (RESPONSIVE) or an admit"),
                             ("PRE-EXISTING", "preexisting", "listed but absent at both sides: not this range's")):
        if r[key]:
            print(f"  {label} ({len(r[key])}) — {note}:")
            for k in r[key]:
                w = key == "new" and k in r["new_writes"]
                print(f"    {_show(k)}" + ("   [write: RESPONSIVE only via a stamped fixture, else R-NEW]" if w else ""))
    print("  clean: no listed row loses its site in this range" if not r["stale"] else
          "  RED: merging this range leaves the rows above R-STALE (and their re-texted sites R-NEW)")
    return 1 if r["stale"] else 0


if __name__ == "__main__":
    sys.exit(main())
