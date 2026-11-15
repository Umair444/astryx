#!/usr/bin/env python3
"""Oracle: the chat workspace never spells "the human" or "me" as the literal 'owner' (11-15).

The workspace was built for one human, and ~49 sites compared a name to 'owner' to mean either "a human wrote this" or
"this is mine". A member is a viewer too: her ask drew no live line, her uploads read "Cv Faran Khalid.2", the owner's
words read "You" on her screen. The two meanings have one spelling each: types.isHuman(name) and api.isMine(name) /
api.personName(name). This scan fails on any new comparison against the literal, so the regression can't come back
one site at a time.

  L1 no `=== 'owner'` / `!== 'owner'` (either side, either quote) in web/src/chat or the shared api/store modules,
     outside the allowlist below (each entry says why it is the literal and not a viewer)
  L2 the scan sees the tree (a real hit is found in a synthetic file: the regex is not vacuous)
Exit 0 pass · 1 fail."""
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "observatory" / "web" / "src"
FILES = [*sorted((WEB / "chat").rglob("*.ts")), *sorted((WEB / "chat").rglob("*.tsx")), WEB / "api.ts", WEB / "store.tsx"]
CMP = re.compile(r"""(?:[!=]==\s*['"]owner['"])|(?:['"]owner['"]\s*[!=]==)""")
# file -> the substrings of a line that may hold the literal: each is the OWNER as a fixed role, never "the viewer"
ALLOW: dict[str, tuple[str, ...]] = {}

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def hits(text: str, rel: str) -> list[str]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("//", 1)[0]
        if CMP.search(code) and not any(a in line for a in ALLOW.get(rel, ())):
            out.append(f"{rel}:{n}: {line.strip()[:140]}")
    return out


found = [h for f in FILES if f.exists() for h in hits(f.read_text(), str(f.relative_to(WEB)))]
arm("L1 no comparison against the literal 'owner' in the chat workspace", not found, "\n        ".join(found))
arm("L2 the scan finds a planted comparison", bool(hits("const mine = m.from === 'owner'\nif ('owner' !== x) y()", "x.ts"))
    and len(hits("const a = m.from === \"owner\"", "x.ts")) == 1 and not hits("// m.from === 'owner'", "x.ts"))
arm("L2 ...and it read the tree", len(FILES) > 50, len(FILES))
print(f"{'PASS' if not fails else 'FAIL'}: chat viewer lint ({fails} failing)")
sys.exit(1 if fails else 0)
