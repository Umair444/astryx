#!/usr/bin/env bash
# astryx · mcp/new.sh <name> — mint a new MCP tool server in one command.
#
# Tools are python functions with an MCP decorator; a server is a folder. This scaffolds
# the folder, registers it (registry.json), regenerates the manifest, and wires the grant
# into spawn.sh's case table — so "create a tool" is: run this, fill in the function,
# grant it in a charter. Nobody hand-copies boilerplate.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME=${1:?usage: mcp/new.sh <name>}
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
import json, sys
root, name = sys.argv[1], sys.argv[2]
p = f"{root}/mcp/registry.json"
d = json.load(open(p))
d[name] = {"command": "venv/bin/python", "args": [f"mcp/{name}/server.py"]}
json.dump(d, open(p, "w"), indent=1)
print(f"registered {name} in registry.json")
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
echo "mcp/$NAME ready: edit $DIR/server.py, then add 'Grants: $NAME' to a charter."
