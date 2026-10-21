"""plan-11859 U0 (D6, BLOCKING from U0 per a2 BC-1): no org- or agent-authored ACTIVE content runs on the front's origin.

That origin holds the owner key in localStorage['obs_key'] (observatory/web/src/api.ts), so any script an agent or an
org authored and the browser runs there can read it. Today's surface (inventoried 10-22, every sink read) is clean;
this census pins it, so the next sink can't land unsandboxed:

CLIENT (observatory/web/src and canvas/web/src, every .ts/.tsx):
  C1 every <iframe> element (read WHOLE: JSX spans lines) carries a `sandbox` attribute, unless EXEMPT names the file
     with its reason. The one exemption: canvas's file viewer, whose server gate (S1) admits no active type.
  C2 no sandbox value anywhere grants allow-same-origin (a sandboxed frame with it is the page's own origin again).
  C3 no raw HTML sink at all: innerHTML/outerHTML assignment, insertAdjacentHTML, document.write, <object>, <embed>,
     eval(, new Function(.
  C4 every dangerouslySetInnerHTML's __html value is DOMPurify.sanitize's output: its identifier's nearest definition
     before the sink calls DOMPurify.sanitize, or calls a local function whose body does (two hops at most).
SERVER (bridges/canvas.py, observatory/api/main.py):
  S1 canvas's INLINE_TYPES (served inline with a GUESSED type) holds no active type (.html .htm .svg .xml .xhtml .js
     .mjs .xsl); TEXT_TYPES is served forced to text/plain.
  S2 every FileResponse of a non-build file sends X-Content-Type-Options: nosniff; an avatar's also sends a CSP sandbox.
  S3 the attachment branch of /api/file (a type guessed from an agent's filename) sends nosniff and a CSP sandbox, so
     a browser that ignores Content-Disposition still can't run it.
Each parser rule has paired fixture arms (a sink it must catch, a lookalike it must leave).

    venv/bin/python tests/test_active_content.py      (ACTIVE_ROOT: a planted tree, the fixture arms' channel)
"""
import ast
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("ACTIVE_ROOT") or REPO)
WEB = ("observatory/web/src", "canvas/web/src")
EXEMPT = {
    "canvas/web/src/Media.tsx": "the PDF/media viewer: a sandboxed frame can't run the browser's PDF viewer, and the "
                                "server lets only INLINE_TYPES into it (raster, PDF, media, all with nosniff): S1 pins "
                                "that no active type is among them",
}
ACTIVE = {".html", ".htm", ".svg", ".xml", ".xhtml", ".js", ".mjs", ".xsl"}
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def element(src, at):
    """The JSX element starting at `at` ('<tag'), to its closing '>' outside {…} and quotes."""
    depth, q, i = 0, None, at
    while i < len(src):
        c = src[i]
        if q:
            if c == q and src[i - 1] != "\\":
                q = None
        elif c in "'\"`":
            q = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth == 0:
            return src[at:i + 1]
        i += 1
    return src[at:]


RAW = re.compile(r"\.(?:innerHTML|outerHTML)\s*=(?!=)|insertAdjacentHTML\s*\(|document\.write(?:ln)?\s*\(|<object\b|"
                 r"<embed\b|(?<![\w.])eval\s*\(|new\s+Function\s*\(")


def sanitized(src, at, ident, hops=2):
    """Is `ident` (used at offset `at`) DOMPurify.sanitize's output: by its nearest prior definition, or through a
    local function that definition calls?"""
    defs = [m for m in re.finditer(rf"(?:const|let|var)\s+{re.escape(ident)}\s*=", src[:at])]
    if not defs:
        return False
    start = defs[-1].end()
    body = src[start:start + 600].split("\n\n")[0]
    if "DOMPurify.sanitize(" in body:
        return True
    if hops <= 1:
        return False
    for f in re.findall(r"\b([A-Za-z_]\w*)\s*\(", body):
        m = re.search(rf"\bfunction\s+{re.escape(f)}\s*\(|(?:const|let)\s+{re.escape(f)}\s*=\s*(?:\([^)]*\)|\w+)\s*=>",
                      src)
        if m:
            end = src.find("\n}", m.end())
            if "DOMPurify.sanitize(" in src[m.end():end if end > 0 else m.end() + 2000]:
                return True
    return False


