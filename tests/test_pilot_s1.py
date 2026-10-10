#!/usr/bin/env python3
"""test_pilot_s1 — plan-9000 S1: the observatory's ONE action catalog, its matrix, its parity with the code.

  (a) the catalog is well formed: every schema uses only the keywords the validator implements, every action
      has a known class, every matrix cell is one of allow / projection / confirm;
  (b) parity: the browser's handler keys (pilot/handlers.ts) are EXACTLY the catalog's action names, and the set
      is non-empty (a parity test over two empty sets would pass vacuously);
  (c) set_theme's enum is exactly the shipped theme ids (canvas/web/src/themes.ts), navigate's enum exactly the
      app's tabs minus the fullscreen face mode (App.tsx Route);
  (d) the MCP list for agents is cut from the matrix: exactly the actions agent may run, all of class view,
      never read/write/actuate;
  (e) the executor's gate, run by node on the real catalog (tests/pilot_core_test.ts).
No DB, no network, no browser.
"""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CAT = REPO / "observatory/pilot/catalog.json"
fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


spec = importlib.util.spec_from_file_location("pilot_catalog", REPO / "observatory/pilot/catalog.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)
cat = pc.load(CAT)
names = [a["name"] for a in cat["actions"]]

# (a)
core = (REPO / "observatory/web/src/pilot/core.ts").read_text()
kw = set(re.search(r"export const KEYWORDS = \[([^\]]*)\]", core).group(1).replace("'", "").replace("\n", "").replace(" ", "").split(","))


def keywords(s, out):
    for k, v in s.items():
        out.add(k)
        if k == "properties":
            for sub in v.values():
                keywords(sub, out)
    return out


used = set()
for a in cat["actions"]:
    keywords(a["parameters"], used)
arm("schemas use only the validator's keywords", used <= kw, f"unsupported: {sorted(used - kw)}")
arm("every action has a known class", all(a.get("class") in cat["classes"] for a in cat["actions"]),
    [a["name"] for a in cat["actions"] if a.get("class") not in cat["classes"]])
cells = {v for row in cat["matrix"].values() for v in row.values()}
arm("every matrix cell is allow / projection / confirm", cells <= {"allow", "projection", "confirm"}, sorted(cells))
arm("every matrix row names known classes", all(set(r) <= set(cat["classes"]) for r in cat["matrix"].values()))
arm("action names are unique", len(names) == len(set(names)))
arm("every action's parameters are a strict object", all(a["parameters"].get("type") == "object" and a["parameters"].get("additionalProperties") is False for a in cat["actions"]))

# (b)
handlers = (REPO / "observatory/web/src/pilot/handlers.ts").read_text()
body = handlers[handlers.index("export function makeHandlers"):]
keys = re.findall(r"^    ([a-z_]+): ", body, re.M)
arm("handler keys are non-empty (anti-vacuity)", len(keys) >= 5, keys)
arm("handlers.ts keys == catalog actions", sorted(keys) == sorted(names),
    f"only in catalog {sorted(set(names) - set(keys))}, only in handlers {sorted(set(keys) - set(names))}")

# (c)
by = {a["name"]: a for a in cat["actions"]}
themes = re.findall(r"\{ id: '([a-z-]+)', name:", (REPO / "canvas/web/src/themes.ts").read_text())
arm("set_theme enum == the shipped themes", sorted(by["set_theme"]["parameters"]["properties"]["theme"]["enum"]) == sorted(themes) and themes,
    f"themes.ts {themes}")
app = (REPO / "observatory/web/src/App.tsx").read_text()
route = app[app.index("export type Route"):app.index("function parseHash")]
tabs = set(re.findall(r"tab: '([a-z]+)'", route)) - {"face"}
arm("navigate enum == the app's tabs (minus the face mode)", set(by["navigate"]["parameters"]["properties"]["view"]["enum"]) == tabs, sorted(tabs))

# (d)
mcp = pc.mcp_tools(cat)
arm("the agent MCP list is non-empty", len(mcp) > 0)
arm("the agent MCP list is exactly the view actions", sorted(t["name"] for t in mcp) == sorted(a["name"] for a in cat["actions"] if a["class"] == "view"))
arm("no read / write / actuate action reaches agents", not any(by[t["name"]]["class"] != "view" for t in mcp))
arm("a missing matrix cell reads as deny", pc.cell(cat, "agent", "actuate") == "deny" and pc.cell(cat, "nobody", "view") == "deny")
arm("no principal runs write or actuate outright: every such cell is confirm or absent", all(r.get(k, "deny") in ("confirm", "deny") for r in cat["matrix"].values() for k in ("write", "actuate")))
arm("there is no owner_tap principal (a caller-assertable owner)", "owner_tap" not in cat["matrix"])
arm("a classless action reads as actuate", pc.cls({"name": "x"}, cat) == "actuate")

# (e)
node = shutil.which("node")
if not node:
    arm("node is installed (the executor's gate runs under it)", False)
else:
    r = subprocess.run([node, str(REPO / "tests/pilot_core_test.ts"), str(CAT)], capture_output=True, text=True, timeout=60)
    print(r.stdout.rstrip())
    arm("the executor's gate (node)", r.returncode == 0, r.stderr.strip()[-400:])

print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
