#!/usr/bin/env python3
"""Two browser gates at once (plan-10108, a4 #50739 arms; a1's first arm #50691, a2's squatter G2).

Measured RED on main 10-14, before D3: two pilot gates started 1 s apart BOTH failed (they shared CDP :9334 and drove
each other's page). Each run here gets its own TMPDIR and VITE_CACHE_DIR, as check.sh's run() hands them (D1, D2):

  TWO PILOTS   two pilot gates started 1 s apart both reach a PASS verdict
  CACHE (D2)   each pilot's vite wrote its dependency cache into THAT gate's VITE_CACHE_DIR (vite.config reads it)
  SQUATTER     a pilot started while another chromium holds :9334 and an unrelated server holds vite's default :5173
               still passes: it talks only to the listeners it owns (its own DevToolsActivePort, vite's own stdout)
  TWO ORBS     two voice-orb gates started 1 s apart both pass

77 only when chromium or observatory/web's vite is absent (G3), or when the pilot itself reports it couldn't search.
PILOT_SRC points at a mutant pilot (tests/mutants_gate_concurrency.py). Exit 0 pass · 1 fail · 77 not searched.
"""
import http.server
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "observatory" / "web"
PILOT = Path(os.environ.get("PILOT_SRC") or REPO / "tests" / "pilot_browser_test.mjs")
ORB = REPO / "tests" / "test_voice_orb.py"
CHROME = next((c for c in ("/usr/bin/chromium", "/usr/bin/google-chrome-stable", "/usr/bin/chromium-browser")
               if os.path.exists(c)), None)
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


if not CHROME or not (WEB / "node_modules" / ".bin" / "vite").exists():
    print("SKIP: needs chromium and observatory/web/node_modules (vite)")
    sys.exit(77)


def gate_env(g: Path) -> dict:
    """What check.sh's run() hands a gate: its own TMPDIR, XDG_CACHE_HOME and VITE_CACHE_DIR under it."""
    return {**os.environ, "TMPDIR": str(g), "XDG_CACHE_HOME": str(g / "cache"), "VITE_CACHE_DIR": str(g / "vite"),
            "PILOT_REPO": str(REPO)}


def start(argv, g: Path):
    return subprocess.Popen(argv, cwd=REPO, env=gate_env(g), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)


def finish(p, within=420):
    try:
        out, _ = p.communicate(timeout=within)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, 9)
        out, _ = p.communicate()
        return -1, out + "\n(the harness killed it: no verdict)"
    return p.returncode, out


def tail(out, n=300):
    return out[-n:].replace("\n", " | ")


orb_unrun = None
with tempfile.TemporaryDirectory(prefix="gc-", dir="/tmp") as base:
    base = Path(base)
    ga, gb, gs, go1, go2 = (base / x for x in ("a", "b", "s", "o1", "o2"))
    for g in (ga, gb, gs, go1, go2):
        g.mkdir()

    print("TWO PILOTS: started 1 s apart, both reach a verdict")
    pa = start(["node", str(PILOT)], ga)
    time.sleep(1)
    pb = start(["node", str(PILOT)], gb)
    (ra, oa), (rb, ob) = finish(pa), finish(pb)
    if ra == 77 and rb == 77:
        print(f"SKIP: the pilot could not search here ({tail(oa, 160)})")
        sys.exit(77)
    check("the first pilot passes", ra == 0 and "ALL PASS" in oa, f"rc {ra}: {tail(oa)}")
    check("the second pilot, 1 s later, passes", rb == 0 and "ALL PASS" in ob, f"rc {rb}: {tail(ob)}")

    print("CACHE (D2): each gate's vite cache is its own")
    meta = [g / "vite" / "deps" / "_metadata.json" for g in (ga, gb)]
    check("each pilot's vite wrote its deps cache into THAT gate's VITE_CACHE_DIR",
          all(m.is_file() for m in meta), str([m.is_file() for m in meta]))

    print("SQUATTER: a pilot attaches only to listeners it owns")
    prof = base / "squatter-prof"
    # shared-on-purpose: the squatter holds the pilot's OLD fixed port, so a pilot that still used it would attach here
    squat_cdp = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9334", f"--user-data-dir={prof}",
                                  "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    class Wrong(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html><body>not the observatory</body></html>"
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    try:
        squat_http = http.server.ThreadingHTTPServer(("127.0.0.1", 5173), Wrong)   # shared-on-purpose: the squatter
        threading.Thread(target=squat_http.serve_forever, daemon=True).start()
    except OSError:
        squat_http = None                       # something already holds vite's default: it squats just as well
    try:
        held = False
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", 9334), timeout=0.2):
                    held = True
                    break
            except OSError:
                time.sleep(0.1)
        check("the squatter chromium holds :9334 (the arm's precondition)", held)
        rs, os_ = finish(start(["node", str(PILOT)], gs))
        check("a pilot beside a squatting chromium and a squatting :5173 passes on its own listeners",
              rs == 0 and "ALL PASS" in os_, f"rc {rs}: {tail(os_)}")
    finally:
        os.killpg(squat_cdp.pid, 9)
        squat_cdp.wait()
        if squat_http:
            squat_http.shutdown()
            squat_http.server_close()
        shutil.rmtree(prof, ignore_errors=True)

    if not os.environ.get("PILOT_SRC"):         # a pilot mutant can't change the orb: don't spend its minute
        print("TWO ORBS: two voice-orb gates started 1 s apart both pass")
        o1 = start([sys.executable, str(ORB)], go1)
        time.sleep(1)
        o2 = start([sys.executable, str(ORB)], go2)
        (r1, out1), (r2, out2) = finish(o1), finish(o2)
        if r1 == 77 and r2 == 77:               # the orb's own prerequisite (websockets) is absent: not run, never a pass
            orb_unrun = tail(out1, 160)
        else:
            check("the first voice-orb gate passes", r1 == 0, f"rc {r1}: {tail(out1)}")
            check("the second, 1 s later, passes", r2 == 0, f"rc {r2}: {tail(out2)}")

print()
if not fails and orb_unrun:
    print(f"SKIP: the pilot arms passed, but the voice-orb arm could not run here ({orb_unrun})")
    sys.exit(77)
print("PASS: concurrent browser gates each reach their own verdict" if not fails
      else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
