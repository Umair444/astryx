#!/usr/bin/env python3
"""Oracle: the ear pill's one state (observatory/web/src/ear/look.ts, hearing S1) — lag is SHOWN, never silence.

seed #46317: the owner said "painter, …" and got no response; the STT queue was minutes behind and the pill said
"listening". earLook() is the pure function EarControl reads its word, line and tone from. The EXACT module is
bundled with the web build's own esbuild and run under node:
  LAG       capturing with behind_s 25 → "catching up", the sheet line names the lag in seconds; the same for the
            room heard by another tab.
  NO LAG    behind_s 1 → "listening" (RED control: lag isn't claimed when there is none); missing behind_s (an older
            ear service) → "listening".
  ORDER     muted beats lag (the mute is never hidden), offline beats everything.
  WIRING    EarControl.tsx takes its look from earLook (no second, inline copy of the state table).
NOT RUN (77) without node or the web build's esbuild (observatory/web/node_modules).
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "observatory" / "web"
ESBUILD = WEB / "node_modules" / ".bin" / "esbuild"
LOOK = WEB / "src" / "ear" / "look.ts"
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


node = shutil.which("node")
if not node or not ESBUILD.exists():
    print("SKIP: needs node and the web build's esbuild (observatory/web/node_modules): VERIFIED NOTHING")
    sys.exit(77)

CASES = {
    "lag":       {"offline": False, "mic": "listening", "capturing": True, "mine": True, "hearing": False, "behind_s": 25},
    "lag_other": {"offline": False, "mic": "listening", "capturing": False, "mine": False, "hearing": False, "behind_s": 25},
    "lag_heard": {"offline": False, "mic": "listening", "capturing": True, "mine": True, "hearing": True, "behind_s": 25},
    "current":   {"offline": False, "mic": "listening", "capturing": True, "mine": True, "hearing": False, "behind_s": 1},
    "old_ear":   {"offline": False, "mic": "listening", "capturing": True, "mine": True, "hearing": False},
    "muted":     {"offline": False, "mic": "muted", "capturing": False, "mine": False, "hearing": False, "behind_s": 25},
    "offline":   {"offline": True, "mic": "listening", "capturing": True, "mine": True, "hearing": False, "behind_s": 25},
}
DRIVER = "import { earLook } from './look.mjs'\nconst cases = JSON.parse(process.argv[2])\n" \
         "console.log(JSON.stringify(Object.fromEntries(Object.entries(cases).map(([k, v]) => [k, earLook(v)]))))\n"

if not LOOK.is_file():
    want("observatory/web/src/ear/look.ts exists (earLook: the pill's one state)", False, "absent")
else:
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        subprocess.run([str(ESBUILD), str(LOOK), "--format=esm", "--log-level=error", f"--outfile={t / 'look.mjs'}"],
                       check=True)
        (t / "drive.mjs").write_text(DRIVER)
        r = subprocess.run([node, str(t / "drive.mjs"), json.dumps(CASES)], capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise SystemExit(f"node driver failed: {r.stderr[-400:]}")
        L = json.loads(r.stdout)
    print("lag")
    want("capturing, 25 s behind → word 'catching up', live accent, the line says catching up",
         L["lag"]["word"] == "catching up" and L["lag"]["tone"] == "accent" and L["lag"]["live"]
         and "Catching up" in L["lag"]["line"], json.dumps(L["lag"]))
    want("the sheet names the lag in seconds (about 25 s)", re.search(r"\b25 ?s\b", L["lag"].get("sub", "")) is not None,
         json.dumps(L["lag"]))
    want("speech heard right now while behind → still 'catching up' (the lag explains the silence)",
         L["lag_heard"]["word"] == "catching up", json.dumps(L["lag_heard"]))
    want("another tab holds the ear, 25 s behind → 'catching up' too", L["lag_other"]["word"] == "catching up",
         json.dumps(L["lag_other"]))
    print("no lag")
    want("RED control: 1 s behind → 'listening' (no lag claimed)", L["current"]["word"] == "listening",
         json.dumps(L["current"]))
    want("an ear service without behind_s → 'listening'", L["old_ear"]["word"] == "listening", json.dumps(L["old_ear"]))
    print("order")
    want("muted beats lag: 'Muted', warn, action unmute",
         L["muted"]["word"] == "Muted" and L["muted"]["tone"] == "warn" and L["muted"]["action"] == "unmute",
         json.dumps(L["muted"]))
    want("offline beats everything: 'ear offline'", L["offline"]["word"] == "ear offline", json.dumps(L["offline"]))

print("wiring")
src = (WEB / "src" / "components" / "EarControl.tsx").read_text()
want("EarControl.tsx imports earLook from '../ear/look' and keeps no inline copy of the state table",
     re.search(r"import\s*\{[^}]*\bearLook\b[^}]*\}\s*from\s*'\.\./ear/look'", src) is not None
     and "look = { word:" not in src)

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
