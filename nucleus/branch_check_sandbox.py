#!/usr/bin/env python3
"""branch_check SANDBOX (plan-4918 R3 + R5): a capability ALLOWLIST, and the boundary PROBED from inside.

R3, the allowlist (a2's measured D run): the run sees exactly
    /usr, /etc (ro) · the live venv and mise (ro, at their own paths) · channel/node_modules (ro, regenerable)
    · the private-tier paths the prep LINKED (ro, at their live paths) · the private repo (rw) · the run tmp (rw)
with HOME = TMPDIR = the run tmp, /tmp and /run as fresh tmpfs (no docker socket), `env -i` plus an explicit env.
THE NETWORK IS NOT SHARED (a3 #32077 R1): --unshare-net gives the run its own netns (loopback only), so it can't reach
the host's listeners (geoloc :8766 serves the owner's location fixes to any 127.0.0.1 client) or the internet. Its
ONE route out is postgres, through a host-side BRIDGE: a unix socket in the run tmp relayed to the server's TCP port,
so authentication stays exactly as it is (SCRAM, the run role's own password). --unshare-pid hides host processes.
~/.pgpass is kept out by independent fences, each sufficient alone: HOME points at the run tmp; the real home is never
mounted (only mise, at its own path); and with the network unshared its host=localhost entry has no route (libpq
applies a localhost entry to a unix socket only at its DEFAULT socket dir, and the bridge's socket isn't there).
Anything not listed is ABSENT, so an undeclared dependency fails loud instead of silently reading live.

R5, the probes (plan-4918 #26043 + #26057 + a3 BC-4), run INSIDE before the suite, each must hold or the run
REFUSES (rc 77, named). A probe that can't be falsified proves nothing, so every NEGATIVE probe has a POSITIVE
control that runs OUTSIDE and must SUCCEED:
  (i)   pgpass reach: every (host, port, user) a reachable pgpass file matches, plus localhost / 127.0.0.1 / the
        LAN address, as genesis and postgres, password-less, must FAIL inside. The .pgpass host is LITERAL (a3 BC-4:
        libpq defaults fail for the wrong reason). Control: the same tuple as the real user OUTSIDE succeeds.
  (iv)  the live .env is unreadable inside.                       Control: readable outside.
  (v)   the live repo is not writable inside.                     Control: n/a (a write outside would mutate E).
  (iii) docker is unreachable inside (no socket).                 Control: the socket exists outside.
  (vi)  the run role can't CONNECT to any database it doesn't own. Control: NOTIFY + LISTEN work in its own clone.
  (ii)  is subsumed by (vi): without CONNECT on prod there is no INSERT to try.
  (vii) every host TCP listener (enumerated OUTSIDE from /proc/net/tcp{,6}) and one external address are unreachable
        inside.                                                    Control: the same connects succeed outside.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LIVE = Path(os.environ.get("ASTRYX_LIVE_REPO", "/home/umair/astryx"))
HOME = Path.home()


def pgpass_tuples() -> list:
    """(host, port, user) of every entry in a reachable pgpass file, NEVER the password (a3 BC-4: derived)."""
    out = []
    for pf in (os.environ.get("PGPASSFILE"), str(HOME / ".pgpass")):
        if pf and Path(pf).is_file():
            for line in Path(pf).read_text().splitlines():
                parts = re.split(r"(?<!\\):", line)
                if len(parts) >= 5 and not line.startswith("#"):
                    out.append((parts[0], parts[1], parts[3]))
    return out


def lan_addrs() -> list:
    try:
        txt = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True).stdout
    except OSError:
        return []
    return [m for m in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", txt) if not m.startswith("127.")]


def reach_targets() -> list:
    """Every (host, port, user) a password-less connect should be tried with."""
    hosts = {"localhost", "127.0.0.1", *lan_addrs()}
    tuples = {(h, p, u) for h, p, u in pgpass_tuples() if h != "*"}
    for h in hosts:
        for u in {"genesis", "postgres"} | {u for _, _, u in pgpass_tuples() if u != "*"}:
            tuples.add((h, "5432", u))
    return sorted(tuples)


EXTERNAL = ("1.1.1.1", 443)


def host_listeners() -> list:
    """(ip, port) of every TCP socket in LISTEN on the host, from /proc/net/tcp{,6}. A wildcard bind is probed on
    loopback (the address a same-host client would use)."""
    out = set()
    for f, fam in (("/proc/net/tcp", 4), ("/proc/net/tcp6", 6)):
        try:
            lines = Path(f).read_text().splitlines()[1:]
        except OSError:
            continue
        for ln in lines:
            parts = ln.split()
            if len(parts) < 4 or parts[3] != "0A":                   # 0A = LISTEN
                continue
            hexip, hexport = parts[1].split(":")
            port = int(hexport, 16)
            if fam == 4:
                ip = ".".join(str(int(hexip[i:i + 2], 16)) for i in (6, 4, 2, 0))
                ip = "127.0.0.1" if ip == "0.0.0.0" else ip
            else:
                ip = "::1"                              # every v6 LISTEN row probed on ::1 (a v6-only listener exists)
            out.add((ip, port))
    return sorted(out)


def _reach(targets, timeout=1.0) -> list:
    import socket
    ok = []
    for ip, port in targets:
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        s = socket.socket(fam, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((ip, port))
            ok.append(f"{ip}:{port}")
        except OSError:
            pass
        finally:
            s.close()
    return ok


def bridge_main(sock_dir: str, host: str = "127.0.0.1", port: int = 5432):
    """The host-side postgres bridge: <sock_dir>/.s.PGSQL.<port> relayed to host:port. Runs OUTSIDE the sandbox."""
    import asyncio

    async def pipe(r, w):
        try:
            while data := await r.read(65536):
                w.write(data)
                await w.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            w.close()

    async def handle(cr, cw):
        try:
            sr, sw = await asyncio.open_connection(host, port)
        except OSError:
            cw.close()
            return
        await asyncio.gather(pipe(cr, sw), pipe(sr, cw))

    async def main():
        path = Path(sock_dir) / f".s.PGSQL.{port}"
        server = await asyncio.start_unix_server(handle, path=str(path))
        async with server:
            await server.serve_forever()
    asyncio.run(main())


class PgBridge:
    """Context manager: start the bridge (from the TOOL's own code) and wait for its socket; stop it on exit."""
    def __init__(self, sock_dir: Path, port: int = 5432):
        self.dir, self.port, self.proc = Path(sock_dir), port, None

    def __enter__(self):
        import socket
        import time
        self.dir.mkdir(parents=True, exist_ok=True)
        # a SIGTERM'd bridge leaves its socket FILE behind; readiness by exists() then passes instantly on a dir that
        # hosted an earlier bridge while nothing listens (a3 #32894 B1: the branch side reuses its dir, main never
        # does, so the race would read as a false REGRESSED). Remove it, and call it ready only on a real connect.
        (self.dir / f".s.PGSQL.{self.port}").unlink(missing_ok=True)
        code = (f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); "
                f"from nucleus.branch_check_sandbox import bridge_main; bridge_main({str(self.dir)!r}, port={self.port})")
        self.proc = subprocess.Popen([sys.executable, "-c", code])
        sock = self.dir / f".s.PGSQL.{self.port}"
        for _ in range(200):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(str(sock))
                return self
            except OSError:
                time.sleep(0.05)
            finally:
                s.close()
        self.proc.kill()
        raise RuntimeError("the postgres bridge never opened its socket")

    def __exit__(self, *exc):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        return False