def client_findings(files):
    """{rule: [file:line ...]} over (relpath, text) pairs."""
    out = {"C1": [], "C2": [], "C3": [], "C4": []}
    for rel, src in files:
        line = lambda i: src.count("\n", 0, i) + 1      # noqa: E731
        for m in re.finditer(r"<iframe\b", src):
            el = element(src, m.start())
            if not re.search(r"\bsandbox\s*=", el) and rel not in EXEMPT:
                out["C1"].append(f"{rel}:{line(m.start())}")
        for m in re.finditer(r"allow-same-origin", src):
            out["C2"].append(f"{rel}:{line(m.start())}")
        for m in RAW.finditer(src):
            out["C3"].append(f"{rel}:{line(m.start())} {m.group(0).strip()}")
        for m in re.finditer(r"dangerouslySetInnerHTML\s*=\s*\{\{\s*__html\s*:\s*(.*?)\s*\}\}", src, re.S):
            v = m.group(1)
            if not re.fullmatch(r"[A-Za-z_]\w*", v):
                out["C4"].append(f"{rel}:{line(m.start())} __html is an expression, not a sanitized name: {v[:40]}")
            elif not sanitized(src, m.start(), v):
                out["C4"].append(f"{rel}:{line(m.start())} __html: {v}")
    return out


def web_files(root):
    out = []
    for w in WEB:
        for p in sorted((root / w).rglob("*")):
            if p.suffix in (".ts", ".tsx") and "node_modules" not in p.parts and "dist" not in p.parts:
                out.append((str(p.relative_to(root)), p.read_text(errors="ignore")))
    return out


def fixtures():
    cases = {
        "C1 an iframe with no sandbox": ("a.tsx", "<iframe src={u} title='x' />", "C1", 1),
        "C1 sandbox on a LATER line of the element counts": ("a.tsx", "<iframe key={k}\n  title='t'\n  sandbox={S} srcDoc={h} />",
                                                            "C1", 0),
        "C1 a `>` inside {…} doesn't end the element": ("a.tsx", "<iframe onLoad={() => a > b}\n sandbox='' />", "C1", 0),
        "C2 allow-same-origin anywhere": ("a.tsx", "const S = 'allow-scripts allow-same-origin'", "C2", 1),
        "C3 innerHTML assignment": ("a.ts", "el.innerHTML = body", "C3", 1),
        "C3 a comparison is not an assignment": ("a.ts", "if (el.innerHTML == '') {}", "C3", 0),
        "C3 insertAdjacentHTML / document.write / eval": ("a.ts", "e.insertAdjacentHTML('x', h); document.write(h); eval(s)",
                                                         "C3", 3),
        "C3 `evaluate(` is not eval": ("a.ts", "evaluate(x); doc.evaluate(y)", "C3", 0),
        "C4 an unsanitized __html": ("a.tsx", "const h = marked.parse(t)\nreturn <div dangerouslySetInnerHTML={{ __html: h }} />",
                                     "C4", 1),
        "C4 sanitized at the definition": ("a.tsx", "const h = DOMPurify.sanitize(marked.parse(t))\n"
                                           "return <div dangerouslySetInnerHTML={{ __html: h }} />", "C4", 0),
        "C4 sanitized one call away (a local render())": (
            "a.tsx", "function render(md) {\n  const x = marked.parse(md)\n  return DOMPurify.sanitize(x)\n}\n"
                     "const h = useMemo(() => render(t), [t])\nreturn <div dangerouslySetInnerHTML={{ __html: h }} />", "C4", 0),
        "C4 an inline expression, not a sanitized name": ("a.tsx", "<div dangerouslySetInnerHTML={{ __html: marked.parse(t) }} />",
                                                         "C4", 1),
    }
    for name, (rel, src, rule, want) in cases.items():
        got = client_findings([(rel, src)])[rule]
        check(f"parser: {name} → {want} finding(s)", len(got) == want, str(got))
    got = client_findings([("canvas/web/src/Media.tsx", "<iframe src={src} title='x' />")])["C1"]
    check("parser: an EXEMPT file's unsandboxed iframe is not a finding (its reason is S1)", got == [], str(got))


