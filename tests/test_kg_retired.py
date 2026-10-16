#!/usr/bin/env python3
"""plan-8018 S-retire: the `kg` postgres schema (its node, edge and claim tables) is retired. The recall graph
compiles on request (src/astryx/memory/memgraph.py) and the ingest's CARRIES incidence is derived from the wiki
pages it already digests (memgraph.system2_incidence), so nothing tracked may read or write a kg relation again.

  R0 RED     the pattern hits a planted read of the retired node table (built at runtime, so this file never
             names one), and NOT `pkg.version` (no false hit inside an
             identifier), so a clean result below is the pattern seeing, not the pattern blind.
  R1         every TRACKED file (`git ls-files`; a symlink is skipped, its target is tracked and read itself) has
             0 hits outside EXEMPT: historical measurement prose that names the old tables as a dated source.
Works on a clean checkout (no memory/, no triggers/: those are gitignored and never listed by git).
Exit 0 pass · 1 fail · 77 could-not-run (no git or not a checkout).
The gitignored estate's code is the ESTATE leg, its own gate: tests/test_kg_retired_estate.py (KG and EXEMPT shared).
The database is the LIVE leg: tests/test_kg_retired_live.py (read-only; the schema was dropped 2026-10-16, #57047).
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
KG = re.compile(r"(^|[^A-Za-z0-9_])kg\.[a-z_]")
EXEMPT = {
    "memory/graph/PROPOSAL.md", "memory/ontology.md", "memory/log.md",   # the estate's own history (untracked anyway)
    "src/astryx/security/grep_guard.py",
    "src/astryx/memory/ontology.py",      # its 2026-08-14 measurement, cited from the retired claim table
    "src/astryx/memory/world.py",         # the 336-node measurement query, quoted as history
}


def main():
    fails = []

    def check(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    PLANT = 'x = "SELECT 1 FROM ' + "kg" + '.node"'           # assembled here, so the scan below never meets it
    check("R0 RED the pattern hits a planted kg read", bool(KG.search(PLANT)))
    check("R0 CONTROL the pattern does not hit inside an identifier (pkg.version)", not KG.search("pkg.version"))

    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"SKIP: not a git checkout ({type(e).__name__}) — the tracked set can't be listed.")
        sys.exit(77)
    files = [f for f in out.decode().split("\0") if f]
    hits = []
    for rel in files:
        p = REPO / rel
        if rel in EXEMPT or p.is_symlink() or not p.is_file():
            continue
        try:
            text = p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue                                          # binary: no SQL lives there
        for n, line in enumerate(text.splitlines(), 1):
            if KG.search(line):
                hits.append(f"{rel}:{n}")
    check(f"R1 no tracked file outside the exempt list names a kg relation ({len(files)} files)", not hits,
          ", ".join(hits[:12]) + (f" … and {len(hits) - 12} more" if len(hits) > 12 else ""))

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
