#!/usr/bin/env python3
"""Oracle: the one .env writer (astryx.config._write_env) and the vault's derived key (astryx.core.vault), medic 12364 R2.
No database; temp directories only, synthetic values.
  E1 eight processes writing at once lose nothing: every key lands, the file stays 0600
  E2 a crash between the write and the rename leaves the OLD file whole, and no temp file behind
  E3 a writer waits for the lock another holds (init.sh's env_add takes the same one)
  E4 the shell's `set KEY` reads the value from stdin (never argv)
  V1 the vault's key is derived from the name: ASTRYX_CRED_<SLUG>; a key the vault doesn't own is refused; no name can
     produce one of the org's own keys
Exit 0 · 1."""
import os
import subprocess
import sys
import tempfile
import threading
import time
from multiprocessing import Process
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from astryx import config  # noqa: E402
from astryx.core import vault  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


def writer(path, n, i):
    for j in range(n):
        config.set_env(f"K_{i}_{j}", f"v{i}.{j}", path)


with tempfile.TemporaryDirectory() as td:
    env = Path(td) / ".env"
    env.write_text("ASTRYX_DSN=postgres://x\n")
    ps = [Process(target=writer, args=(env, 25, i)) for i in range(8)]
    [p.start() for p in ps]
    [p.join() for p in ps]
    got = config.read_env(env)
    arm("E1 eight writers at once: all 200 keys land, the old one kept", all(got.get(f"K_{i}_{j}") == f"v{i}.{j}" for i in range(8) for j in range(25)) and got.get("ASTRYX_DSN") == "postgres://x", len(got))
    arm("E1 the file stays 0600, its lock too", (env.stat().st_mode & 0o777) == 0o600 and (Path(str(env) + ".lock").stat().st_mode & 0o777) == 0o600)

    before = env.read_text()
    real = os.replace
    os.replace = lambda a, b: (_ for _ in ()).throw(OSError("crash"))
    try:
        config.set_env("NEW", "x", env)
        arm("E2 a crash mid-write raises", False)
    except OSError:
        pass
    finally:
        os.replace = real
    arm("E2 …and leaves the old file whole, no temp file behind", env.read_text() == before and not [f for f in os.listdir(td) if f.startswith(".env.") and f != ".env.lock"], os.listdir(td))

    import fcntl
    lk = os.open(str(env) + ".lock", os.O_WRONLY)
    fcntl.flock(lk, fcntl.LOCK_EX)
    done = []
    t = threading.Thread(target=lambda: (config.set_env("WAITED", "1", env), done.append(time.time())))
    t0 = time.time()
    t.start()
    time.sleep(0.6)
    arm("E3 a writer waits while another holds the lock", not done)
    fcntl.flock(lk, fcntl.LOCK_UN)
    os.close(lk)
    t.join(5)
    arm("E3 …and writes once it's free", done and config.read_env(env).get("WAITED") == "1")
    lk = os.open(str(env) + ".lock", os.O_WRONLY)
    fcntl.flock(lk, fcntl.LOCK_EX)
    sh = subprocess.Popen(["bash", "-c", f"cd {td} && source <(sed -n '/^env_add()/,/^}}/p' {REPO / 'init.sh'}) && echo SHELL_ADDED=1 | env_add"])
    time.sleep(0.6)
    arm("E3 init.sh's env_add waits on the same lock", sh.poll() is None)
    fcntl.flock(lk, fcntl.LOCK_UN)
    os.close(lk)
    sh.wait(5)
    arm("E3 …and appends once it's free", config.read_env(env).get("SHELL_ADDED") == "1")

    import io
    real_estate, real_stdin = config._cli_estate, sys.stdin
    config._cli_estate = lambda invoked: Path(td)          # the CLI's tree, pinned to this temp dir: no real .env is touched
    sys.stdin = io.StringIO("sekrit-value\n")
    try:
        rc = config._main(["set", "FROM_STDIN"])
    finally:
        config._cli_estate, sys.stdin = real_estate, real_stdin
    arm("E4 `set KEY` takes the value from stdin (it never rides in argv)", rc == 0 and config.read_env(env).get("FROM_STDIN") == "sekrit-value", rc)

arm("V1 the key is derived from the name", vault.env_key("My key.2", {}) == "ASTRYX_CRED_MY_KEY_2")
for bad in ("", " ", "../x", "a" * 49, "x\ny", None, "ASTRYX=DSN"):
    try:
        vault.env_key(bad, {})
        arm(f"V1 a bad name is refused: {bad!r}", False)
    except vault.Refused:
        pass
try:
    vault.env_key("work", {"ASTRYX_CRED_WORK": "set by hand"})
    arm("V1 a key in .env that the vault doesn't own is refused", False)
except vault.Refused:
    arm("V1 a key in .env that the vault doesn't own is refused", True)
arm("V1 …the vault's own name maps to its own key", vault.env_key("work", {"ASTRYX_CRED_WORK": "x"}, {"Work"}) == "ASTRYX_CRED_WORK")
arm("V1 no name yields one of the org's own keys", all(vault.env_key(n, {}).startswith("ASTRYX_CRED_") for n in ("ASTRYX_DSN", "WA_WEBHOOK_SECRET", "CLAUDE_CODE_OAUTH_TOKEN")))

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: one locked, atomic .env writer, and derived credential keys")
sys.exit(1 if fails else 0)
