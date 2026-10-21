#!/usr/bin/env python3
"""Mutants for plan-11860 F0 and S3. The oracles are tests/test_floor_f0.py and (S-mutants) tests/test_floor_s3.py;
every mutant must turn its oracle RED.
Its subjects span several files (the resolver, the bridges, the PUT, doctor, the .env writer), so this probe mutates IN
PLACE on the tree it sits in and restores each file in a finally: run it on a worktree, never the live checkout.
a3's review list (#61993) is M1..M5; a1's BC-1/BC-2 mutants are M6/M7; M8..M10 are the gate, the writer and doctor."""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORACLE = REPO / "tests" / "test_floor_f0.py"
S3 = REPO / "tests" / "test_floor_s3.py"
LR = REPO / "src" / "astryx" / "security" / "logredact.py"
B, API, CFG = REPO / "bridges" / "routing.py", REPO / "observatory" / "api" / "main.py", REPO / "src" / "astryx" / "config.py"
MUTANTS = {
    "M1 a duplicate chat is accepted": (B, "        if chat in seen:\n", "        if False:\n"),
    "M2 the diff reads the rows, not the effective maps (no doorbell)":
        (B, '            out["doorbell"].append({"agent": ag, "old": o, "new": n})', "            pass"),
    "M3 the resolver is copied into main.py":
        (API, "def glyphs_of(", "def resolve(rows):\n    return [r for r in rows if r.get('enabled')]\n\n\ndef glyphs_of("),
    "M4 the PUT stops requiring If-Match": (API, "    if not want:\n        return JSONResponse(", "    if False:\n        return JSONResponse("),
    "M5 the home flag is ignored (the first row is the doorbell)":
        (B, "        homes = [r for r in mine if r.get(\"home\") is True]\n        return homes[0] if len(homes) == 1 else None",
         "        return mine[0] if mine else None"),
    "M6 set_env rewrites the first occurrence and leaves the rest (BC-1's break)":
        (CFG, "        for i in reversed(hits[1:]):\n            del lines[i]\n", ""),
    "M7 a bridge keeps a first-match loop (BC-2)":
        (REPO / "bridges" / "telegram.py", 'route = routes().chat(chat.removeprefix("tg:"))',
         "route = next((r for r in routes() if f\"tg:{r.get('chat')}\" == chat), None)"),
    "M8 the gate is method-blind again (a public GET opens its POST)":
        (API, '    if (p.startswith("/api/") and (m, p) not in PUBLIC', '    if (p.startswith("/api/") and p not in PUBLIC_PATHS'),
    "M9 a host write bypasses atomic_write": (API, "    atomic_write(p, f.content)\n", "    p.write_text(f.content)\n"),
    "M10 doctor keeps its own validator":
        (REPO / "src" / "astryx" / "cli.py", "def org_checks(ctx: Ctx) -> int:",
         "def validate(rows, agents=None):\n    return []\n\n\ndef org_checks(ctx: Ctx) -> int:"),
    "M11 the glyphs projection carries the chat id":
        (API, '    return [{"agent": a, "channel": c, "kind": k, "count": n} for (a, c, k), n in sorted(counts.items())]',
         '    return [{"agent": a, "channel": c, "kind": k, "count": n, "chat": str(next(iter(tables.values()))[0].get("chat"))}'
         ' for (a, c, k), n in sorted(counts.items())]'),
    "M12 a routes file that stops parsing reads [] (BC-3)":
        (B, "        return _last_good.get(key, [])", "        return []"),
    "S1 logredact stops scrubbing a bot token (httpx's request log leaks it)":
        (LR, '    return _HOOK.sub(r"\\1<redacted>", _TG.sub(r"\\1<redacted>", _KEY.sub(r"\\1<redacted>", text)))',
         '    return _HOOK.sub(r"\\1<redacted>", _KEY.sub(r"\\1<redacted>", text))', S3),
    "S2 a probe failure echoes the upstream error text":
        (API, '                            status_code=400 if outcome == "invalid" else 503)',
         '                            status_code=400 if outcome == "invalid" else 503) if False else JSONResponse({"error": f"{outcome}: {token}", "outcome": outcome}, status_code=400 if outcome == "invalid" else 503)', S3),
    "S3 a set key is replaced without confirm": (API, "    if config.is_set(key, ENV_FILE) and not body.replace:", "    if False:", S3),
    "S4 CONNECTED without the bridge's /health":
        (API, '                     "connected" if healthy else "written")', '                     "connected")', S3),
    "S5 pairing runs over a linked phone": (API, '    if link["state"] != "unlinked":', '    if link["state"] == "unknown":', S3),
}


def main():
    if (REPO / "triggers").is_dir():
        sys.exit("mutants_floor_f0: refusing to mutate a live tree (triggers/ present): run it on a worktree")
    survived = []
    for name, (f, old, new, *rest) in MUTANTS.items():
        oracle = rest[0] if rest else ORACLE
        src = f.read_text()
        if src.count(old) != 1:
            print(f"  STALE  {name}: the anchor is not exactly once in {f.name}")
            survived.append(name)
            continue
        try:
            f.write_text(src.replace(old, new))
            r = subprocess.run([sys.executable, str(oracle)], capture_output=True, text=True, timeout=600, env=os.environ)
        finally:
            f.write_text(src)
        killed = r.returncode != 0
        print(f"  {'KILLED  ' if killed else 'SURVIVED'} {name}" + ("" if killed else f"  (rc {r.returncode})"))
        if not killed:
            survived.append(name)
    print(f"{'PASS' if not survived else 'FAIL'}: floor F0 mutants ({len(MUTANTS) - len(survived)}/{len(MUTANTS)} killed)")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
