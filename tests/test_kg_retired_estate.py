#!/usr/bin/env python3
"""plan-8018 S-retire, the ESTATE leg: no gitignored estate code reads or writes a retired kg relation.

tests/test_kg_retired.py scans the TRACKED tree (`git ls-files`), which by construction never lists memory/ or
triggers/; the estate's own code (the nightly ingest, the ontology trigger, ...) is exactly where the old graph's
writers lived. This leg runs the SAME pattern and the SAME exempt list (imported, never copied) over
memory/**/*.py and triggers/**/*.py under the estate root.

  E0 RED      a planted estate (temp root, triggers/ present) whose trigger reads the retired node table: rc 1,
              and the hit names the planted file. The read is assembled at runtime, so this file never names one.
  E0 CONTROL  the same planted estate with a clean trigger: rc 0.
  E0 ABSENT   a planted root with no triggers/: rc 77 and the SKIP line, never a pass.
  E1          the estate at the root: 0 hits outside EXEMPT, over a non-empty .py set.

The estate root is ASTRYX_KG_ESTATE_ROOT (default: this checkout). The estate rule is the one
src/astryx/security/sqlguard/estate.py uses: triggers/ absent means a committed-only tree (CI, a clone), so the
leg is NOT SEARCHED and exits 77 (UNVERIFIED in check.sh, never green); triggers/ present means a live host.
When the env var is set the file runs only the scan (it is the child the E0 arms drive).
Why only .py under memory/ and triggers/ (a4 #56888): measured 2026-10-16, after the DROP, over every OTHER
gitignored file (28,801; venv/, node_modules/, .claude/, backups/ and caches excluded), the pattern hits 11 files,
all prose or transcript (.md, .jsonl, .txt under homes/ and memory/) and 0 code. Re-measure if the estate grows code
elsewhere. The database itself is the LIVE leg, its own gate: tests/test_kg_retired_live.py.
Exit 0 pass · 1 fail · 77 estate absent (triggers/ missing at the root).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from test_kg_retired import EXEMPT, KG

HERE = Path(__file__).resolve()
ENV = "ASTRYX_KG_ESTATE_ROOT"
ROOT = Path(os.environ.get(ENV) or HERE.parents[1]).resolve()
SUBTREES = ("memory", "triggers")


def scan(root):
    """(files scanned, hits as rel:line) over the estate's .py files. A symlink is skipped, as in the tracked leg."""
    files, hits = 0, []
    for sub in SUBTREES:
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            if rel in EXEMPT or p.is_symlink() or not p.is_file():
                continue
            files += 1
            try:
                text = p.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if KG.search(line):
                    hits.append(f"{rel}:{n}")
    return files, hits


def estate_leg(root):
    """The gate proper: 77 on a committed-only tree, else 0/1 on the scan."""
    if not (root / "triggers").is_dir():
        print(f"SKIP: NOT SEARCHED — no estate at {root} (a committed-only tree: triggers/ absent)")
        return 77
    files, hits = scan(root)
    ok = files > 0 and not hits
    detail = ("the estate is present but no .py file was scanned: the leg saw nothing" if not files else
              ", ".join(hits[:12]) + (f" … and {len(hits) - 12} more" if len(hits) > 12 else ""))
    print(f"  {'PASS' if ok else 'FAIL'}  E1 no estate .py outside the exempt list names a kg relation "
          f"({files} files under {'/, '.join(SUBTREES)}/)" + ("" if ok else f"  — {detail}"))
    return 0 if ok else 1


def child(root):
    p = subprocess.run([sys.executable, str(HERE)], env={**os.environ, ENV: str(root)},
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def main():
    if os.environ.get(ENV):                      # the child: scan the given root and nothing else
        sys.exit(estate_leg(ROOT))
    fails = []

    def check(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    read = 'rows = cur.execute("SELECT id FROM ' + "kg" + '.node").fetchall()\n'   # assembled: never on disk here
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "triggers" / "someone").mkdir(parents=True)
        (t / "memory" / "graph").mkdir(parents=True)
        (t / "memory" / "graph" / "clean.py").write_text("import pkg.version\n")
        planted = t / "triggers" / "someone" / "planted.py"
        planted.write_text("def check(cur):\n    " + read)
        rc, out = child(t)
        check("E0 RED a planted estate trigger reading the retired node table fails the leg",
              rc == 1 and "triggers/someone/planted.py:2" in out, f"rc={rc}: {out.strip()[-300:]}")
        planted.write_text("def check(cur):\n    return None\n")
        rc, out = child(t)
        check("E0 CONTROL the same estate, clean, passes", rc == 0 and "(2 files" in out,
              f"rc={rc}: {out.strip()[-300:]}")
        (t / "triggers" / "someone" / "planted.py").unlink()
        (t / "triggers" / "someone").rmdir()
        (t / "triggers").rmdir()
        rc, out = child(t)
        check("E0 ABSENT no triggers/ at the root is 77 (NOT SEARCHED), never a pass",
              rc == 77 and "triggers/ absent" in out, f"rc={rc}: {out.strip()[-300:]}")

    rc = estate_leg(ROOT)
    if fails:                                    # a red arm is red on every tree, never NOT SEARCHED
        rc = 1
    print(f"\n{'FAIL' if rc == 1 else 'SKIP' if rc == 77 else 'PASS'}: {len(fails) + (rc == 1 and not fails)} failing"
          + (" · estate NOT SEARCHED" if rc == 77 else ""))
    sys.exit(rc)


if __name__ == "__main__":
    main()
