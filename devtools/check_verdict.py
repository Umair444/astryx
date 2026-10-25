"""check.sh's OWN verdict sets, parsed from the block it prints LAST. Stdlib only: branch_check imports it, and
devtools/marker.sh runs it under any python (moved verbatim out of branch_check.py, a1 #62905 R1: marker.sh's sed range
read gate output, the injection this parser was built against, #33638).

    python3 -I devtools/check_verdict.py <log>    # line 1: the verdict line; line 2: FAILED (n): [json] | FAILED none
    python3 -I devtools/check_verdict.py --failed <log>    # one FAILED label per line
"""
import json
import re
import sys

_HEAD = {"failed": re.compile(r"^FAILED \(\d+\):$"), "unverified": re.compile(r"^UNVERIFIED \(\d+\) — ")}


def summary(log: str) -> dict:
    """check.sh's OWN verdict sets, parsed from the block it prints LAST (check.sh:109-124): {failed, unverified, line}.
    Only that trailing block counts. A gate's own output can print a "FAILED (3): …" line and "  ✗ …" items (the
    econ provenance oracle does, first end-to-end run #33638), and reading those would let a gate inject or mask a
    name. So: the LAST `check: ` line, and walking UP from it, only its headers (their exact shape) and their items."""
    lines = re.sub(r"\x1b\[[0-9;]*m", "", log).splitlines()
    out = {"failed": [], "unverified": [], "line": ""}
    end = max((i for i, ln in enumerate(lines) if ln.startswith("check: ")), default=None)
    if end is None:
        return out
    out["line"] = lines[end]
    items = []
    above = lines[:end]
    # Between the block's trailing `echo` and the verdict line, check.sh prints its OWN lines, never a gate's: verdict()
    # settles the sqlguard dir first ("sqlguard traces kept (red verdict): …"). Walking up, they're skipped to that blank
    # line. Without this every RED run that kept its traces parsed as FAILED none (a4, 10-25, on .last-check.log).
    while above and above[-1].strip():
        above.pop()
    for ln in reversed(above):
        if not ln.strip():
            if out["failed"] or out["unverified"]:
                break                                      # verdict()'s leading `echo` (check.sh:104): the TOP edge
            continue                                       # its trailing `echo` (check.sh:115), below the block
        if ln.startswith("  ") and ln.strip()[:1] in ("✗", "○"):
            items.append(ln.strip()[1:].strip())
            continue
        kind = next((k for k, rx in _HEAD.items() if rx.match(ln)), None)
        if kind is None:
            break                                          # above the summary block: gate output, never read
        out[kind] = list(reversed(items)) + out[kind]
        items = []
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["--failed"]:    # one FAILED label per line (pushed_tree_check's WHO LAST TOUCHED list)
        print("\n".join(summary(open(sys.argv[2], errors="replace").read())["failed"]))
        sys.exit(0)
    s = summary(open(sys.argv[1], errors="replace").read())
    print(s["line"])
    print(f"FAILED ({len(s['failed'])}): {json.dumps(s['failed'], ensure_ascii=False)}" if s["failed"] else "FAILED none")
