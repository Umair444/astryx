#!/usr/bin/env python3
"""Oracle: the owner-surface census (plan-11884 G2 + G3, a4 #62268; domain per a4 #62291 and a2 #62292).

AN OWNER SURFACE MAY ADD ROUTES AND READERS, NEVER A NEW WRITER, AND NEVER A NEW INTERPRETER OF STRANGER BYTES.

THE DOMAIN, derived once and never hand-listed: the modules whose bytes reach the owner's origin. That is every .py
under observatory/ (a1 BC-1 (a)), plus the service behind EACH proxy route. A proxy is read off main.py's ROUTES (a2
#62292 (1)): a handler whose path is a catch-all (`{path...}`). Each must resolve to ONE declared upstream: a global
assigned from `_upstream("<unit>", ...)`, or a function whose body names `orgs.port('<unit>')`. A proxy that resolves
to none is a FAILURE, never a silent drop. The unit maps to its module through init.sh's own ExecStart line.

  G2 WRITES: the (file, function) sites that INSERT INTO messages (case-insensitive, string constants, AST) over the
     domain are EXACTLY the expected set. A RED control: a planted sibling module with a lowercase insert is caught.
     A second instrument that fails differently (a1 BC-1 (b)): every sqlguard ledger row naming `into messages` in the
     domain is in the text census (sqlguard's rule is "observed, or listed debt", so the ledger is a SUBSET: a ledger
     row the census lacks means the census is blind).
  G3 SERVING: every FileResponse / StreamingResponse / StaticFiles call site in the domain is CLASSIFIED below with
     its reason; anything else (a second hand-written file server) is a failure. The untrusted-byte routes answer
     through serve_untrusted: /api/chat/file, canvas's /api/file and /api/file/preview (a2 BC-2 (ii)).
  CLIENT (a1 BC-2): no URL observatory/web/src builds for /api/chat/file carries `key=`.
"""
import ast
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("SURFACE_ROOT") or REPO)
MAIN = Path(os.environ.get("SURFACE_MAIN_SRC") or ROOT / "observatory" / "api" / "main.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  — {detail}"))
    if not ok:
        fails.append(name)


# ── the domain ───────────────────────────────────────────────────────────────────────────────────────────────────
def proxies(main_src: str) -> tuple[dict, list]:
    """{route path: unit stem} for every catch-all route in main.py, and the ones that resolve to no upstream."""
    t = ast.parse(main_src)
    upstream_globals = {}                                 # CANVAS_UP = _upstream("astryx-canvas", ...)
    port_funcs = {}                                       # def growbot_body(): ... orgs.port('astryx-growbot') ...
    for n in t.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "_upstream" \
                and n.value.args and isinstance(n.value.args[0], ast.Constant):
            for tg in n.targets:
                if isinstance(tg, ast.Name):
                    upstream_globals[tg.id] = n.value.args[0].value
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            m = re.search(r"orgs\.port\(\s*['\"]([\w-]+)['\"]", ast.unparse(n))
            if m:
                port_funcs[n.name] = m.group(1)
    out, orphans = {}, []
    for n in t.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str) \
                    and re.search(r"\{path(?::path)?\}", d.args[0].value):
                names = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
                stems = {upstream_globals[x] for x in names if x in upstream_globals} | \
                        {port_funcs[x] for x in names if x in port_funcs}
                if len(stems) == 1:
                    out[d.args[0].value] = stems.pop()
                else:
                    orphans.append(f"{d.args[0].value} -> {sorted(stems) or 'no declared upstream'}")
    return out, orphans


def unit_module(stem: str) -> Path | None:
    """init.sh's ExecStart for a unit: `uvicorn pkg.mod:app` or `python -m pkg.mod` -> the module's file."""
    init = (ROOT / "init.sh").read_text()
    at = init.find(f"_uw {stem} service")
    m = re.search(r"ExecStart=\S*?(?:uvicorn\s+([\w.]+):\w+|python\s+-m\s+([\w.]+))", init[at:at + 2000]) if at >= 0 else None
    if not m:
        return None
    mod = (m.group(1) or m.group(2)).replace(".", "/") + ".py"
    for base in (ROOT, ROOT / "src"):
        if (base / mod).is_file():
            return base / mod
    return None


