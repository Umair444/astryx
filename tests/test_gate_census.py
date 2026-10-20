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

print("TRACKED: a gitignored file a gate names is the owner's estate, never read")
import subprocess  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    ge = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    (t / "devtools").mkdir()
    (t / "tests").mkdir()
    (t / "devtools" / "check.sh").write_text('run "fx" "$PY" tests/test_fx.py\n')
    (t / "tests" / "test_fx.py").write_text("# drives estate.py and owned.py\nimport subprocess\n")
    (t / "estate.py").write_text("open('/tmp/astryx-estate-fixed.log', 'w')\n")
    (t / "owned.py").write_text("open('/tmp/astryx-owned-fixed.log', 'w')\n")
    (t / ".gitignore").write_text("estate.py\n")
    subprocess.run(["git", "init", "-q", str(t)], env=ge, check=True)
    subprocess.run(["git", "-C", str(t), "add", "-A"], env=ge, check=True)
    d = gc.domain(t, bc=gc.load_branch_check(REPO))               # the real domain rules, pointed at the fixture repo
check("a TRACKED file the oracle names is in the domain (the control)", "owned.py" in d, str(sorted(d)))
check("a GITIGNORED file the oracle names is not", "estate.py" not in d, str(sorted(d)))

print("BARE PYTHON: CI and the pre-push tree run gates under a python3 without psycopg")
# psycopg is made ABSENT in the child by an import blocker, whatever interpreter runs this (the venv's has it)
BLOCK = ("import sys, importlib.abc\n"
         "class _NoPg(importlib.abc.MetaPathFinder):\n"
         "    def find_spec(self, name, path=None, target=None):\n"
         "        if name == 'psycopg' or name.startswith('psycopg.'):\n"
         "            raise ModuleNotFoundError(f'No module named {name!r}')\n"
         "sys.meta_path.insert(0, _NoPg())\n"
         "import importlib.util, pathlib\n"
         "spec = importlib.util.spec_from_file_location('gc', sys.argv[1])\n"
         "gc = importlib.util.module_from_spec(spec); spec.loader.exec_module(gc)\n"
         "print(len(gc.domain(pathlib.Path(sys.argv[2]))))\n")
probe = subprocess.run([sys.executable, "-I", "-c", BLOCK,
                        os.environ.get("GATE_CENSUS_SRC") or str(REPO / "devtools" / "gate_census.py"), str(REPO)],
                       capture_output=True, text=True, timeout=120)
check("with psycopg ABSENT the domain still loads and reaches >100 files",
      probe.returncode == 0 and probe.stdout.strip().isdigit() and int(probe.stdout.strip()) > 100,
      (probe.stdout + probe.stderr)[-300:])

print("(r) a SERVICE started on the host's registry, per gate (its tests/ reach), beside a pinned control")
SPAWN = "import subprocess, sys\nsubprocess.Popen([sys.executable, '-m', 'uvicorn', 'gateway:app', '--fd', '3'])\n"
R_TREE = {
    "r_spawn": {"tests/test_r.py": SPAWN},
    "r_target": {"tests/test_r.py": "import subprocess\nsubprocess.run(['venv/bin/uvicorn', 'main:app'])\n"},
    "r_inproc": {"tests/test_r.py": "import uvicorn\nuvicorn.Server(uvicorn.Config(app)).run(sockets=[s])\n"},
    "r_runner": {"tests/test_r.py": "import subprocess, sys\nsubprocess.run([sys.executable, '-c', "
                                    "'import uvicorn; uvicorn.run(app)'])\n"},
    "r_helper": {"tests/test_r.py": "# drives r_helper.py\nimport r_helper\n", "tests/r_helper.py": SPAWN},
    "g_gate": {"tests/test_r.py": "from astryx.security.sqlguard.estate import gate\ngate('test_r', REPO)\n" + SPAWN},
    "g_named": {"tests/test_r.py": "import os\nos.environ['ASTRYX_COG_REGISTRY'] = '/tmp/x/none.json'\n" + SPAWN},
    # a2 #61467 R-1: a pin is a WRITE of the key IN THE ORACLE; a mention, an unpin, a file in the reach pin nothing
    "r_helper_pins": {"tests/test_r.py": "# drives r_helper.py and r_pin.py\n" + SPAWN,
                      "tests/r_pin.py": "E = {'ASTRYX_COG_REGISTRY': 'absent'}\n"},
    "r_pop": {"tests/test_r.py": "import os\nos.environ.pop('ASTRYX_COG_REGISTRY', None)\n" + SPAWN},
    "r_comment_named": {"tests/test_r.py": "# compare test_q.py\n" + SPAWN,
                        "tests/test_q.py": "from astryx.security.sqlguard.estate import gate\ngate('test_q', REPO)\n"},
    "r_mention": {"tests/test_r.py": "print('ASTRYX_COG_REGISTRY')\n" + SPAWN},
    "r_etc": {"tests/test_r.py": "import os\nos.environ['ASTRYX_COG_REGISTRY'] = '/etc/astryx/cog.json'\n" + SPAWN},
    "r_gate_other": {"tests/test_r.py": "def gate(*a):\n    pass\ngate('test_r')\n" + SPAWN},
    "g_setdefault": {"tests/test_r.py": "import os\nos.environ.setdefault('ASTRYX_COG_REGISTRY', '/tmp/x/n')\n" + SPAWN},
    "g_update_kw": {"tests/test_r.py": "import os\nos.environ.update(ASTRYX_COG_REGISTRY='/tmp/x/n')\n" + SPAWN},
    "g_dict": {"tests/test_r.py": "import os\nos.environ |= {'ASTRYX_COG_REGISTRY': '/tmp/x/n'}\n" + SPAWN},
    "g_estate_mod": {"tests/test_r.py": "from astryx.security.sqlguard import estate as es\nes.gate('test_r', R)\n"
                                        + SPAWN},
    "g_gate_alias": {"tests/test_r.py": "from astryx.security.sqlguard.estate import gate as g\ng('test_r', R)\n"
                                        + SPAWN},
    "g_noise": {"tests/test_r.py": "# subprocess.Popen(['uvicorn', 'gateway:app'])\n"
                                   "def f():\n    \"\"\"subprocess.Popen(['uvicorn'])\"\"\"\n"
                                   "assert 'bridges.ear:app' in unit\nprint('uvicorn', 'gateway:app')\n"},
    "g_allow": {"tests/test_r.py": "import subprocess, sys\n# shared-on-purpose: a fixture registry by construction\n"
                                   "subprocess.Popen([sys.executable, '-m', 'uvicorn', 'gateway:app'])\n"},
    "g_src_names": {"tests/test_r.py": "# drives orgs.py\n" + SPAWN, "orgs.py": "ENV = 'ASTRYX_COG_REGISTRY'\n"},
}
_bcr = gc.load_branch_check(REPO)
r_got = {}
for nm, tree in R_TREE.items():
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "devtools").mkdir()
        (t / "devtools" / "check.sh").write_text('run "fx" "$PY" tests/test_r.py\n')
        for rel, text in tree.items():
            (t / rel).parent.mkdir(parents=True, exist_ok=True)
            (t / rel).write_text(text)
        r_got[nm] = [(f["class"], f["file"], f["line"]) for f in gc.unpinned(t, bc=_bcr)]