def server(root):
    cv = Path(os.environ.get("ACTIVE_CANVAS_SRC") or root / "bridges" / "canvas.py").read_text()   # the probe's channel
    tree = ast.parse(cv)
    sets = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id in ("INLINE_TYPES", "TEXT_TYPES") and isinstance(n.value, ast.Set):
            sets[n.targets[0].id] = {e.value for e in n.value.elts if isinstance(e, ast.Constant)}
    check("S1: canvas's INLINE_TYPES (inline, with a GUESSED type) holds no active type",
          "INLINE_TYPES" in sets and not (sets["INLINE_TYPES"] & ACTIVE), str(sets.get("INLINE_TYPES")))
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "message_file"), None)
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "FileResponse"] if fn else []
    text_ok = any("TEXT_TYPES" in ast.unparse(i.test) and "text/plain" in ast.unparse(i)
                  for i in ast.walk(fn) if isinstance(i, ast.If)) if fn else False
    check("S1: TEXT_TYPES are served forced to text/plain", text_ok)
    last = max(calls, key=lambda c: c.lineno) if calls else None      # the fall-through, by SOURCE order
    lt = ast.unparse(last) if last else ""
    check("S3: /api/file's attachment branch (a type guessed from an agent's filename) sends nosniff AND a CSP sandbox",
          last is not None and "content_disposition_type" not in lt and "nosniff" in lt and "sandbox" in lt, lt)
    bad = []
    for path in ("bridges/canvas.py", "observatory/api/main.py"):
        t = ast.parse(cv if path == "bridges/canvas.py" else (root / path).read_text())
        for c in ast.walk(t):
            if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "FileResponse":
                s = ast.unparse(c)
                if "DIST" in s:
                    continue                                   # the app's own build output, not authored content
                if "nosniff" not in s:
                    bad.append(f"{path}:{c.lineno} no nosniff")
                if "_AVATAR" in s and "sandbox" not in s:
                    bad.append(f"{path}:{c.lineno} an avatar without a CSP sandbox")
    check("S2: every FileResponse of a non-build file sends nosniff; an avatar's also a CSP sandbox", not bad,
          "; ".join(bad))


def main():
    fixtures()
    files = web_files(ROOT)
    found = client_findings(files)
    check(f"LIVE: the census read the two web apps ({len(files)} .ts/.tsx files; anti-vacuity: both trees present)",
          len(files) > 20 and any(r.startswith(WEB[0]) for r, _ in files) and any(r.startswith(WEB[1]) for r, _ in files))
    for rule, what in (("C1", "every iframe is sandboxed or EXEMPT with its reason"),
                       ("C2", "no sandbox grants allow-same-origin"),
                       ("C3", "no raw HTML sink (innerHTML=, insertAdjacentHTML, document.write, object/embed, eval)"),
                       ("C4", "every dangerouslySetInnerHTML is DOMPurify.sanitize's output")):
        check(f"LIVE {rule}: {what}", not found[rule], "; ".join(found[rule]))
    stale = [f for f in EXEMPT if not (ROOT / f).exists()]
    check("EXEMPT names only files that exist (a stale exemption is a finding)", not stale, str(stale))
    server(ROOT)
    print(f"\n{'FAIL' if fails else 'PASS'}: active content ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
