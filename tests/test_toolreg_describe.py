#!/usr/bin/env python3
"""Oracle: a registered tool's search text is its OWN header, never a triple quote from its body.

    venv/bin/python tests/test_toolreg_describe.py        (also run by nucleus/check.sh)
    TOOLREG_SRC=<path> …                                   (the subject; default nucleus/toolreg.py)

toolreg._describe() is the registry door's search text: find() matches words against it, so a
wrong description makes a tool unfindable. The Python-docstring regex used to run over EVERY
file, so a shell script with `'''` or `\"\"\"` anywhere in its first 40 lines was described by
whatever followed the quote. Seen live: mcp/new.sh was registered as its own template's
placeholder docstring ("astryx · $NAME MCP server — <one line: …>"), and a script whose DSN
line held `tr -d '"'\\''` was registered as ")".

  S1 a shell script with `'''` in its code is described by its header comment.
  S2 a shell script with a docstring inside a heredoc (the mcp/new.sh shape) is described by its
     header comment, not the heredoc's docstring.
  S3 control: a .py module docstring is still the description.
  S4 control: a .py with no docstring falls back to its header comment.
  S5 the real case: mcp/new.sh on this tree is described by its own header (skip if absent).
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
SRC = Path(os.environ.get("TOOLREG_SRC") or REPO / "nucleus" / "toolreg.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


if not SRC.is_file():
    print(f"  SKIP  subject absent: {SRC}")
    sys.exit(EXIT_SKIP)
spec = importlib.util.spec_from_file_location("toolreg_under_test", SRC)
toolreg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolreg)

CASES = {
    "S1 shell `'''` in code → header": ("a.sh",
        "#!/usr/bin/env bash\n# astryx · vitals — the org's health in one pass.\n"
        "DSN=\"$(grep -E '^X=' .env | cut -d= -f2- | tr -d '\"'\\''')\"\n",
        "astryx · vitals — the org's health in one pass."),
    "S2 shell heredoc docstring → header": ("b.sh",
        "#!/usr/bin/env bash\n# astryx · new.sh <name> — mint a new MCP tool server.\n"
        "cat > server.py <<EOF\n\"\"\"astryx · $NAME MCP server — <one line>\"\"\"\nEOF\n",
        "astryx · new.sh <name> — mint a new MCP tool server."),
    "S3 control: .py module docstring": ("c.py",
        "#!/usr/bin/env python3\n\"\"\"astryx · usage gauge — one read.\n\nMore.\n\"\"\"\n",
        "astryx · usage gauge — one read."),
    "S4 control: .py header comment, no docstring": ("d.py",
        "#!/usr/bin/env python3\n# astryx · tiny helper — does one thing.\nprint(1)\n",
        "astryx · tiny helper — does one thing."),
}

with tempfile.TemporaryDirectory() as td:
    for name, (fn, body, want) in CASES.items():
        p = Path(td) / fn
        p.write_text(body)
        got = toolreg._describe(p)
        check(name, got == want, f"got {got!r}, want {want!r}")

real = REPO / "mcp" / "new.sh"
if real.is_file():
    header = next((ln.strip().lstrip("# ").strip() for ln in real.read_text().splitlines()
                   if ln.startswith("#") and not ln.startswith("#!")), "")
    got = toolreg._describe(real)
    check("S5 real: mcp/new.sh described by its own header", got == header[:200],
          f"got {got!r}, want {header[:200]!r}")
else:
    print("  SKIP  S5 mcp/new.sh absent on this tree")

print(f"{'FAIL' if fails else 'PASS'}: toolreg describe ({len(fails)} failed)")
sys.exit(1 if fails else 0)
