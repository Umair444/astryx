#!/usr/bin/env python3
"""Oracle: mcp/docpdf/server.py renders HTML → PDF, VERIFIES it, and FAILS CLOSED.

    venv/bin/python tests/test_docpdf_mcp.py

Part 1 is hermetic: the two process seams (_render, _inspect) are replaced by fakes, and the
allowed root is a temp dir. Part 2 drives the REAL Chromium + poppler once: a one-page render
verifies, a page cap refuses an overlong render without touching the good PDF, and a page that
references a loopback URL produces ZERO hits on a real listener (the dead-proxy network block).
Neutral fixtures only.
"""
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_docpdf_mcp", REPO, deps=("mcp.server",), env=False)   # a committed-only tree (no venv): 77, not an import crash
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {str(detail)[:300]}")


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "mcp" / "docpdf" / "server.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


root = Path(tempfile.mkdtemp(prefix="docpdf-oracle.")).resolve()
os.environ["DOCPDF_ROOT"] = str(root)
S = load("docpdf_server")
check("R0 allowed root follows DOCPDF_ROOT", S.ALLOWED_ROOT == root, S.ALLOWED_ROOT)

html = root / "doc.html"
html.write_text("<h1>Example Person</h1><p>Body</p>")
out = root / "doc.pdf"
RENDERED = []
FAKE = {"pages": 1, "text": "Example Person\nBody\n", "write": b"%PDF-1.4 fake"}


def fake_render(h, o):
    RENDERED.append((h, o))
    if FAKE["write"] is not None:
        Path(o).write_bytes(FAKE["write"])


def fake_inspect(p):
    if isinstance(FAKE.get("inspect_error"), Exception):
        raise FAKE["inspect_error"]
    return {"pages": FAKE["pages"], "text": FAKE["text"]}


S._render, S._inspect = fake_render, fake_inspect


def is_err(s):
    return isinstance(s, str) and s.startswith("error:")


def parse(s):
    try:
        return json.loads(s)
    except Exception:
        return None


print("html_to_pdf · happy path")
r = parse(S.html_to_pdf(str(html), str(out), max_pages=1, copy_to=str(root / "Example - Doc.pdf")))
check("H1 renders, verifies, reports pages/text", r and r["pages"] == 1 and r["text_chars"] > 0
      and r["first_text_line"] == "Example Person" and out.read_bytes() == FAKE["write"], r)
check("H2 copy is byte-identical", (root / "Example - Doc.pdf").read_bytes() == out.read_bytes())
check("H3 no temp render left beside the output",
      not [p for p in root.iterdir() if p.name.startswith("docpdf.")], list(root.iterdir()))

print("html_to_pdf · fail closed, good PDF untouched")
good = out.read_bytes()
FAKE.update(pages=2)
o = S.html_to_pdf(str(html), str(out), max_pages=1)
check("F1 over the page cap → error", is_err(o) and "cap is 1" in o, o)
check("F1 existing PDF untouched on cap failure", out.read_bytes() == good)
FAKE.update(pages=1, text="   \n")
o = S.html_to_pdf(str(html), str(out))
check("F2 no extractable text → error (ATS would read blank)", is_err(o), o)
check("F2 existing PDF untouched", out.read_bytes() == good)
FAKE.update(text="Example Person\n", write=None)
o = S.html_to_pdf(str(html), str(out))
check("F3 renderer produced nothing → error", is_err(o), o)
FAKE.update(write=b"%PDF fake", inspect_error=S.DocError("rendered file is not a readable PDF"))
o = S.html_to_pdf(str(html), str(out))
check("F4 unreadable PDF → error", is_err(o) and "readable" in o, o)
check("F4 existing PDF untouched", out.read_bytes() == good)
FAKE.pop("inspect_error")


def boom(h, o):
    raise S.DocError("chromium exited 1")


S._render = boom
check("F5 renderer failure → error", is_err(S.html_to_pdf(str(html), str(out))))
S._render = fake_render

print("html_to_pdf · path confinement")
outside = Path(tempfile.mkdtemp(prefix="docpdf-outside.")).resolve()
(outside / "x.html").write_text("<p>x</p>")
RENDERED.clear()
cases = {
    "P1 relative html path": ("doc.html", str(out)),
    "P2 html outside the root": (str(outside / "x.html"), str(out)),
    "P3 pdf outside the root": (str(html), str(outside / "x.pdf")),
    "P4 .. escape": (str(root / ".." / outside.name / "x.html"), str(out)),
    "P5 wrong input suffix": (str(root / "doc.pdf"), str(out)),
    "P6 wrong output suffix": (str(html), str(root / "doc.txt")),
    "P7 missing html": (str(root / "nope.html"), str(out)),
    "P8 missing output dir": (str(html), str(root / "no-dir" / "x.pdf")),
}
for name, (h, p) in cases.items():
    check(f"{name} → error", is_err(S.html_to_pdf(h, p)))
