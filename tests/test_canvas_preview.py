#!/usr/bin/env python3
"""Oracle: `canvas.py preview` (src/astryx/core/canvas.py) — the page in the real shell, screenshotted, READ-ONLY.

Hermetic by construction: every arm but one feeds preview an injected data source (`load=`), so no
row is read or written; the outdirs are throwaway temp dirs. The one LIVE arm runs the real CLI
against an existing canvas and proves its data is byte-identical after a --set preview; it is
NOT RUN (exit 77) where the DB is unreachable. Chromium is a host dependency: without it the
screenshot arms verify nothing, so the suite exits 77 after the arms that need no browser.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_canvas_preview", REPO, deps=("psycopg",))   # a committed-only tree (no venv): 77, not an import crash
from astryx.core import canvas as cv  # noqa: E402

fails, skipped = 0, []
TMP = Path(tempfile.mkdtemp(prefix="test-cv-preview-"))


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def skip(name, why):
    skipped.append(name)
    print(f"  SKIP  {name}  — {why}")


def page(name, html):
    p = TMP / f"{name}.html"
    p.write_text(html)
    return str(p)


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cv.main(argv)
    return rc, out.getvalue(), err.getvalue()


def no_browser():
    print("no browser (e)")
    real, cv.browser = cv.browser, lambda: None
    loaded = []
    try:
        rc, out, err = run_main(["preview", "2", page("nb", "<p>x</p>"), str(TMP / "nb")])
        arm("resolver says none: preview exits non-zero with a plain message naming chromium",
            rc != 0 and "chromium" in err, (rc, err))
        try:
            cv.preview(2, page("nb", "<p>x</p>"), str(TMP / "nb2"), load=lambda c: loaded.append(c) or {})
            arm("the library raises too, before reading any data", False)
        except cv.CanvasError:
            arm("the library raises too, before reading any data", loaded == [] and not (TMP / "nb2").exists())
    finally:
        cv.browser = real
    env = {**os.environ, "PATH": str(TMP / "empty-path")}
    r = subprocess.run([sys.executable, str(REPO / "src/astryx/core/canvas.py"), "preview", "2", page("nb", "<p>x</p>")],
                       capture_output=True, text=True, env=env, timeout=60)
    arm("PATH stripped of chromium: the CLI exits non-zero, says so, renders nothing",
        r.returncode != 0 and "chromium" in r.stderr and not r.stdout.strip(), (r.returncode, r.stderr[-300:]))


def isolation():
    print("isolation (publish never depends on preview)")
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import astryx.core.canvas; "
                        "print(sorted(m for m in ('http.server', 'bridges.canvas_shell') if m in sys.modules))"
                        % str(REPO)], capture_output=True, text=True, timeout=60)
    arm("importing src/astryx/core/canvas.py loads neither the kit server nor the shell (preview is lazy)",
        r.returncode == 0 and r.stdout.strip() == "[]", (r.stdout, r.stderr[-300:]))


def screenshots():
    src = {"title": "Probe", "nest": {"n": 1, "keep": [1, 2]}}
    before = json.dumps(src, sort_keys=True)
    print("screenshots (chromium)")
    pngs, errs = cv.preview(9, page("boom", "<p>x</p><script>throw new Error('boom')</script>"), str(TMP / "a"),
                            load=lambda c: src)
    arm("(a) a page that throws: >=1 error, and it names the throw", any("boom" in e for e in errs), errs)

    pngs, errs = cv.preview(9, page("clean", "<div class='cv-card' id=o></div><script>astryx.data.all()"
                                    ".then(d => o.textContent = JSON.stringify(d))</script>"),
                            str(TMP / "b"), load=lambda c: src)
    arm("(b) a clean page: 0 errors", errs == [], errs)
    arm("(b) exactly 3 PNGs, each a real non-empty file", len(pngs) == 3 and all(p.is_file() and p.stat().st_size > 1000
        for p in pngs) and sorted(x.name for x in (TMP / "b").glob("*.png")) == ["desktop.png", "phone.png", "reduced.png"],
        [(p, p.exists() and p.stat().st_size) for p in pngs])

    pngs, errs = cv.preview(9, page("set", "<p>x</p>"), str(TMP / "c"),
                            [("nest.n", 99), ("nest.deep.k", "v"), ("title", "forced")], load=lambda c: src)
    doc = (TMP / "c" / "preview.html").read_text()
    arm("(c) --set reaches into nested keys IN THE STUB", '"n": 99' in doc and '"deep": {"k": "v"}' in doc
        and '"title": "forced"' in doc, doc[-400:])
    arm("(c) READ-ONLY: the injected source is byte-identical after a --set preview",
        json.dumps(src, sort_keys=True) == before, json.dumps(src))

    pngs, errs = cv.preview(9, page("csp", '<p>x</p><script src="https://example.com/x.js"></script>'),
                            str(TMP / "d"), load=lambda c: src)
    doc = (TMP / "d" / "frame.html").read_text()
    arm("(d) the shell's CSP is unchanged: connect-src none, no https: source",
        "connect-src &#x27;none&#x27;" in doc and "https:" not in doc.split("Content-Security-Policy")[1].split(">")[0])
    arm("(d) an off-box script is BLOCKED and preview surfaces the CSP violation",
        any(e.startswith("CSP-BLOCKED") and "example.com/x.js" in e for e in errs), errs)

    pngs, errs = cv.preview(9, page("tmp", "<p>x</p>"), None, load=lambda c: {})
    out = pngs[0].parent
    arm("(4) no outdir: a fresh cv-preview-* temp dir, outside the repo",
        out.name.startswith("cv-preview-") and REPO not in out.resolve().parents, out)
    shutil.rmtree(out, ignore_errors=True)


def centre_rgb(png):
    """The centre pixel of a PNG, stdlib only (zlib), so the containment arm needs no image library and is
    proven wherever chromium runs (steward #42008). Chromium writes 8-bit, non-interlaced RGB/RGBA; any
    other format RAISES, so an unreadable screenshot is a crash, never a 'not red' pass."""
    import struct
    import zlib
    data = Path(png).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{png}: not a PNG")
    pos, idat, hdr = 8, [], None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + n
    w, h, depth, ctype, _, _, interlace = hdr
    if depth != 8 or ctype not in (2, 6) or interlace:
        raise ValueError(f"{png}: unsupported PNG (depth {depth}, colour type {ctype}, interlace {interlace})")
    bpp = 3 if ctype == 2 else 4
    stride, raw = w * bpp, zlib.decompress(b"".join(idat))
    prev = bytearray(stride)
    for y in range(h // 2 + 1):  # rows unfilter top-down, each against the one above
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif f != 0:
                raise ValueError(f"{png}: bad filter type {f} on row {y}")
        prev = line
    x = (w // 2) * bpp
    return tuple(prev[x:x + 3])


def red(png):
    """True when the screenshot's centre is pure red (the canary's colour)."""
    r, g, b = centre_rgb(png)
    return r > 230 and g < 30 and b < 30


def containment():
    """abstractor-3 #41769: CSP does not govern navigation, and preview runs on THIS host. A page (or
    guest-written data rendered as HTML) must not pull a host file into a screenshot, nor reach a host port."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import urllib.request
    print("containment (navigation; production sandbox)")
    hits = []

    class Listen(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200); self.end_headers(); self.wfile.write(b"<body style='background:#f00'>")

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Listen)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/control", timeout=5).read()
        arm("control: the listener counts a direct GET", hits == ["/control"], hits)
        hits.clear()
        cv.preview(9, page("nav", f"<script>location.href='http://127.0.0.1:{port}/leak?d='+Date.now()</script>"),
                   str(TMP / "f1"), load=lambda c: {"secret": "x"})
        arm("(f) a page navigating to a host port reaches it 0 times", hits == [], hits)
    finally:
        srv.shutdown(); srv.server_close()

    full = "<div style='position:fixed;inset:0;background:#f00'></div>"
    pngs, _ = cv.preview(9, page("redctl", full), str(TMP / "f2"), load=lambda c: {})
    arm("control: the pixel probe sees a red page as red", red(pngs[0]), pngs[0])
    white = "<div style='position:fixed;inset:0;background:#fff'></div>"
    wpngs, _ = cv.preview(9, page("whitectl", white), str(TMP / "f2w"), load=lambda c: {})
    arm("control: the pixel probe reads a white page as exactly white, not red",
        centre_rgb(wpngs[0]) == (255, 255, 255) and not red(wpngs[0]), centre_rgb(wpngs[0]))
    try:
        from PIL import Image
    except ImportError:
        print("  note  stdlib reader not cross-checked against Pillow (absent); the two controls above pin it")
    else:
        busy = ("<div style='position:fixed;inset:0;background:linear-gradient(37deg,#123,#f80 40%,#0c9 60%,#eee)'>"
                + "<p style='font-size:31px;color:#a0f'>" + "medic ÿ 0123 " * 40 + "</p></div>")
        cv.preview(9, page("busy", busy), str(TMP / "f2b"), load=lambda c: {})  # every filter type, not flat rows
        shots = sorted(TMP.rglob("*.png"))
        def pil_centre(p):
            with Image.open(p) as im:
                return im.convert("RGB").getpixel((im.width // 2, im.height // 2))
        diff = [(p.name, centre_rgb(p), pil_centre(p)) for p in shots if centre_rgb(p) != pil_centre(p)]
        arm(f"the stdlib reader agrees with Pillow on all {len(shots)} screenshots so far", shots and not diff, diff)
    canary = TMP / "canary.html"
    canary.write_text("<body style='margin:0;background:#f00'>CANARY</body>")
    # a positive paint witness (abstractor-3 #44885): the page paints green, then navigates. Not-red alone also passes
    # on a frame that never painted (the bare shell), which the OOPIF race made common; exact green means the page
    # painted AND stayed. Measured: blocked navigation keeps it (0,170,0); without the paint the centre is the shell.
    green = "<div style='position:fixed;inset:0;background:#0a0'></div>"
    pngs, _ = cv.preview(9, page("file", green + f"<script>location.href={json.dumps(canary.as_uri())}</script>"),
                         str(TMP / "f3"), load=lambda c: {})
    arm("(f) a page navigating to a host file: it painted and stayed, the file is NOT in the screenshot",
        centre_rgb(pngs[0]) == (0, 170, 0) and not red(pngs[0]), centre_rgb(pngs[0]))

    _, errs = cv.preview(9, page("ls", "<script>localStorage.setItem('k', 1)</script>"), str(TMP / "f4"),
                         load=lambda c: {})
    arm("(g) production's sandbox holds: localStorage throws in preview as it does in the viewer's iframe",
        any(e.startswith("UNCAUGHT") for e in errs), errs)

    if cv.KIT_DIR.is_dir():
        _, errs = cv.preview(9, page("kit", '<script src="/kit/d3.min.js"></script>'
                                            "<script>if (typeof d3 !== 'object') throw new Error('nokit')</script>"),
                             str(TMP / "f6"), load=lambda c: {})
        arm("(i) the kit still loads through the locked-down network (d3 is defined, 0 errors)", errs == [], errs)
    else:
        skip("(i) the kit loads", f"kit not built at {cv.KIT_DIR}")

    real, cv.live_data = cv.live_data, lambda c: {}
    try:
        rc, out, err = run_main(["preview", "9", page("boom2", "<script>throw new Error('boom')</script>"),
                                 str(TMP / "f5")])
    finally:
        cv.live_data = real
    arm("(h) page errors exit 2, so `preview && publish` cannot ship a throwing page", rc == 2, (rc, out, err))


def live():
    print("live read-only arm (canvas 2, production DB)")
    try:
        import psycopg
        dsn = cv.dsn()
        with psycopg.connect(dsn, connect_timeout=5) as c:
            c.read_only = True
            snap = lambda: c.execute("SELECT key, value::text, updated_at, updated_by FROM canvas_data "  # noqa: E731
                                     "WHERE canvas_id = 2 ORDER BY key").fetchall()
            # Canvas 2 (Org pulse) has a live writer: painter's org_pulse_refresh trigger rewrites its keys every 5
            # minutes in a ~6 s burst, so one before/after pair can straddle it and read as a preview write (the
            # merge_check red of 10-16). A preview that WRITES differs on every attempt; a 5-minute burst can't
            # straddle three back-to-back ones. The override value is never allowed to land, on any attempt.
            for _attempt in range(3):
                pre_rows, pre = snap(), json.dumps(cv.get_data(c, 2), sort_keys=True)
                c.rollback()
                rc, out, err = run_main(["preview", "2", page("live", "<p>x</p>"), str(TMP / "live"),
                                         "--set", "probe.forced=12345"])
                post_rows, post = snap(), json.dumps(cv.get_data(c, 2), sort_keys=True)
                c.rollback()
                if (pre == post and pre_rows == post_rows) or "12345" in post:
                    break
    except (Exception, SystemExit) as e:
        skip("(c-live) canvas 2 byte-identical after a --set preview", f"DB unreachable ({type(e).__name__})")
        return
    arm("(c-live) the CLI previewed canvas 2 with an override", rc == 0 and "12345" in
        (TMP / "live" / "preview.html").read_text(), (rc, out, err))
    arm("(c-live) canvas 2's data is byte-identical after (values, updated_at, updated_by)",
        pre == post and pre_rows == post_rows and "12345" not in post)


if __name__ == "__main__":
    try:
        no_browser()
        isolation()
        if cv.browser():
            screenshots()
            containment()
            live()
        else:
            skip("screenshot arms (a)(b)(c)(d) and the live arm", "no chromium on this host")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    if fails:
        print(f"FAIL ({fails})")
        sys.exit(1)
    if skipped:
        print(f"NOT RUN ({len(skipped)}): " + "; ".join(skipped) + " — a gate that observed nothing is not a pass")
        sys.exit(77)
    print("PASS")
