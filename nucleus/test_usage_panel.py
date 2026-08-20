#!/home/umair/astryx/venv/bin/python
"""Gates for the observatory usage panel (goal #2470, plan-2470 quorum 4/4 @ msg 12363).

Exit 0 = all gates ran and passed. 1 = a gate failed. 77 = a gate could not RUN
(automake SKIP convention) — a gate that did not run is NOT a pass, and this file names
every one it could not run rather than reporting a count.
"""
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

FAIL, SKIP = [], []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def skip(name, why):
    print(f"  SKIP  {name}  — {why}")
    SKIP.append(f"{name} ({why})")


# ── comment stripping ────────────────────────────────────────────────────────────────
# A CHECK MUST SCAN WHAT EXECUTES, NOT WHAT IS WRITTEN ABOUT IT. This file's own subject
# documents the credential path in its docstring, and `usage_view.py` names it too — in
# a comment explaining that it must never read it. Grepping raw source would flag both
# and the gate would be measuring prose. A comment can neither execute nor fail a build,
# so it must not be able to pass or fail one either.
def strip_comments(path: Path) -> str:
    src = path.read_text(errors="replace")
    if path.suffix == ".py":
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return src
        # blank out docstrings, then drop `#` comments line-wise
        drop = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                b = getattr(node, "body", None)
                if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                        and isinstance(b[0].value.value, str):
                    for ln in range(b[0].lineno, (b[0].end_lineno or b[0].lineno) + 1):
                        drop.add(ln)
        out = []
        for i, line in enumerate(src.splitlines(), 1):
            if i in drop:
                continue
            out.append(re.sub(r"#.*$", "", line))
        return "\n".join(out)
    if path.suffix in (".mjs", ".js"):
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        return re.sub(r"//.*$", "", src, flags=re.M)
    if path.suffix == ".sh" or path.suffix == "":
        return re.sub(r"#.*$", "", src, flags=re.M)
    return src


# A GUARD KEYED ON A SPELLING PASSES EVERY OTHER SPELLING OF THE SAME ACT. The credential
# read has at least four forms — `Path.home()/".claude"/".credentials.json"`, an absolute
# literal, an env indirection, a relative form. Key on the FILENAME and the `.claude`
# COMPONENT together, and treat any construction reaching that directory as a hit.
CRED_FILE = re.compile(r"\.credentials\.json")
CLAUDE_COMPONENT = re.compile(r"""(?x)
      ['"]\.claude['"]          # a quoted path SEGMENT: Path.home()/".claude"/...
    | \.claude/                 # a slash-joined path:   ~/.claude/.credentials.json
    | \$HOME/\.claude           # shell
    | \.claude['"]?\s*\)        # os.path.join(..., ".claude")
""")

# THE DETECTOR MATCHES ITSELF, and an exemption manifest is the right instrument.
# This file carries the credential pattern as a REGEX LITERAL in executable code, so
# comment-stripping cannot clear it and nothing should: the pattern is the point. By the
# omission-polarity law this build ships, an EXEMPTION set is the safe kind of
# hand-maintained set — forget to add a member and it gets ACCUSED, which is fail-closed.
# The exemption is not taken on trust: _exemption_is_honest() re-checks that the exempted
# file performs no actual read of the credential, so the manifest can never launder one.
CRED_EXEMPT = {
    "nucleus/test_usage_panel.py":
        "the detector itself — holds the pattern as a regex literal, reads nothing",
}