link = root / "link.html"
link.symlink_to(outside / "x.html")
check("P9 symlink resolving outside the root → error", is_err(S.html_to_pdf(str(link), str(out))))
check("P10 copy_to outside the root → error",
      is_err(S.html_to_pdf(str(html), str(out), copy_to=str(outside / "c.pdf"))))
check("P11 negative max_pages → error", is_err(S.html_to_pdf(str(html), str(out), max_pages=-1)))
check("P* no confinement failure ever reached the renderer", RENDERED == [], RENDERED)
shutil.rmtree(outside)

print("real Chromium + poppler")
R = load("docpdf_real")
try:
    R._chromium()
    have = shutil.which("pdfinfo") and shutil.which("pdftotext")
except R.DocError:
    have = False
if not have:
    print("  SKIP  real render: no chromium or poppler on this host")
else:
    HITS = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            HITS.append(self.path)
            self.send_response(200); self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    one = root / "one.html"
    one.write_text(f"""<html><head><style>@page{{size:A4;margin:12mm}}</style>
<link rel="stylesheet" href="http://127.0.0.1:{port}/css">
</head><body><h1>Example Person</h1><p>One page of text.</p>
<img src="http://127.0.0.1:{port}/beacon.png"><img src="https://127.0.0.1:{port}/b2.png">
</body></html>""")
    rp = root / "one.pdf"
    r = parse(R.html_to_pdf(str(one), str(rp), max_pages=1))
    check("X1 real render: 1 page, text extracted", r and r["pages"] == 1
          and r["first_text_line"] == "Example Person", r)
    good = rp.read_bytes() if rp.exists() else b""
    long = root / "long.html"
    long.write_text("<body>" + "".join(f"<p>line {i}</p>" for i in range(400)) + "</body>")
    o = R.html_to_pdf(str(long), str(rp), max_pages=1)
    check("X2 real overlong render over the cap → error", is_err(o) and "cap is 1" in o, o)
    check("X2 the good PDF is untouched", rp.read_bytes() == good)
    time.sleep(0.3)
    check("X3 the page's loopback references reached the listener ZERO times", HITS == [], HITS)
    srv.shutdown()

    # X4 (a1 #44856 F1): the renderer reads nothing outside the html's own folder.
    outside2 = Path(tempfile.mkdtemp(prefix="docpdf-canary.")).resolve()
    (outside2 / "secret.txt").write_text("CANARY-OUTSIDE-7731")
    sub = root / "x4"; sub.mkdir()
    (sub / "sibling.txt").write_text("SIBLING-INSIDE-4410")
    sec = (outside2 / "secret.txt").as_uri()
    (sub / "x4.html").write_text(f"""<body><p>Example Person</p>
<iframe srcdoc="<p>CTRL-INLINE-5520</p>"></iframe>
<iframe src="sibling.txt"></iframe>
<iframe src="{sec}"></iframe><object data="{sec}"></object><embed src="{sec}">
</body>""")
    o = R.html_to_pdf(str(sub / "x4.html"), str(sub / "x4.pdf"))
    txt = subprocess.run(["pdftotext", str(sub / "x4.pdf"), "-"], capture_output=True,
                         text=True).stdout if not is_err(o) else ""
    check("X4 control: an inline (srcdoc) iframe DOES render (frames work)",
          "CTRL-INLINE-5520" in txt, (o, txt[:200]))
    check("X4 a SIBLING file in the html's own folder is ABSENT (a1 #44860)",
          not is_err(o) and "SIBLING-INSIDE-4410" not in txt, txt[:200])
    check("X4 file:// iframe/object/embed outside the folder: canary ABSENT", not is_err(o)
          and "CANARY-OUTSIDE-7731" not in txt, txt[:200])
    shutil.rmtree(outside2)

    # X5 (a1 #44856 F2): no protocol leaves, WebRTC/UDP included.
    import socket
    us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); us.bind(("127.0.0.1", 0)); us.settimeout(0.1)
    uport = us.getsockname()[1]
    (root / "x5.html").write_text(f"""<body><p>Example Person</p><script>
const pc=new RTCPeerConnection({{iceServers:[{{urls:"stun:127.0.0.1:{uport}"}}]}});
pc.createDataChannel("x");pc.createOffer().then(o=>pc.setLocalDescription(o));
</script><p>pad</p></body>""")
    R.html_to_pdf(str(root / "x5.html"), str(root / "x5.pdf"))
    dgrams = 0
    t_end = time.time() + 2
    while time.time() < t_end:
        try:
            us.recvfrom(2048); dgrams += 1
        except socket.timeout:
            pass
    us.close()
    check("X5 a WebRTC STUN page sends ZERO datagrams to a real UDP listener", dgrams == 0, dgrams)

shutil.rmtree(root)
print(f"\n{'FAIL' if fails else 'OK'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