PROBE_AT = "/run/bc_probe.py"


def argv(repo: Path, run_tmp: Path, ro_extra=(), live: Path = LIVE, probe_src: Path = None,
         share_net: bool = False) -> list:
    """The bwrap command prefix. `ro_extra` = live paths the prep linked (the private tier). `probe_src` is the
    TOOL's own copy of this file, bound read-only at PROBE_AT: the repo inside is the BRANCH's tree, and a verifier
    taken from the subject under test could be rewritten to lie."""
    a = ["bwrap",
         "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
         "--symlink", "usr/lib", "/lib64", "--symlink", "usr/bin", "/sbin",
         "--ro-bind", "/etc", "/etc", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run",
         "--ro-bind", str(live / "venv"), str(live / "venv")]
    mise = HOME / ".local" / "share" / "mise"
    if mise.is_dir():
        a += ["--ro-bind", str(mise), str(mise)]
    nm = live / "channel" / "node_modules"
    if nm.is_dir() and (repo / "channel").is_dir():
        a += ["--ro-bind", str(nm), str(repo / "channel" / "node_modules")]
    for p in ro_extra:
        if Path(p).exists():
            a += ["--ro-bind", str(p), str(p)]
    if probe_src:
        a += ["--ro-bind", str(probe_src), PROBE_AT]
    a += ["--bind", str(repo), str(repo), "--bind", str(run_tmp), str(run_tmp),
          "--setenv", "HOME", str(run_tmp), "--setenv", "TMPDIR", str(run_tmp),
          ("--share-net" if share_net else "--unshare-net"),       # share_net: ONLY the oracle's RED control
          "--unshare-pid", "--die-with-parent", "--chdir", str(repo)]
    return a


def env(run_dsn: str) -> dict:
    """What `env -i` hands the sandbox: a minimal PATH, the locale, and the run role's DSN. Nothing else."""
    return {"PATH": "/usr/bin", "LANG": "C.UTF-8", "ASTRYX_DSN": run_dsn}


