"""The shared substrate of plan-11324 S3a's oracles: a TWO-org fixture registry, two fixture HOMEs, and an
ESTATE-FREE fixture checkout (a detached git worktree of this tree's HEAD: no .env, no local.md, no agents/, no
homes/), so a reader that falls back to the checkout finds nothing (#58435 item 2).

It never writes the host's registry (/etc/astryx/cog.json): every process it starts carries ASTRYX_COG_REGISTRY,
the declared fixture seam, pointing into its own temp dir. The two orgs' databases are NAMES only (fxorg_a_<pid>,
fxorg_b_<pid>): they never exist, so a refusal is proven to happen before any connection. The DSNs reuse this
host's host, port and user (read in Python, never printed), so libpq would reach them if a resolver let one through.

    with OrgHomes() as fx:
        fx.co      the estate-free checkout (venv linked in: host class)
        fx.home["a"], fx.home["b"], fx.db["a"], fx.dsn["a"], fx.reg (the registry file), fx.org["a"] (its name), fx.ports["a"] (its unit ports)
        fx.tmux("a")     argv prefix for org a's own tmux server (-L ax-<org>); __exit__ kills both servers
        fx.env(**over)   a clean environment for a child: the host names only, plus ASTRYX_COG_REGISTRY
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOST_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TERM", "XDG_RUNTIME_DIR", "TMPDIR", "TMUX_TMPDIR")
# mutation_probe's seams: each names a mutant copy of ONE subject, which the fixture writes over that file in the
# estate-free checkout (every child runs the checkout's code), and which the census reads in place of the file
SEAMS = {
    "ORG_HOME_SPAWN_SRC": "scripts/spawn.sh",
    "ORG_HOME_CONFIG_SRC": "src/astryx/config.py",
    "ORG_HOME_PATHS_SRC": "src/astryx/paths.py",
    "ORG_HOME_ORGS_SRC": "src/astryx/orgs.py",
    "ORG_HOME_ORGENV_SRC": "src/astryx/orgenv.py",
    "ORG_HOME_CLASSES_SRC": "src/astryx/data/org_env.json",
    "ORG_HOME_MJS_SRC": "channel/home.mjs",
    "ORG_HOME_INIT_SRC": "init.sh",
    "ORG_HOME_PULSE_SRC": "src/astryx/pulse/pulse.py",
    "ORG_HOME_BACKUP_SRC": "scripts/backup.sh",
    "ORG_HOME_ORGTMUX_SRC": "scripts/org_tmux.sh",
    "ORG_HOME_COMPACT_SRC": "src/astryx/pulse/shipped_triggers/context_compact.py",
    "ORG_HOME_HEAL_SRC": "src/astryx/pulse/shipped_triggers/agent_heal.py",
    "ORG_HOME_UNITS_DATA_SRC": "src/astryx/data/org_units.json",
    "ORG_HOME_GATEWAY_SRC": "bridges/gateway.py",
    "ORG_HOME_CHARTER_SRC": "src/astryx/core/charter.py",
}


def seam_overrides() -> dict:
    """{repo-relative subject: the mutant file standing in for it} for every seam set in the environment."""
    return {rel: Path(os.environ[k]) for k, rel in SEAMS.items() if os.environ.get(k)}


def private_tmux() -> Path:
    """Point THIS process (and every child given fx.env) at a private tmux directory: the fixture's servers, and any
    `tmux` a mutant sends to the "default" socket, live there, never on the host's real server. Call before OrgHomes."""
    d = Path(tempfile.mkdtemp(prefix="astryx-tmux-")).resolve()
    os.environ["TMUX_TMPDIR"] = str(d)
    return d


def kill_server(sock: str) -> None:
    """Stop a fixture's private tmux server AND remove its socket file: tmux leaves the file behind, and a gate that
    runs on every check would fill /tmp/tmux-<uid>/ (the 10-18 inode exhaustion was this class)."""
    subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)   # -L: never an inherited $TMUX's server
    f = Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}" / sock
    if f.is_socket() and subprocess.run(["tmux", "-L", sock, "has-session"], capture_output=True).returncode:
        f.unlink(missing_ok=True)


class FixtureUnavailable(Exception):
    pass


def live_parts() -> dict:
    """host/port/user of this host's org DSN, through the ONE resolver; never the password, never printed."""
    import sys
    sys.path.insert(0, str(REPO / "src"))
    from astryx import config, orgs, paths
    d = orgs.conninfo(config.dsn(paths.estate(__file__) / ".env"))
    return {k: d[k] for k in ("host", "port", "user") if d.get(k)}