def _exemption_is_honest(path: Path) -> bool:
    r"""An exemption may excuse a MENTION; it may never excuse a READ. Re-derive rather
    than trust the manifest: no call that opens a path built from the credential.

    PARSE THE SURFACE IN ITS OWN LANGUAGE. The first version of this was a regex —
    `(open|read_text)\s*\([^)]*credentials` — and a mutant walked straight through it,
    because `[^)]*` cannot cross the `)` in `Path.home()` and every realistic spelling of
    this read has a nested call in it. The unit of a python expression is the NODE, not a
    run of characters between two parens."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return False              # unparseable = BLIND, and blind is not honest
    src = path.read_text(errors="replace")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in ("open", "read_text", "read_bytes"):
            continue
        seg = ast.get_source_segment(src, node) or ""
        if "credentials" in seg:
            return False
    return True


SCAN_EXT = (".py", ".mjs", ".js", ".sh")
SCAN_SKIP = ("/venv/", "/node_modules/", "/.git/", "/backups/", "/var/")


def estate_files():
    for p in sorted(REPO.rglob("*")):
        if not p.is_file() or p.suffix not in SCAN_EXT:
            continue
        s = str(p)
        if any(x in s for x in SCAN_SKIP):
            continue
        yield p


def main():
    print("usage panel gates (goal #2470)\n")

    # ── BC-2 (1) TOTAL, ESTATE-WIDE ──────────────────────────────────────────────────
    # Not "observatory has none" — ONE NAMED WRITER of the credential read, estate-wide.
    # (1) is what makes (2) cheap, AND it fails loudly if a SECOND reader appears
    # anywhere, which is exactly the case where "which process is it in" stops being
    # answerable by reading one import graph.
    readers = []
    for p in estate_files():
        body = strip_comments(p)
        if CRED_FILE.search(body) and CLAUDE_COMPONENT.search(body):
            rel = str(p.relative_to(REPO))
            if rel in CRED_EXEMPT:
                if not _exemption_is_honest(p):
                    FAIL.append(f"exemption laundering a real read: {rel}")
                    print(f"  FAIL  exemption for {rel} hides an actual credential read")
                continue
            readers.append(rel)
    check("BC-2(1) exactly one credential reader estate-wide",
          readers == ["nucleus/usage_refresh.py"],
          f"found {readers or 'none'}")

    # ── BC-2 (2) CLOSURE ─────────────────────────────────────────────────────────────
    # The refresher must not be reachable in the observatory app's import graph. Walk it
    # statically rather than importing the app (importing would need a live DB).
    def imports_of(path: Path) -> set:
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except Exception:
            return set()
        out = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                out |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                out |= {f"{n.module}.{a.name}" for a in n.names} | {n.module}
        return out

    app = REPO / "observatory" / "api" / "main.py"
    if not app.exists():
        skip("BC-2(2) refresher not in observatory import closure", "observatory/api/main.py absent")
    else:
        seen, frontier = set(), {"observatory.api.main"}
        local = {}
        for p in estate_files():
            if p.suffix == ".py":
                rel = p.relative_to(REPO).with_suffix("")
                local[".".join(rel.parts)] = p
        frontier = imports_of(app)
        while frontier:
            m = frontier.pop()
            if m in seen:
                continue
            seen.add(m)
            if m in local:
                frontier |= imports_of(local[m]) - seen
        check("BC-2(2) refresher NOT in observatory import closure",
              "nucleus.usage_refresh" not in seen,
              "usage_refresh reachable from the app")
        check("BC-2(2b) the read side IS reachable (the panel actually works)",
              "nucleus.usage_view" in seen or "nucleus" in seen,
              "usage_view unreachable — endpoint would 500")

    # ── GATE BY OMISSION ─────────────────────────────────────────────────────────────
    src = app.read_text() if app.exists() else ""
    m = re.search(r"PUBLIC_PATHS\s*=\s*\{(.*?)\}", src, re.S)
    if not m:
        skip("/api/usage is owner-gated by omission", "PUBLIC_PATHS not found")
    else:
        check("/api/usage is owner-gated by omission from PUBLIC_PATHS",
              "/api/usage" not in m.group(1), "it is listed PUBLIC")

    # ── TIER: no money leaves, ever ──────────────────────────────────────────────────
    from nucleus import usage_refresh, usage_view
    money = ("dollar", "spend", "amount_minor", "credit", "balance", "currency")
    allow_blob = json.dumps(usage_refresh.USAGE_ALLOWLIST) + json.dumps(usage_refresh.LIMITS_ALLOWLIST)
    check("no money field in the egress allowlist (owner finances are tier)",
          not any(w in allow_blob.lower() for w in money),
          allow_blob)

    # ── BC-3 NOT-CONFIGURED: the modal state across the population ───────────────────
    # Drive it with no credential present: no cache written, nothing archived, and the
    # panel refuses to render a number it cannot date.
    with tempfile.TemporaryDirectory() as td:
        real_cred, real_cache, real_status = (usage_refresh.CRED, usage_refresh.CACHE,
                                              usage_refresh.STATUS)
        vreal_cache, vreal_status = usage_view.CACHE, usage_view.STATUS
        try:
            usage_refresh.CRED = Path(td) / "absent" / ".credentials.json"
            usage_refresh.CACHE = usage_view.CACHE = Path(td) / "usage_cache.json"
            usage_refresh.STATUS = usage_view.STATUS = Path(td) / "usage_status.json"
            r = usage_refresh.refresh()
            check("BC-3 no credential -> state not_configured", r["state"] == "not_configured", str(r))
            check("BC-3 no credential -> NO cache written", r["wrote_cache"] is False, str(r))
            check("BC-3 no credential -> cache file absent on disk",
                  not usage_refresh.CACHE.exists())
            v = usage_view.read_cache()
            check("BC-3 view reports not_configured", v["state"] == "not_configured", str(v))
            check("BC-3 view renders NO number it cannot date",
                  v["data"] is None and v["renderable"] is False, str(v))

            # never-render-an-undated-number, driven over every non-renderable state
            for st in ("stale", "unreadable", "unparseable", "not_configured"):
                usage_refresh.CACHE.write_text(json.dumps(
                    {"fetched_at": "2020-01-01T00:00:00+00:00", "state": st,
                     "data": {"five_hour_utilization": 99.0}}))
                usage_view.STATUS.write_text(json.dumps({"state": st, "checked_at": "x"}))
                vv = usage_view.read_cache()
                check(f"undated/non-renderable state '{st}' yields no numbers",
                      vv["data"] is None, str(vv))
            # and a genuinely fresh one DOES render — a negative suite that never shows
            # the positive is also what a totally broken reader produces
            from datetime import datetime, timezone
            usage_refresh.CACHE.write_text(json.dumps(
                {"fetched_at": datetime.now(timezone.utc).isoformat(), "state": "fresh",
                 "data": {"five_hour_utilization": 41.0}}))
            usage_view.STATUS.write_text(json.dumps({"state": "fresh", "checked_at": "x"}))
            vv = usage_view.read_cache()
            check("POSITIVE CONTROL: a fresh dated cache DOES render its number",
                  vv["data"] and vv["data"].get("five_hour_utilization") == 41.0, str(vv))
        finally:
            usage_refresh.CRED, usage_refresh.CACHE, usage_refresh.STATUS = (
                real_cred, real_cache, real_status)
            usage_view.CACHE, usage_view.STATUS = vreal_cache, vreal_status

    # ── SHAPE-CHANGED tests membership, not truthiness ───────────────────────────────
    # BC-1 measured this: the upstream nulls an inapplicable rung rather than dropping
    # the key. A guard keyed on truthiness would fire on every idle model and demote the
    # authoritative gauge during ordinary use.
    # Call the REAL predicate. An earlier draft of this file re-implemented the
    # membership test here and would have passed while the shipped code did anything at
    # all — a test conforming to its own restatement, never to the subject.
    full = set(usage_refresh.STRUCTURAL_KEYS)
    body = {"five_hour": {"utilization": 5.0}, "seven_day": None, "limits": [],
            "extra_usage": None}
    check("SHAPE-CHANGED ignores null-valued structural keys (membership, not truthiness)",
          usage_refresh.shape_missing(body, full) == [],
          f"nulls misread as missing: {usage_refresh.shape_missing(body, full)}")
    check("SHAPE-CHANGED still fires on a genuinely absent structural key",
          "seven_day" in usage_refresh.shape_missing({"five_hour": {}}, full))

    # ── the baseline contract, which already rotted once IN SILENCE ─────────────────
    # The first implementation globbed `*.json` against an archive declared `*.jsonl` and
    # whole-file-parsed a line-delimited series. It read nothing, reported "none", and
    # would have left SHAPE-CHANGED dormant forever with no error anywhere. The gate that
    # matters is therefore not "does a good baseline work" but "is every REFUSAL NAMED" —
    # a bare empty set is what made the defect invisible.
    import datetime as _dt
    with tempfile.TemporaryDirectory() as td3:
        real_arch, real_base = usage_refresh.ARCHIVE, usage_refresh.BASELINE
        try:
            usage_refresh.ARCHIVE = Path(td3)
            usage_refresh.BASELINE = Path(td3) / "baseline.json"
            now = _dt.datetime.now(_dt.timezone.utc)

            def _write(**kw):
                usage_refresh.BASELINE.write_text(json.dumps(kw))

            check("baseline absent -> named 'none', not a crash",
                  usage_refresh.baseline_keys() == (set(), "none"))

            # THE REGRESSION: a raw JSONL series present but no derived baseline must be
            # 'none' — and must never be mistaken for a populated baseline.
            (Path(td3) / "2026-08.jsonl").write_text(
                json.dumps({"observed_keys": ["five_hour"]}) + "\n")
            check("raw *.jsonl series alone -> still 'none' (we do not parse memory's format)",
                  usage_refresh.baseline_keys() == (set(), "none"))

            _write(keys=["five_hour", "seven_day"], sample_count=40, min_samples=30,
                   generated_at=now.isoformat())
            ks, src = usage_refresh.baseline_keys()
            check("POSITIVE CONTROL: a well-formed baseline ARMS the detector",
                  src == "baseline" and ks == {"five_hour", "seven_day"}, f"{src} {ks}")
            check("armed baseline actually fires shape_missing on an absent key",
                  usage_refresh.shape_missing({"five_hour": {}}, ks) == ["seven_day"])

            _write(keys=["five_hour"], sample_count=3, min_samples=30,
                   generated_at=now.isoformat())
            check("under-powered baseline -> named 'insufficient', dormant",
                  usage_refresh.baseline_keys() == (set(), "insufficient"))

            _write(keys=["five_hour"], sample_count=40, min_samples=30,
                   generated_at=(now - _dt.timedelta(days=30)).isoformat())
            check("stale baseline -> named 'stale', dormant",
                  usage_refresh.baseline_keys() == (set(), "stale"))

            usage_refresh.BASELINE.write_text("{not json")
            check("unparseable baseline -> named 'unreadable', dormant",
                  usage_refresh.baseline_keys() == (set(), "unreadable"))

            _write(keys="five_hour", sample_count=40, min_samples=30, generated_at=now.isoformat())
            check("malformed keys field -> named 'unreadable', dormant",
                  usage_refresh.baseline_keys() == (set(), "unreadable"))

            # every refusal must be DISTINGUISHABLE — a single catch-all would have hidden
            # the original defect just as well as the silent empty set did
            usage_refresh.BASELINE.unlink(missing_ok=True)
            names = {usage_refresh.baseline_keys()[1]}
            for kw, want in ((dict(keys=["a"], sample_count=1, min_samples=9,
                                   generated_at=now.isoformat()), "insufficient"),
                             (dict(keys=["a"], sample_count=9, min_samples=1,
                                   generated_at=(now - _dt.timedelta(days=99)).isoformat()),
                              "stale")):
                _write(**kw)
                names.add(usage_refresh.baseline_keys()[1])
            check("refusal reasons are distinct, not one catch-all",
                  len(names) >= 3, str(names))
        finally:
            usage_refresh.ARCHIVE, usage_refresh.BASELINE = real_arch, real_base

    # ── the token must never appear in any artifact this build writes ────────────────
    st, tok = usage_refresh.read_credential()
    if st != "ok" or not tok:
        skip("token absent from all written artifacts", f"no live credential ({st})")
    else:
        # EXERCISE THE WRITERS; do not scan artifacts they wrote on some earlier run.
        # The first version of this read the status file off disk and a mutant that put
        # the token INTO _write_status survived untouched, because the oracle never ran
        # the writer — it graded a stale artifact. Existence is not execution.
        with tempfile.TemporaryDirectory() as td2:
            rc, rs = usage_refresh.CACHE, usage_refresh.STATUS
            try:
                usage_refresh.CACHE = Path(td2) / "c.json"
                usage_refresh.STATUS = Path(td2) / "s.json"
                usage_refresh._write_status("fresh", None, reason=None)
                blobs = [f.read_text() for f in (usage_refresh.CACHE, usage_refresh.STATUS)
                         if f.exists()]
            finally:
                usage_refresh.CACHE, usage_refresh.STATUS = rc, rs
        for f in (usage_refresh.CACHE, usage_refresh.STATUS):
            if f.exists():
                blobs.append(f.read_text())
        blobs.append(json.dumps(usage_view.read_cache()))
        check("token never appears in cache/status/served payload (writers EXERCISED)",
              not any(tok in b for b in blobs))
        check("scrubber removes a bearer token from an exception string",
              tok not in usage_refresh._scrub(f"boom Authorization: Bearer {tok}", tok))

    # ── verdict ──────────────────────────────────────────────────────────────────────
    print()
    if FAIL:
        print(f"FAILED ({len(FAIL)}): " + "; ".join(FAIL))
        return 1
    if SKIP:
        # A SKIP IS NOT A PASS and an aggregate verdict may never out-claim its parts:
        # name every gate that did not run, because a count never makes anyone go look.
        print(f"NOT RUN ({len(SKIP)}): " + "; ".join(SKIP))
        print("some gates could not run — exit 77 (SKIP), not a pass")
        return 77
    print("all usage-panel gates ran and passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