def domain() -> tuple[list[Path], dict, list]:
    px, orphans = proxies(MAIN.read_text())
    real_main = ROOT / "observatory" / "api" / "main.py"
    files = sorted(p for p in (ROOT / "observatory").rglob("*.py") if "node_modules" not in p.parts)
    if MAIN != real_main:                               # the probe's channel: the judged main.py stands in for the real one
        files = [MAIN if p == real_main else p for p in files]
    mods = {}
    for route, stem in px.items():
        f = unit_module(stem)
        if f is None:
            orphans.append(f"{route} -> unit {stem} has no ExecStart module in init.sh")
        else:
            mods[route] = f
            if f not in files:
                files.append(f)
    return files, mods, orphans


def _rel(f: Path) -> str:
    if f == MAIN:
        return "observatory/api/main.py"
    return str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f)


# ── G2 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
INSERT = re.compile(r"insert\s+into\s+messages\b", re.I)


def writers(files) -> list[tuple[str, str]]:
    """(relpath, innermost function) per string constant that INSERTs INTO messages."""
    out = []
    for f in files:
        rel = _rel(f)
        tree = ast.parse(f.read_text())
        docs = {id(n.body[0].value) for n in ast.walk(tree)          # a docstring describes a writer; it isn't one
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}

        def walk(node, fn):
            for ch in ast.iter_child_nodes(node):
                inner = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                if isinstance(ch, ast.Constant) and isinstance(ch.value, str) and INSERT.search(ch.value) and id(ch) not in docs:
                    out.append((rel, fn))
                walk(ch, inner)
        walk(tree, "<module>")
    return sorted(out)


EXPECTED_WRITERS = sorted([
    ("observatory/api/main.py", "people_answer"), ("observatory/api/main.py", "goal_create"),
    ("observatory/api/main.py", "owner_send"), ("observatory/api/main.py", "brain_completions"),
    ("observatory/api/main.py", "growbot_event"), ("observatory/api/main.py", "growbot_event"),
    ("observatory/api/main.py", "memory_chat"), ("observatory/api/main.py", "cog_new_org"),
    ("observatory/api/main.py", "memory_propose"), ("observatory/api/room.py", "ask"),
    ("bridges/canvas.py", "_say"), ("bridges/ear.py", "record"),
])

# ── G3 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
SERVERS = ("FileResponse", "StreamingResponse", "StaticFiles")
CLASSIFIED = {   # (relpath, function, constructor): why it may serve bytes without serve_untrusted
    ("observatory/api/main.py", "agent_avatar", "FileResponse"): "an agent's own avatar from the agents/ tree (org-authored); "
        "nosniff + a CSP sandbox, pinned by test_active_content S2",
    ("bridges/canvas.py", "avatar", "FileResponse"): "the same avatar rule on canvas, pinned by test_active_content S2",
    ("observatory/api/main.py", "index", "FileResponse"): "the app's own build output (web/dist)",
    ("observatory/front.py", "index", "FileResponse"): "the front's own build output (web/dist)",
    ("observatory/api/main.py", "<module>", "StaticFiles"): "the app's own build output (web/dist)",
    ("observatory/front.py", "<module>", "StaticFiles"): "the front's own build output (web/dist)",
    ("bridges/canvas.py", "<module>", "StaticFiles"): "canvas's own build output (canvas/web/dist)",
    ("observatory/api/room.py", "audio", "FileResponse"): "speech the org synthesised from an agent's line (TTS), a fixed "
        "audio/mpeg type; no stranger's bytes",
    ("observatory/api/main.py", "events", "StreamingResponse"): "the wire's SSE: org JSON, a fixed text/event-stream type",
    ("bridges/canvas.py", "events", "StreamingResponse"): "canvas's SSE: org JSON, a fixed text/event-stream type",
    ("observatory/front.py", "cog_stream", "StreamingResponse"): "the cog's SSE: org JSON, a fixed text/event-stream type",
    ("observatory/api/main.py", "whatsapp_pair", "StreamingResponse"): "wacli's pairing lines (a QR as text), a fixed "
        "text/plain type",
    ("observatory/api/main.py", "_pipe", "StreamingResponse"): "the /canvas and /ear proxies: their upstream modules are "
        "IN this census (the derived domain)",
    ("observatory/front.py", "_relay", "StreamingResponse"): "the cog front's relay to each org's observatory, which is "
        "main.py, in this census",
}
UNTRUSTED_ROUTES = (("observatory/api/chat.py", "file"), ("bridges/canvas.py", "message_file"),
                    ("bridges/canvas.py", "message_file_preview"))


