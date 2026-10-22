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


OBJ = re.compile(r"createObjectURL")     # every MENTION (a3 #62247): URL['createObjectURL'], .bind(URL), a destructure
MEDIA_SRC = re.compile(r"(?:^|[^\w.])((?:this\.)?\w+)\.src\s*=\s*$")
MEDIA_DECL = r"\b{name}\s*(?::\s*HTML(?:Audio|Video|Image)Element\b|=\s*(?:new\s+(?:Audio|Image)\s*\(|document\.createElement\(\s*['\"](?:audio|video|img)['\"]))"


def object_url_class(src, at):
    """C5 (a3 #62226 R2): an object URL made on the front's page carries the front's ORIGIN and NO response header, so it
    is safe only as (a) the src of an element the file shows to be audio/video/img, or (b) the href of an anchor that is
    also given `download`. Anything else is accused. -> 'media' | 'download' | None."""
    if not re.match(r"createObjectURL\s*\(", src[at:]) or not re.search(r"\bURL\.\s*$", src[max(0, at - 8):at]):
        return None                              # only the plain call `URL.createObjectURL(` can be classed at all
    at = src.rfind("URL.", 0, at)                # classify from the call's start, as its context reads it
    head = src[max(0, at - 200):at]
    line_start = src.rfind("\n", 0, at) + 1
    before = src[line_start:at]
    jsx = src.rfind("<", 0, at)
    tag = re.match(r"<\s*(\w+)", src[jsx:at]) if jsx >= 0 and ">" not in src[jsx:at] else None
    if tag and tag.group(1) in ("audio", "video", "img", "source") and re.search(r"\bsrc\s*=\s*\{[^}]*$", src[jsx:at]):
        return "media"
    m = MEDIA_SRC.search(before)
    if m:
        name = m.group(1).split(".")[-1]
        if re.search(MEDIA_DECL.format(name=re.escape(name)), src):
            return "media"
        return None
    v = re.search(r"(?:const|let|var)\s+(\w+)\s*=\s*$", before)
    if v:
        rest = src[at:at + 500]
        a = re.search(rf"\b(\w+)\.href\s*=\s*{re.escape(v.group(1))}\b", rest)
        if a and re.search(rf"\b{re.escape(a.group(1))}\.download\s*=", rest) \
                and re.search(rf"\b{re.escape(a.group(1))}\s*=\s*document\.createElement\(\s*['\"]a['\"]", src[max(0, at - 50):at + 500]):
            return "download"
    del head
    return None


RAW = re.compile(r"\.(?:innerHTML|outerHTML)\s*=(?!=)|insertAdjacentHTML\s*\(|document\.write(?:ln)?\s*\(|<object\b|"
                 r"<embed\b|(?<![\w.])eval\s*\(|new\s+Function\s*\(|"
                 # a3 #62247: HTML parsed into live nodes. createContextualFragment runs its scripts once appended;
                 # DOMParser's nodes fire <img onerror> once adopted; setHTMLUnsafe/setHTML write markup
                 r"createContextualFragment\s*\(|\bDOMParser\b|\.setHTMLUnsafe\s*\(|\.setHTML\s*\(")


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
    out = {"C1": [], "C2": [], "C3": [], "C4": [], "C5": []}
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
        for m in OBJ.finditer(src):
            if object_url_class(src, m.start()) is None:
                out["C5"].append(f"{rel}:{line(m.start())} an object URL neither a media src nor a download href")
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
        "C5 window.open of an object URL (a3's PlantBlob)": ("a.tsx",
            "const b = new Blob([html], {type: 'text/html'})\nwindow.open(URL.createObjectURL(b))", "C5", 1),
        "C5 an anchor to an object URL WITHOUT download": ("a.tsx",
            "<a href={URL.createObjectURL(b)} target=\"_blank\">open</a>", "C5", 1),
        "C5 an iframe src of an object URL": ("a.tsx", "<iframe sandbox='' src={URL.createObjectURL(b)} />", "C5", 1),
        "C5 an audio element's src (room.tsx's shape)": ("a.ts",
            "class R {\n  private el = new Audio()\n  async p(r) { this.el.src = URL.createObjectURL(await r.blob()) }\n}", "C5", 0),
        "C5 a .src on an element NOT shown to be media": ("a.ts", "frame.src = URL.createObjectURL(b)", "C5", 1),
        "C5 a JSX <img src> of an object URL": ("a.tsx", "<img alt='' src={URL.createObjectURL(b)} />", "C5", 0),
        "C5 a download anchor (SqlView's shape)": ("a.ts",
            "function d(n, t) {\n  const url = URL.createObjectURL(new Blob([t], { type: 'text/csv' }))\n"
            "  const a = document.createElement('a')\n  a.href = url\n  a.download = n\n  a.click()\n}", "C5", 0),
        "C5 the same anchor without download": ("a.ts",
            "function d(n, t) {\n  const url = URL.createObjectURL(b)\n  const a = document.createElement('a')\n"
            "  a.href = url\n  a.click()\n}", "C5", 1),
        "C3 createContextualFragment (its scripts run when appended)": ("a.ts",
            "document.body.append(document.createRange().createContextualFragment(html))", "C3", 1),
        "C3 DOMParser HTML adopted into the page": ("a.ts",
            "const d = new DOMParser().parseFromString(html, 'text/html'); el.append(...d.body.childNodes)", "C3", 1),
        "C3 setHTMLUnsafe / setHTML": ("a.ts", "el.setHTMLUnsafe(h); el.setHTML(h)", "C3", 2),
        "C5 a bracketed URL['createObjectURL'](b) (a3's PlantBlob2 i)": ("a.ts", "window.open(URL['createObjectURL'](b))", "C5", 1),
        "C5 a bound createObjectURL (a3's PlantBlob2 ii)": ("a.ts",
            "const mk = URL.createObjectURL.bind(URL)\nwindow.open(mk(b))", "C5", 1),
        "C5 a destructured createObjectURL": ("a.ts", "const { createObjectURL } = URL\nwindow.open(createObjectURL(b))", "C5", 2),
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
                       ("C4", "every dangerouslySetInnerHTML is DOMPurify.sanitize's output"),
                       ("C5", "every object URL is a media src or a download href (it carries the origin, no headers)")):
        check(f"LIVE {rule}: {what}", not found[rule], "; ".join(found[rule]))
    stale = [f for f in EXEMPT if not (ROOT / f).exists()]
    check("EXEMPT names only files that exist (a stale exemption is a finding)", not stale, str(stale))
    server(ROOT)
    print(f"\n{'FAIL' if fails else 'PASS'}: active content ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