class OrgHomes:
    def __init__(self, local_md=("a", "b"), user_db_for=None):
        self.local_md = local_md
        self.user_db_for = user_db_for       # an org whose registry db is the superuser's NAME (correction 1(ii))

    def __enter__(self):
        if subprocess.run(["git", "-C", str(REPO), "rev-parse", "--git-dir"], capture_output=True).returncode:
            raise FixtureUnavailable("this tree is not a git checkout (an estate-free worktree needs one)")
        try:
            parts = live_parts()
        except Exception as e:  # noqa: BLE001
            raise FixtureUnavailable(f"no org DSN here to borrow host/port/user from ({type(e).__name__})")
        self.t = Path(tempfile.mkdtemp(prefix="astryx-orghome-")).resolve()
        self.co = self.t / "co"
        r = subprocess.run(["git", "-C", str(REPO), "worktree", "add", "-q", "--detach", str(self.co), "HEAD"],
                           capture_output=True, text=True)
        if r.returncode:
            shutil.rmtree(self.t, ignore_errors=True)
            raise FixtureUnavailable(f"git worktree add failed: {r.stderr.strip()[:200]}")
        for rel, mutant in seam_overrides().items():
            (self.co / rel).write_bytes(mutant.read_bytes())
        venv = REPO / "venv"
        if venv.exists():
            (self.co / "venv").symlink_to(venv.resolve())
        nm = REPO / "channel" / "node_modules"
        if nm.exists():
            (self.co / "channel" / "node_modules").symlink_to(nm.resolve())
        self.parts = parts
        self.home, self.db, self.dsn = {}, {}, {}
        for o in ("a", "b"):
            h = self.t / f"home-{o}"
            h.mkdir()
            (h / ".astryx").write_text("astryx home\n")
            db = parts["user"] if self.user_db_for == o else f"fxorg_{o}_{os.getpid()}"
            hostpart = parts.get("host", "127.0.0.1") + (f":{parts['port']}" if parts.get("port") else "")
            self.dsn[o] = f"postgresql://{parts['user']}@{hostpart}/{db}"
            (h / ".env").write_text(f"ASTRYX_DSN={self.dsn[o]}\nPEOPLE_SALT=salt-{o}\nASTRYX_ORG=fxorg-{o}\n"
                                    f"WA_CLI=echo wa-{o}\n")
            if o in self.local_md:
                (h / "local.md").write_text(f"# the law of fixture org {o}\nonly org {o} is bound by this.\n")
            (h / "agents").mkdir()
            self.home[o], self.db[o] = h, db
        # org NAMES are per run (S3b): each org's tmux server is `-L ax-<org>`, a host-wide socket name, so two runs
        # (a merge_check beside the live stamp) must never share one
        self.org = {o: f"fx{o}-{os.getpid()}" for o in ("a", "b")}
        # each org's ports (S3b 5/n) are its own and NEVER the fixed ones (A: +10000, B: +20000), so a unit that kept
        # its literal reads as the literal, never as a coincidence. Declared here, never bound by any oracle.
        fixed = {"astryx-whatsapp": 8477, "astryx-telegram": 8478, "astryx-discord": 8479, "astryx-senses": 8460,
                 "astryx-geoloc": 8766, "astryx-ear": 8092, "astryx-growbot": 8470}
        self.ports = {o: {k: v + off for k, v in fixed.items()} for o, off in (("a", 10000), ("b", 20000))}
        self.reg = self.t / "orgs.json"
        self.reg.write_text(json.dumps({"orgs": {self.org[o]: {"home": str(self.home[o]), "db": self.db[o],
                                                               "ports": self.ports[o]} for o in ("a", "b")}}))
        return self

    def env(self, **over) -> dict:
        e = {k: os.environ[k] for k in HOST_KEEP if os.environ.get(k)}
        e["ASTRYX_COG_REGISTRY"] = str(self.reg)
        e.update({k: v for k, v in over.items() if v is not None})
        return e

    def tmux(self, o) -> list[str]:
        return ["tmux", "-L", f"ax-{self.org[o]}"]

    def __exit__(self, *exc):
        if hasattr(self, "org"):
            for o in self.org:                   # only the fixture's OWN servers, never the default socket
                kill_server(f"ax-{self.org[o]}")
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(self.co)], capture_output=True)
        subprocess.run(["git", "-C", str(REPO), "worktree", "prune"], capture_output=True)
        shutil.rmtree(self.t, ignore_errors=True)
        return False