def servers(files) -> tuple[set, dict]:
    sites, calls_su = set(), {}
    for f in files:
        rel = _rel(f)
        tree = ast.parse(f.read_text())

        def walk(node, fn):
            for ch in ast.iter_child_nodes(node):
                inner = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                if isinstance(ch, ast.Call):
                    nm = getattr(ch.func, "id", None) or getattr(ch.func, "attr", None)
                    if nm in SERVERS:
                        sites.add((rel, fn, nm))
                    if nm == "serve_untrusted":
                        calls_su[(rel, fn)] = calls_su.get((rel, fn), 0) + 1
                walk(ch, inner)
        walk(tree, "<module>")
    return sites, calls_su


def main():
    files, mods, orphans = domain()
    rels = {_rel(f) for f in files}
    check("DOMAIN every catch-all proxy route in main.py resolves to ONE declared upstream (none silently dropped)",
          not orphans and len(mods) >= 3, f"orphans {orphans}; resolved {sorted(mods)}")
    check("DOMAIN the proxied services are in it: canvas, ear and growbot's body (anti-vacuity)",
          {"bridges/canvas.py", "bridges/ear.py", "src/astryx/contrib/growbot_body.py"} <= rels, sorted(rels))

    got = writers(files)
    check(f"G2 the INSERT INTO messages sites over the domain are EXACTLY the expected {len(EXPECTED_WRITERS)} "
          f"(observatory/**.py + the proxied services; case-insensitive)", got == EXPECTED_WRITERS,
          f"new: {sorted(set(got) - set(EXPECTED_WRITERS))}; gone: {sorted(set(EXPECTED_WRITERS) - set(got))}; "
          f"counts {len(got)} vs {len(EXPECTED_WRITERS)}")
    with tempfile.TemporaryDirectory() as td:            # RED control: a sibling module's lowercase writer is caught
        planted = Path(td) / "sibling.py"
        planted.write_text('async def sneak(pool):\n    await pool.execute("insert  into messages (body) values ($1)", "x")\n')
        red = writers(files + [planted])
    check("G2 RED control: a planted sibling module with a lowercase insert is caught",
          len(red) == len(got) + 1 and any(fn == "sneak" for _, fn in red), red[-3:])
    ledger = json.loads((ROOT / "src/astryx/security/sqlguard/ledger.json").read_text())
    led = set()
    for part in ("rows", "covering"):
        for k in ledger.get(part, {}):
            f, _, rest = k.partition("::")
            fn, _, sql = rest.partition("\x1f")
            if f in rels and INSERT.search(sql):
                led.add((f, fn))
    check("G2 second instrument: every sqlguard ledger row that writes messages in the domain is in the text census",
          led <= set(got) and len(led) > 0, f"ledger-only: {sorted(led - set(got))}; ledger {sorted(led)}")

    sites, su = servers(files)
    unclassified = sorted(s for s in sites if s not in CLASSIFIED)
    check("G3 every FileResponse / StreamingResponse / StaticFiles in the domain is classified with its reason "
          "(no second hand-written server of untrusted bytes)", not unclassified, unclassified)
    stale = sorted(k for k in CLASSIFIED if k not in sites)
    check("G3 the classification names only sites that exist (no stale exemption)", not stale, stale)
    missing = [r for r in UNTRUSTED_ROUTES if not su.get(r)]
    check("G3 the untrusted-byte routes answer through serve_untrusted: /api/chat/file, canvas /api/file and its preview",
          not missing, missing)

    web = ROOT / "observatory" / "web" / "src"
    leaks = []
    for f in list(web.rglob("*.ts")) + list(web.rglob("*.tsx")):
        for i, ln in enumerate(f.read_text().splitlines(), 1):
            if "/api/chat/file" in ln and re.search(r"[?&]key=|\bkey=", ln):
                leaks.append(f"{f.relative_to(ROOT)}:{i}")
    check("CLIENT (a1 BC-2) no URL the page builds for /api/chat/file carries key=", not leaks, leaks)
    print(f"\n{'PASS' if not fails else 'FAIL'}: owner surface ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
