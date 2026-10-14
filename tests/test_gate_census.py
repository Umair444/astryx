#!/usr/bin/env python3
"""Oracle for devtools/gate_census.py (plan-10108 D4, a4 #50739; a3 BC-1 ii; a2 rider #50743).

Every class RED on a fixture, beside a GREEN control that differs by one discriminator:
  (a)  a literal port to a listener: python spawn argv, bind, HTTPServer, uvicorn.run, docker -p; js spawn + const; sh
  (b)  probe-then-release: close(), `with`, a shell $(...); bind(0)-and-serve, and a held refusal port, stay green
  (d') a write under a shared root: an absolute literal, Path.home(), an XDG_RUNTIME_DIR-derived log (a3's measured
       instance, android's); the same write via tempfile / TMPDIR / the run root is green
  NOISE  a port or a path in a comment, a docstring, a quoted grep pattern, a unit's ExecStart or a heredoc is no finding
  ALLOW  `# shared-on-purpose: <why>` on the line, the line above, or the ROOT's definition silences it; elsewhere not
  LIVE   the census over the real gate domain (>100 files, the pilot and voice-orb gates in it) finds nothing
GATE_CENSUS_SRC points at a mutant census (tests/mutants_gate_census.py). Exit 0 pass · 1 fail.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("gate_census_under_test",
                                              os.environ.get("GATE_CENSUS_SRC") or REPO / "devtools" / "gate_census.py")
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def census(files: dict) -> dict:
    """{fixture name: [classes found]} for a tree written from `files`."""
    with tempfile.TemporaryDirectory() as td:
        for rel, text in files.items():
            (Path(td) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(td) / rel).write_text(text)
        got = gc.scan(Path(td), files)
    out = {rel: [] for rel in files}
    for f in got:
        out[f["file"]].append(f["class"])
    return out


RED = {
    # (a)
    "a_py_argv.py": "import subprocess\nsubprocess.Popen(['vite', '--port', '5181', '--strictPort'])\n",
    "a_py_cdp.py": "import subprocess\nsubprocess.Popen(['chromium', '--remote-debugging-port=9334', 'about:blank'])\n",
    "a_py_bind.py": "import socket\ns = socket.socket()\ns.bind(('127.0.0.1', 8123))\ns.listen()\n",
    "a_py_http.py": "import http.server\nhttp.server.ThreadingHTTPServer(('127.0.0.1', 8080), None)\n",
    "a_py_uvicorn.py": "import uvicorn\nuvicorn.run(app, host='127.0.0.1', port=8000)\n",
    "a_py_docker.py": "import subprocess\nsubprocess.run(['docker', 'run', '-p', '127.0.0.1:5433:5432', 'pg'])\n",
    "a_js_argv.mjs": "import { spawn } from 'node:child_process'\nspawn('vite', ['--port', '5181', '--strictPort'])\n",
    "a_js_const.mjs": "const port = 9334\nspawn(CHROME, [`--remote-debugging-port=${port}`, 'about:blank'])\n",
    "a_js_listen.mjs": "server.listen(3000)\n",
    "a_sh.sh": "#!/bin/bash\nuvicorn app:app --host 127.0.0.1 --port 8123 &\n",
    # (b)
    "b_close.py": ("import socket\ndef port():\n    s = socket.socket()\n    s.bind(('127.0.0.1', 0))\n"
                   "    p = s.getsockname()[1]\n    s.close()\n    return p\n"),
    "b_with.py": ("import socket\ndef port():\n    with socket.socket() as so:\n        so.bind(('127.0.0.1', 0))\n"
                  "        return so.getsockname()[1]\n"),
    "b_sh.sh": ("#!/bin/bash\nport=$(python3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\", 0)); "
                "print(s.getsockname()[1])')\n"),
    # (d')
    "d_abs.py": "open('/tmp/astryx-fixed.log', 'w').write('x')\n",
    "d_home.py": "from pathlib import Path\n(Path.home() / '.cache' / 'gate').mkdir(parents=True)\n",
    "d_xdg.py": ("import os\nfrom pathlib import Path\n"
                 "log = Path(os.environ.get('XDG_RUNTIME_DIR') or '/tmp') / 'astryx-android-x.log'\n"
                 "fh = open(log, 'ab')\n"),
    "d_xdg_only.py": ("import os\nfrom pathlib import Path\n"
                      "(Path(os.environ['XDG_RUNTIME_DIR']) / 'astryx-android-x.log').open('ab')\n"),
    "d_env_default.py": ("import os\nfrom pathlib import Path\nROOT = Path(os.environ.get('ASTRYX_X_ROOT', '/tmp/astryx-x'))\n"
                         "(ROOT / 'lock.json').write_text('{}')\n"),
    "d_profile.py": ("import subprocess\nfrom pathlib import Path\n"
                     "subprocess.Popen(['chromium', f'--user-data-dir={Path.home()}', 'about:blank'])\n"),
    "d_js.mjs": "import { writeFileSync } from 'node:fs'\nwriteFileSync('/tmp/astryx-fixed.json', '{}')\n",
    "unmarked_root.py": ("import os\nfrom pathlib import Path\nSTATE = Path(os.environ.get('ASTRYX_S') or Path.home() / '.s')\n"
                         "(STATE / 'x').write_text('1')\n"),
}
WANT = {k: k.split("_")[0] if k[1] == "_" else "d" for k in RED}

GREEN = {
    "g_port0.py": ("import subprocess\nsubprocess.Popen(['chromium', '--remote-debugging-port=0', 'about:blank'])\n"
                   "subprocess.Popen(['vite', '--host', '127.0.0.1'])\n"),
    "g_docker.py": "import subprocess\nsubprocess.run(['docker', 'run', '-p', '127.0.0.1::5432', 'pg'])\n",
    "g_serve.py": ("import socket\ndef serve():\n    s = socket.socket()\n    s.bind(('127.0.0.1', 0))\n"
                   "    p = s.getsockname()[1]\n    s.listen()\n    s.accept()\n    s.close()\n    return p\n"),
    "g_refuse.py": "import socket\n_S = socket.socket()\n_S.bind(('127.0.0.1', 0))\nDOWN = _S.getsockname()[1]\n",
    "g_udp.py": ("import socket\nus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\nus.bind(('127.0.0.1', 0))\n"
                 "uport = us.getsockname()[1]\nus.recvfrom(64)\nus.close()\n"),
    "g_tmp.py": ("import os, tempfile\nfrom pathlib import Path\n"
                 "log = Path(tempfile.gettempdir()) / 'astryx-android-x.log'\nfh = open(log, 'ab')\n"
                 "d = Path(tempfile.mkdtemp()) / 'p'\nd.mkdir()\n"
                 "t = Path(os.environ['TMPDIR']) / 'x'\nt.write_text('1')\n"),
    "g_repo.py": "from pathlib import Path\nREPO = Path(__file__).resolve().parent\n(REPO / 'out.txt').write_text('1')\n",
    "g_override.py": ("import os, tempfile\nfrom pathlib import Path\n"
                      "R = Path(os.environ.get('ASTRYX_R') or tempfile.gettempdir())\n(R / 'x').write_text('1')\n"),
    "g_noise.py": ('"""Run: uvicorn app --port 8090, writes /tmp/fixed.log"""\n'
                   "# subprocess.Popen(['vite', '--port', '5181'])\nX = 'open(\"/tmp/x\", \"w\")'\n"),
    "g_noise.mjs": "// spawn(vite, ['--port', '5181'])\n/* --remote-debugging-port=9334 */\nconst url = 'http://127.0.0.1:8090/'\n",
    "g_noise.sh": ("#!/bin/bash\n# uvicorn app --port 8123\n"
                   "n=$(grep -c 'bridges.whatsapp:app --host 1.2.3.4 --port 8477' init.sh)\n"
                   "ExecStart=/venv/bin/uvicorn main:app --port 8090\n"
                   "cat > unit <<EOF\nExecStart=uvicorn app --port 8091\nEOF\n"
                   "cat > run.sh <<'EOS'\nuvicorn app:app --port 8092\nEOS\n"),
    "g_marked.py": "open('/tmp/astryx-fixed.log', 'w')   # shared-on-purpose: the fixture's one shared log\n",
    "g_marked_above.py": "import socket\n# shared-on-purpose: a fixed listener the fixture declares\n"
                         "socket.socket().bind(('127.0.0.1', 8123))\n",
    "g_marked_root.py": ("import os\nfrom pathlib import Path\n"
                         "# shared-on-purpose: the live org's state; gates set ASTRYX_S under their TMPDIR\n"
                         "STATE = Path(os.environ.get('ASTRYX_S') or Path.home() / '.s')\n"
                         "LOCK = STATE / '.lock'\n(STATE / 'x').write_text('1')\nLOCK.touch()\n"),
}

print("RED: each class is found, by its own class")
got = census(RED)
for name, want in WANT.items():
    check(f"({want}) {name}", want in got[name], str(got[name]))

print("GREEN: the one-discriminator controls are quiet")
got = census(GREEN)
for name in GREEN:
    check(f"quiet: {name}", got[name] == [], str(got[name]))

print("ALLOW: the marker counts only at the finding, the line above, or the root's definition")
far = {"far.py": "# shared-on-purpose: too far away\n\n\nopen('/tmp/astryx-fixed.log', 'w')\n"}
check("a marker three lines up does NOT silence it", census(far)["far.py"] == ["d"], str(census(far)))
bare = {"bare.py": "open('/tmp/astryx-fixed.log', 'w')   # shared-on-purpose:\n"}
check("a marker with no reason does NOT silence it", census(bare)["bare.py"] == ["d"], str(census(bare)))

print("LIVE: the census over the real gate domain")
dom = gc.domain(REPO)
check(f"the domain is the gates' reach ({len(dom)} files), the pilot and voice-orb gates in it",
      len(dom) > 100 and "tests/pilot_browser_test.mjs" in dom and "tests/test_voice_orb.py" in dom)
check("...TRANSITIVELY: runscope.py, which no gate names and only imports reach, is in it",
      "src/astryx/pg/runscope.py" in dom)
live = gc.scan(REPO, dom)
check("no unmarked host-global resource in any gate's reach", not live,
      "; ".join(f"({f['class']}) {f['file']}:{f['line']}" for f in live[:6]))
for rel, needle in (("src/astryx/pg/runscope.py", "SCOPE_ROOT = "), ("tests/_oracle_debris.py", "ORACLE_BASE = ")):
    text = (REPO / rel).read_text().splitlines()
    i = next((n for n, ln in enumerate(text) if ln.startswith(needle)), None)
    check(f"{needle.strip(' =')} is declared shared-on-purpose (a2 rider: a cross-run ledger, never under $G)",
          i is not None and any("shared-on-purpose:" in text[j] for j in range(max(0, i - 3), i + 1)))

print()
print("PASS: every host-global resource in a gate's reach is per gate or declared" if not fails
      else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
