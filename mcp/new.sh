#!/usr/bin/env bash
# astryx · mcp/new.sh <name> — mint a new MCP tool server in one command.
#
# Tools are python functions with an MCP decorator; a server is a folder. This scaffolds
# the folder, registers it (registry.json), regenerates the manifest, and wires the grant
# into spawn.sh's case table — so "create a tool" is: run this, fill in the function,
# grant it in a charter. Nobody hand-copies boilerplate.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME=${1:?usage: mcp/new.sh <name> [agent1,agent2,...]}
# The CREATOR decides who gets the tool — pass the recipient agents as arg 2 (comma-sep).
# Not everyone gets everything; a tool is granted to the minds whose craft needs it. Omit to
# grant nobody yet (add 'Grants: <name>' to a charter later, or re-run with the list).
GRANTEES=${2:-}
[[ "$NAME" =~ ^[a-z][a-z0-9_-]*$ ]] || { echo "name must be [a-z][a-z0-9_-]*"; exit 1; }
DIR="$ROOT/mcp/$NAME"
[ -e "$DIR" ] && { echo "mcp/$NAME already exists"; exit 1; }

mkdir -p "$DIR"
cat > "$DIR/server.py" <<EOF
#!/usr/bin/env python3
"""astryx · $NAME MCP server — <one line: what capability this scopes>.

Granted per charter (\`Grants: $NAME\`). Config via the org's .env (never hardcode
secrets; never echo them — scrub error text)."""
from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
mcp = FastMCP("$NAME")


@mcp.tool()
def example(query: str) -> str:
    """<what this tool does, for the agent reading the schema>."""
    return f"$NAME received: {query}"


if __name__ == "__main__":
    mcp.run()
EOF

# register + manifest
python3 - "$ROOT" "$NAME" <<'PY'
import json, os, sys
root, name = sys.argv[1], sys.argv[2]
p = f"{root}/mcp/registry.json"
d = json.load(open(p))
# author is DECLARED at creation (AUTHOR=<resident> mcp/new.sh ...); default 'unknown' so the
# field can't be silently skipped — pay-the-author (3408) credits W to this author, and an
# unknown-authored tool's credit PARKS (house account) until sourced + re-ratified by seed.
d[name] = {"command": "venv/bin/python", "args": [f"mcp/{name}/server.py"],
           "author": os.environ.get("AUTHOR", "unknown")}
json.dump(d, open(p, "w"), indent=1)
print(f"registered {name} in registry.json (author={d[name]['author']})")
PY

# wire the grant into spawn.sh (idempotent: skip if present)
if ! grep -q "\"$NAME\":" "$ROOT/nucleus/spawn.sh"; then
python3 - "$ROOT" "$NAME" <<'PY'
import sys
root, name = sys.argv[1], sys.argv[2]
p = f"{root}/nucleus/spawn.sh"
s = open(p).read()
anchor = '    contacts) EXTRA="$EXTRA,'
block = (f'    {name}) EXTRA="$EXTRA,\n'
         f'  \\"{name}\\": {{ \\"command\\": \\"$ROOT/venv/bin/python\\", '
         f'\\"args\\": [\\"$ROOT/mcp/{name}/server.py\\"] }}";;\n')
assert anchor in s, "spawn.sh grant table anchor moved"
open(p, "w").write(s.replace(anchor, block + anchor))
print(f"grant '{name}' wired into spawn.sh")
PY
fi

"$ROOT/venv/bin/python" "$ROOT/mcp/scan.py" >/dev/null 2>&1 || true

# GRANT to the creator-named agents: write 'Grants: <name>' into each charter (append to an
# existing Grants line, or add one). Idempotent; resolves the charter through the ONE resolver
# so it works at any tree depth. Takes effect on that agent's next respawn.
if [ -n "$GRANTEES" ]; then
python3 - "$ROOT" "$NAME" "$GRANTEES" <<'PY'
import re, subprocess, sys
root, name, grantees = sys.argv[1], sys.argv[2], sys.argv[3]
for agent in [a.strip() for a in grantees.split(",") if a.strip()]:
    try:
        path = subprocess.check_output(
            [f"{root}/venv/bin/python", f"{root}/nucleus/charter.py", agent],
            text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        print(f"  ! {agent}: no charter — skipped"); continue
    s = open(path).read()
    m = re.search(r'^Grants:(.*)$', s, re.M)
    if m:
        have = [g.strip() for g in m.group(1).split(",") if g.strip()]
        if name in have:
            print(f"  = {agent}: already granted {name}"); continue
        s = s[:m.start()] + "Grants: " + ", ".join(have + [name]) + s[m.end():]
    else:  # no Grants line yet — add one after the opening title/intro block (first blank line)
        i = s.find("\n\n")
        cut = (i + 2) if i != -1 else 0
        s = s[:cut] + f"Grants: {name}\n\n" + s[cut:]
    open(path, "w").write(s)
    print(f"  + granted {name} to {agent}")
PY
fi
echo "mcp/$NAME ready: edit $DIR/server.py. Granted to: ${GRANTEES:-none yet (re-run with an agent list, or add 'Grants: $NAME' to a charter)}."
