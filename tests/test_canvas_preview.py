#!/usr/bin/env python3
"""Oracle: `canvas.py preview` (nucleus/canvas.py) — the page in the real shell, screenshotted, READ-ONLY.

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

from nucleus import canvas as cv  # noqa: E402

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
    r = subprocess.run([sys.executable, str(REPO / "nucleus/canvas.py"), "preview", "2", page("nb", "<p>x</p>")],
                       capture_output=True, text=True, env=env, timeout=60)
    arm("PATH stripped of chromium: the CLI exits non-zero, says so, renders nothing",
        r.returncode != 0 and "chromium" in r.stderr and not r.stdout.strip(), (r.returncode, r.stderr[-300:]))


def isolation():
    print("isolation (publish never depends on preview)")
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import nucleus.canvas; "
                        "print(sorted(m for m in ('http.server', 'bridges.canvas_shell') if m in sys.modules))"
                        % str(REPO)], capture_output=True, text=True, timeout=60)
    arm("importing nucleus/canvas.py loads neither the kit server nor the shell (preview is lazy)",
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
    doc = (TMP / "d" / "preview.html").read_text()
    arm("(d) the shell's CSP is unchanged: connect-src none, no https: source",
        "connect-src &#x27;none&#x27;" in doc and "https:" not in doc.split("Content-Security-Policy")[1].split(">")[0])
    arm("(d) an off-box script is BLOCKED and preview surfaces the CSP violation",
        any(e.startswith("CSP-BLOCKED") and "example.com/x.js" in e for e in errs), errs)

    pngs, errs = cv.preview(9, page("tmp", "<p>x</p>"), None, load=lambda c: {})
    out = pngs[0].parent
    arm("(4) no outdir: a fresh cv-preview-* temp dir, outside the repo",
        out.name.startswith("cv-preview-") and REPO not in out.resolve().parents, out)
    shutil.rmtree(out, ignore_errors=True)


def live():
    print("live read-only arm (canvas 2, production DB)")
    try:
        import psycopg
        dsn = cv.dsn()
        with psycopg.connect(dsn, connect_timeout=5) as c:
            c.read_only = True
            snap = lambda: c.execute("SELECT key, value::text, updated_at, updated_by FROM canvas_data "  # noqa: E731
                                     "WHERE canvas_id = 2 ORDER BY key").fetchall()
            pre_rows, pre = snap(), json.dumps(cv.get_data(c, 2), sort_keys=True)
            c.rollback()
            rc, out, err = run_main(["preview", "2", page("live", "<p>x</p>"), str(TMP / "live"),
                                     "--set", "probe.forced=12345"])
            post_rows, post = snap(), json.dumps(cv.get_data(c, 2), sort_keys=True)
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