for nm, want in (("r_spawn", [("r", "tests/test_r.py", 2)]), ("r_target", [("r", "tests/test_r.py", 2)]),
                 ("r_inproc", [("r", "tests/test_r.py", 2)]), ("r_runner", [("r", "tests/test_r.py", 2)]),
                 ("r_helper", [("r", "tests/r_helper.py", 2)]), ("r_helper_pins", [("r", "tests/test_r.py", 3)]),
                 ("r_pop", [("r", "tests/test_r.py", 4)]), ("r_comment_named", [("r", "tests/test_r.py", 3)]),
                 ("r_mention", [("r", "tests/test_r.py", 3)]), ("r_etc", [("r", "tests/test_r.py", 4)]),
                 ("r_gate_other", [("r", "tests/test_r.py", 5)]),
                 ("g_src_names", [("r", "tests/test_r.py", 3)])):    # the SUBJECT naming the registry pins nothing
    check(f"RED {nm}: the unpinned service start is found at its line", r_got[nm] == want, str(r_got[nm]))
for nm in ("g_gate", "g_named", "g_setdefault", "g_update_kw", "g_dict", "g_estate_mod", "g_gate_alias", "g_noise",
           "g_allow"):
    check(f"GREEN {nm}: no (r) finding", r_got[nm] == [], str(r_got[nm]))
with tempfile.TemporaryDirectory() as td:                         # not a gate: no run line names it, nothing found
    (Path(td) / "devtools").mkdir()
    (Path(td) / "devtools" / "check.sh").write_text("# no gates\n")
    (Path(td) / "tests").mkdir()
    (Path(td) / "tests" / "test_r.py").write_text(SPAWN)
    check("GREEN a file no gate runs: no (r) finding", gc.unpinned(Path(td), bc=_bcr) == [])

print("LIVE: the census over the real gate domain")
dom = gc.domain(REPO)
check(f"the domain is the gates' reach ({len(dom)} files), the pilot and voice-orb gates in it",
      len(dom) > 100 and "tests/pilot_browser_test.mjs" in dom and "tests/test_voice_orb.py" in dom)
_bc = gc.load_branch_check(REPO)                                  # the SEEDS, re-derived: oracles + the files they name
_idx, seeds = _bc._file_index(REPO), set()
for _files in _bc.gate_files(REPO).values():
    for _o in _files:
        seeds.add(_o)
        for _nm in _bc._NAMED_RX.findall((REPO / _o).read_text(errors="replace")):
            seeds |= set(_idx.get(_nm, ()))
beyond = sorted(dom - seeds)
check(f"...TRANSITIVELY: {len(beyond)} file(s) no gate names, reached only by import, are in it", len(beyond) >= 10,
      str(beyond[:5]))
live = gc.scan(REPO, dom)
live += gc.unpinned(REPO)
check("no unmarked host-global resource in any gate's reach, no gate starting a service on the host's registry", not live,
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