# ── the probe, as a program: run INSIDE (and, for the controls, OUTSIDE) ──────────────────────────────────────
def probe(cfg: dict) -> dict:
    """cfg: {targets, live_env, live_repo, own_dsn, foreign_dbs, run_conn, listeners, socket_dirs}. Returns {name: ok, …}; `ok` means
    the property the run needs holds IN THIS PROCESS's world (a boundary: reach FAILS)."""
    import psycopg
    res = {}
    reached = []
    for h, p, u in cfg["targets"]:
        try:
            c = psycopg.connect(host=h, port=p, user=u, dbname="postgres", connect_timeout=3, password="")
            reached.append(f"{u}@{h}:{p}")
            c.close()
        except Exception:
            pass
    res["pgpass_reach"] = {"reached": reached}
    try:
        Path(cfg["live_env"]).read_bytes()
        res["live_env_readable"] = True
    except OSError:
        res["live_env_readable"] = False
    # VISIBLE first: bwrap creates the live repo's path as an EMPTY synthetic directory (the parent of the venv
    # mount), which is writable and isn't the repo. Only the real repo has its own files. Writability is asked with
    # access(2), never an actual write, so the OUTSIDE control never writes to E either.
    lr = Path(cfg["live_repo"])
    res["live_repo_visible"] = (lr / "nucleus" / "check.sh").is_file()
    res["live_repo_writable"] = res["live_repo_visible"] and os.access(lr / "nucleus", os.W_OK)
    res["docker_socket"] = Path("/var/run/docker.sock").exists() or Path("/run/docker.sock").exists()
    res["listeners_reached"] = _reach([tuple(x) for x in cfg.get("listeners", [])])
    res["external_reached"] = bool(_reach([EXTERNAL], timeout=3.0))
    for sd in cfg.get("socket_dirs", []):                        # (i) through the bridge, password-less
        for u in ("genesis", "postgres"):
            try:
                c = psycopg.connect(host=sd, port=5432, user=u, dbname="postgres", connect_timeout=3, password="")
                res["pgpass_reach"]["reached"].append(f"{u}@{sd}")
                c.close()
            except Exception:
                pass
    foreign = []
    for db in cfg.get("foreign_dbs", []):
        try:
            c = psycopg.connect(**cfg["run_conn"], dbname=db, connect_timeout=3)
            foreign.append(db)
            c.close()
        except Exception:
            pass
    res["foreign_connect"] = foreign
    notify_ok = False
    if cfg.get("own_dsn"):
        try:
            with psycopg.connect(cfg["own_dsn"], autocommit=True) as a, psycopg.connect(cfg["own_dsn"], autocommit=True) as b:
                a.execute("LISTEN bc_probe")
                b.execute("NOTIFY bc_probe, 'x'")
                notify_ok = any(n.payload == "x" for n in a.notifies(timeout=3, stop_after=1))
        except Exception:
            notify_ok = False
    res["own_notify"] = notify_ok
    return res


def verdict(inside: dict, outside: dict) -> list:
    """The reasons to REFUSE (empty = the boundary holds AND every negative probe was shown falsifiable)."""
    bad = []
    if inside["pgpass_reach"]["reached"]:
        bad.append(f"(i) password-less reach from inside: {inside['pgpass_reach']['reached']}")
    if not outside["pgpass_reach"]["reached"]:
        bad.append("(i) VACUOUS: no pgpass tuple authenticates even OUTSIDE, so the inside FAIL proves nothing")
    if inside["live_env_readable"]:
        bad.append("(iv) the live .env is readable inside")
    if not outside["live_env_readable"]:
        bad.append("(iv) VACUOUS: the live .env isn't readable outside either")
    if inside["live_repo_writable"]:
        bad.append("(v) the live repo is writable inside")
    if not outside["live_repo_writable"]:
        bad.append("(v) VACUOUS: the live repo isn't writable outside either, so the inside result proves nothing")
    if inside["docker_socket"]:
        bad.append("(iii) a docker socket is visible inside")
    if inside.get("listeners_reached"):
        bad.append(f"(vii) host listeners reachable from inside: {inside['listeners_reached']}")
    if not outside.get("listeners_reached"):
        bad.append("(vii) VACUOUS: no host listener is reachable even OUTSIDE, so the inside result proves nothing")
    if inside.get("external_reached"):
        bad.append("(vii) the internet is reachable from inside")
    if inside["foreign_connect"]:
        bad.append(f"(vi) the run role CONNECTs to databases it doesn't own: {inside['foreign_connect']}")
    if not inside["own_notify"]:
        bad.append("(vi) VACUOUS: NOTIFY/LISTEN doesn't work even in the run's own clone")
    return bad


if __name__ == "__main__":
    print(json.dumps(probe(json.loads(sys.stdin.read()))))
