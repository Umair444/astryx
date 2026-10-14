"""astryx — the command line (plan-10224 S3).

The CLI's job is to get the SEED alive, fast and reliably; the seed then walks the owner through the
rest (agents/seed/onboard.md), using these same verbs. Every step stays runnable by hand.

Phase 1: `init` does the preflight and the HOME choice itself, then shells to the idempotent init.sh for
the heavy lifting. Every external command goes through `RUNNER` and every secret prompt through
`SECRET_PROMPT`, so tests stub both.
"""
from __future__ import annotations

import argparse
import getpass
import inspect
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import astryx
from astryx import config, paths, tree
from astryx.ui import UI

RUNNER = subprocess.run            # seam: tests replace it
SECRET_PROMPT = getpass.getpass    # seam: tests replace it; the ONLY way a secret enters the CLI
WHICH = shutil.which               # seam
OBS_URL = "http://localhost:8090/"
FULL_CONTROL = ("Agents get full control of this machine: sudo, and Claude Code in bypassPermissions mode. "
                "That is the design. Run ASTRYX on a dedicated VM or machine, never on your daily laptop.")

CHANNELS = {
    "telegram": {"key": "TG_BOT_TOKEN", "ask": "Telegram bot token (from @BotFather)",
                 "routes": "bridges/routes-telegram.json", "unit": "astryx-telegram.service"},
    "discord": {"key": "DISCORD_BOT_TOKEN", "ask": "Discord bot token (Developer Portal → Bot → Reset Token)",
                "routes": "bridges/routes-discord.json", "unit": "astryx-discord.service"},
    "whatsapp": {"key": "WA_WEBHOOK_SECRET", "ask": "WhatsApp webhook secret (press Enter to generate one)",
                 "routes": "bridges/routes-whatsapp.json", "unit": "astryx-whatsapp.service", "generate": True},
}


class CliError(Exception):
    """A user-facing failure: printed as one calm line plus a fix, never a traceback."""

    def __init__(self, msg, fix=None, code=1):
        super().__init__(msg)
        self.fix, self.code = fix, code


# ------------------------------------------------------------------ plumbing
class Ctx:
    def __init__(self, home: Path | None = None, ui: UI | None = None):
        if home is not None:
            self.home, self.rung = Path(home).expanduser().resolve(), "--home"
        else:
            self.home, self.rung = paths.resolve_home()
        self.ui = ui or UI()

    @property
    def root(self) -> Path | None:
        return tree.org_root(self.home)

    def need_root(self) -> Path:
        r = self.root
        if r is None:
            raise CliError(f"no org at {self.home} yet", fix="astryx init")
        return r

    def env(self) -> dict:
        e = dict(os.environ)
        e["ASTRYX_HOME"] = str(self.home)
        return e


def run(cmd, cwd=None, capture=False, env=None, timeout=None):
    """Run a command. capture=False streams to the terminal (rc only); a missing binary is rc 127."""
    try:
        return RUNNER(cmd, cwd=cwd, env=env, timeout=timeout, text=True,
                      capture_output=capture, check=False)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]}: not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"{cmd[0]}: timed out")


def out(cmd, **kw) -> str:
    r = run(cmd, capture=True, **kw)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def init_sh(ctx: Ctx, *args) -> int:
    root = ctx.need_root()
    return run(["bash", str(root / "init.sh"), *args], cwd=root, env=ctx.env()).returncode


def script(ctx: Ctx, rel: str, *args) -> int:
    root = ctx.need_root()
    p = root / rel
    if not p.is_file():
        raise CliError(f"{rel} is missing from {root}", fix="astryx init")
    return run(["bash", str(p), *args], cwd=root, env=ctx.env()).returncode


# ------------------------------------------------------------------ preflight
def _node_ok(v: str) -> bool:
    m = re.match(r"v?(\d+)", v or "")
    return bool(m) and int(m.group(1)) >= 20


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def pid1() -> str:
    try:
        return Path("/proc/1/comm").read_text().strip()
    except OSError:
        return ""


def preflight() -> list[dict]:
    """Each check: state ok|fail|skip, label, fix, hard (a hard fail stops init)."""
    mac = sys.platform == "darwin"
    pkg = "brew install" if mac else "sudo apt install -y"
    checks = []

    def add(state, label, fix=None, hard=True, detail=None):
        checks.append({"state": state, "label": label, "fix": fix, "hard": hard, "detail": detail})

    v = sys.version_info
    add("ok" if v >= (3, 12) else "fail", f"python {v.major}.{v.minor}",
        None if v >= (3, 12) else "install Python 3.12+, then: pip install astryx")
    if WHICH("docker"):
        ok = run(["docker", "info", "--format", "{{.ServerVersion}}"], capture=True, timeout=20).returncode == 0
        add("ok" if ok else "fail", "docker" if ok else "docker is installed but the daemon isn't reachable",
            None if ok else ("start Docker Desktop" if mac else
                             "sudo systemctl enable --now docker && sudo usermod -aG docker $USER  (then log in again)"))
    else:
        add("fail", "docker", "install Docker Desktop (https://docs.docker.com/desktop/)" if mac
            else "curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER")
    add("ok" if WHICH("tmux") else "fail", "tmux", None if WHICH("tmux") else f"{pkg} tmux")
    nv = out(["node", "--version"]) if WHICH("node") else ""
    add("ok" if _node_ok(nv) else "fail", f"node {nv or '(missing)'}" + ("" if _node_ok(nv) else ", need 20+"),
        None if _node_ok(nv) else ("brew install node" if mac else
                                   "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs"))
    add("ok" if WHICH("git") else "fail", "git", None if WHICH("git") else f"{pkg} git")
    if WHICH("claude"):
        add("ok", "claude CLI")
        logged = (Path.home() / ".claude" / ".credentials.json").is_file() or \
            bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
        add("ok" if logged else "skip", "claude login" if logged else "claude login not found",
            None if logged else "run `claude` once and log in (or set ANTHROPIC_API_KEY)", hard=False)
    else:
        add("fail", "claude CLI", "curl -fsSL https://claude.ai/install.sh | bash")
    if mac:
        add("skip", "launchd (macOS)", hard=False,
            detail="the units are systemd; on macOS run services in the background and the pulse from cron (CLAUDE.md)")
    elif is_wsl():
        if pid1() == "systemd":
            add("ok", "WSL2 with systemd")
        else:
            add("fail", "WSL2 without systemd (PID 1 is not systemd)",
                "add `[boot]` + `systemd=true` to /etc/wsl.conf, then run `wsl --shutdown` from Windows and reopen")
        add("skip", "WSL: a sleeping machine is a sleeping org", hard=False,
            detail="keep the Windows host awake, or run ASTRYX on an always-on machine")
    elif Path("/run/systemd/system").is_dir():
        add("ok", "systemd")
    else:
        add("fail", "systemd not running", "ASTRYX needs systemd (a standard Linux server, or WSL2 with systemd)")
    return checks


def show_checks(ui: UI, checks) -> bool:
    for c in checks:
        ui.step(c["state"], c["label"], fix=c["fix"], detail=c["detail"])
    return not any(c["state"] == "fail" and c["hard"] for c in checks)


# ------------------------------------------------------------------ verbs
def cmd_init(ctx: Ctx, a) -> int:
    ui = ctx.ui
    ui.header("init", "a minimal bootstrap, then the seed takes over")
    ui.section("1  Preflight")
    if not show_checks(ui, preflight()):
        ui.blank()
        raise CliError("fix the ✗ lines above, then run `astryx init` again (it picks up where it stopped)")

    ui.section("2  Home")
    ui.step("info", f"{ctx.home}", detail=f"chosen by: {ctx.rung}  (override with --home DIR or ASTRYX_HOME)")
    ui.warn(f"  {FULL_CONTROL}")
    if not a.yes:
        if not sys.stdin.isatty():
            raise CliError("not a terminal, so nothing was confirmed", fix="astryx init --yes")
        if input("  Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            ui.dim("  stopped; nothing changed.")
            return 1

    ui.section("3  Code")
    dev = paths.checkout_root()
    if dev is not None and dev == ctx.home:
        ui.step("ok", "dev checkout: the org runs from this tree")
    else:
        try:
            n = tree.materialize(ctx.home)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
            raise CliError(f"could not install the runtime tree into {ctx.home}: {e}")
        tree.write_marker(ctx.home, astryx.__version__)
        ui.step("ok", f"runtime tree in place ({n['new']} new, {n['updated']} updated, {n['same']} unchanged)",
                detail=f"from the {n['source']}")

    ui.section("4  Bootstrap (init.sh)")
    ui.dim("  postgres in docker, schema, deps, org identity, units, the seed.")
    ui.dim("  lines that need sudo are printed for you to run; nothing here runs sudo by itself.")
    ui.blank()
    rc = init_sh(ctx)
    ui.blank()
    if rc != 0:
        raise CliError(f"init.sh stopped (rc {rc})", fix="astryx doctor   then   astryx init   (idempotent)", code=rc)
    ui.step("ok", "bootstrap complete")

    ui.section("5  Handoff")
    if run(["tmux", "has-session", "-t", "=ax-seed"], capture=True).returncode == 0:
        ui.step("ok", "the seed is up; it will walk you through the rest")
    else:
        ui.step("skip", "the seed isn't up yet", fix="astryx spawn seed")
    ui.blank()
    ui.note("  Talk to it:")
    ui.cmd("tmux attach -t ax-seed          # detach with Ctrl-b d")
    ui.note(f"  or open the observatory: {OBS_URL}  (key: in {ctx.home / '.env'} as OBS_KEY)")
    ui.note("  Check on things any time:")
    ui.cmd("astryx status")
    return 0


def cmd_doctor(ctx: Ctx, a) -> int:
    if ctx.root is None:
        ctx.ui.header("doctor", f"no org at {ctx.home} yet; checking the machine")
        ok = show_checks(ctx.ui, preflight())
        ctx.ui.blank()
        ctx.ui.note("  next: astryx init" if ok else "  fix the ✗ lines, then: astryx init")
        return 0 if ok else 1
    return init_sh(ctx, "doctor")


def _residents() -> list[str]:
    names = out(["tmux", "ls", "-F", "#{session_name}"]).splitlines()
    return sorted(n[3:] for n in names if n.startswith("ax-"))


def _services() -> list[tuple[str, str]]:
    rows = []
    for line in out(["systemctl", "list-units", "astryx-*", "--all", "--no-legend", "--plain"]).splitlines():
        f = line.split()
        if len(f) >= 4:
            rows.append((f[0], f"{f[2]}/{f[3]}"))
    return rows


def _pulse_next() -> str:
    raw = out(["systemctl", "list-timers", "astryx-pulse.timer", "--all", "-o", "json"])
    try:
        t = json.loads(raw)[0]
    except (ValueError, IndexError, KeyError):
        return ""
    import datetime as _dt
    if t.get("next"):
        return "next fire " + _dt.datetime.fromtimestamp(t["next"] / 1e6).strftime("%Y-%m-%d %H:%M:%S")
    if t.get("last"):
        return "firing now (last fired " + _dt.datetime.fromtimestamp(t["last"] / 1e6).strftime("%H:%M:%S") + ")"
    return "never fired"


def _overview() -> dict | None:
    try:
        with urllib.request.urlopen(OBS_URL + "api/overview", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def cmd_status(ctx: Ctx, a) -> int:
    ui = ctx.ui
    ui.header("status", f"home {ctx.home}")
    res = _residents()
    if "seed" in res:
        ui.step("ok", f"{len(res)} residents: {', '.join(res)}")
    else:
        ui.step("fail", f"seed not resident ({len(res)} other residents)" if res else "no residents",
                fix="astryx spawn seed")
    svcs = _services()
    if svcs:
        bad = [u for u, s in svcs if not s.startswith(("active", "activating", "reloading", "inactive/dead"))]
        ui.step("fail" if bad else "ok", f"{len(svcs)} astryx units" + (f", {len(bad)} unhealthy" if bad else ""),
                fix="journalctl -u <unit> -n 50" if bad else None)
        ui.table("", ["unit", "state"], svcs)
    else:
        ui.step("skip", "no astryx units loaded", fix="astryx up   (after astryx init)")
    pause = ctx.home / "var" / "org_pause.json"
    if pause.is_file():
        try:
            d = json.loads(pause.read_text())
            ui.step("skip", f"pulse PAUSED: {d.get('reason', '')}", fix="astryx pause off")
        except ValueError:
            ui.step("skip", "pulse pause declared", fix="astryx pause status")
    nxt = _pulse_next()
    timer_on = dict(svcs).get("astryx-pulse.timer", "").startswith("active")
    ui.step("ok" if timer_on and nxt else "skip", f"pulse timer: {nxt or 'not installed'}",
            fix=None if timer_on or not nxt else "astryx up")
    ov = _overview()
    if ov:
        parts = [f"{k.replace('_', ' ')} {v}" for k, v in ov.items() if isinstance(v, (int, float))]
        ui.step("ok", f"observatory {OBS_URL}", detail=", ".join(parts))
    else:
        ui.step("skip", f"observatory not answering at {OBS_URL}", fix="astryx up")
    ui.dim(f"  observatory key: in {ctx.home / '.env'} as OBS_KEY")
    return 0


def _can_sudo() -> bool:
    return run(["sudo", "-n", "true"], capture=True, timeout=10).returncode == 0


def _unit_files() -> list[str]:
    names = []
    for line in out(["systemctl", "list-unit-files", "astryx-*", "--no-legend"]).splitlines():
        n = line.split()[0] if line.split() else ""
        if n and "@" not in n:
            names.append(n)
    return names


def _do(ctx: Ctx, lines: list[list[str]], a) -> int:
    ui = ctx.ui
    if a.print or not _can_sudo():
        ui.note("  run these (they need sudo):" if not a.print else "  the commands:")
        for c in lines:
            ui.cmd(" ".join(_q(x) for x in c))
        return 0
    rc = 0
    for c in lines:
        ui.cmd(" ".join(_q(x) for x in c))
        r = run(c, cwd=ctx.root, env=ctx.env()).returncode
        ui.step("ok" if r == 0 else "fail", " ".join(c[:4]) + (" …" if len(c) > 4 else ""))
        rc = rc or r
    return rc


def _q(s: str) -> str:
    return s if re.fullmatch(r"[\w./:=@%+-]+", s) else "'" + s.replace("'", "'\\''") + "'"


def cmd_up(ctx: Ctx, a) -> int:
    root = ctx.need_root()
    ctx.ui.header("up")
    units = _unit_files()
    svcs = [u for u in units if u.endswith(".service") and u != "astryx-pulse.service"]
    if not units:
        raise CliError("no astryx units are installed yet", fix="astryx init   (it prints the install lines)")
    lines = [["sudo", "systemctl", "start", *svcs]] if svcs else []
    if (ctx.home / "var" / "org_pause.json").is_file():
        lines.append([str(root / "scripts" / "pause.sh"), "off"])
    else:
        lines.append(["sudo", "systemctl", "start", "astryx-pulse.timer"])
    return _do(ctx, lines, a)


def cmd_down(ctx: Ctx, a) -> int:
    root = ctx.need_root()
    ctx.ui.header("down", "the pulse is paused WITH a declared reason, so the witness reads PAUSED, not DOWN")
    reason = a.reason or f"astryx down by {getpass.getuser()}"
    svcs = [u for u in _unit_files() if u.endswith(".service") and u != "astryx-pulse.service"]
    lines = [[str(root / "scripts" / "pause.sh"), "on", reason]]
    if svcs:
        lines.append(["sudo", "systemctl", "stop", *svcs])
    rc = _do(ctx, lines, a)
    ctx.ui.dim("  residents keep running in tmux; stop one with: tmux kill-session -t ax-<name>")
    return rc


def cmd_pause(ctx: Ctx, a) -> int:
    args = [a.action] + ([a.reason] if a.reason else []) + ([a.until] if a.until else [])
    if a.action == "on" and not a.reason:
        raise CliError("a pause needs a reason", fix='astryx pause on "<reason>" [until]', code=2)
    return script(ctx, "scripts/pause.sh", *args)


def cmd_spawn(ctx: Ctx, a) -> int:
    return script(ctx, "scripts/spawn.sh", a.agent)


def cmd_retire(ctx: Ctx, a) -> int:
    root = ctx.need_root()
    ui = ctx.ui
    if a.agent == "seed":
        raise CliError("the seed is the founding agent; it isn't retired")
    r = run([sys.executable, str(root / "src" / "astryx" / "core" / "charter.py"), a.agent], cwd=root, capture=True)
    path = (r.stdout or "").strip() if r.returncode == 0 else ""
    ui.header(f"retire {a.agent}", "retiring is the seed's act: archive the charter; the nucleus stops resurrecting it")
    if not path:
        ui.step("skip", f"no charter named '{a.agent}' under agents/")
        return 1
    ui.note("  Ask the seed on the wire (`retire " + a.agent + "`), or by hand:")
    ui.cmd(f"printf '\\n## Tombstone\\nRetired: <why>\\n' >> {path}   # spawn.sh then refuses the name; it rests")
    ui.cmd(f"tmux kill-session -t ax-{a.agent}")
    ui.dim("  a tombstoned name is held forever; spawn-all and the pulse skip it.")
    return 0


def cmd_federate(ctx: Ctx, a) -> int:
    root = ctx.need_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import importlib
        mod = importlib.import_module("astryx.federation.federate")
    except ModuleNotFoundError as e:
        if e.name not in ("astryx.federation.federate", "nucleus"):
            raise
        ctx.ui.header("federate", "the federation wizard (relay or public address) is coming")
        ctx.ui.note("  For now, join a peer by hand:")
        ctx.ui.cmd("astryx join http://their-host:8845")
        return 0
    fn = getattr(mod, "main")
    return int(fn(a.rest) if inspect.signature(fn).parameters else fn() or 0)


def _env_file(ctx: Ctx) -> Path:
    return ctx.home / ".env"


def cmd_connect(ctx: Ctx, a) -> int:
    if a.target not in CHANNELS:
        return init_sh(ctx, "connect", a.target)           # an agent: attach read-only
    ch = CHANNELS[a.target]
    ui, key, envf = ctx.ui, ch["key"], _env_file(ctx)
    ctx.need_root()
    ui.header(f"connect {a.target}", "the credential is read hidden and written only to .env (mode 600)")
    if config.is_set(key, envf):
        if not sys.stdin.isatty() and not a.replace:
            ui.step("ok", f"{key} is already set in {envf}", detail="replace it with --replace")
            return _channel_next(ctx, a.target)
        if not a.replace and input(f"  {key} is already set. Replace it? [y/N] ").strip().lower() not in ("y", "yes"):
            ui.step("ok", f"{key} kept")
            return _channel_next(ctx, a.target)
    value = SECRET_PROMPT(f"  {ch['ask']}: ").strip()
    if not value:
        if not ch.get("generate"):
            raise CliError("nothing entered; nothing changed")
        value = secrets.token_hex(32)
        ui.step("ok", f"{key} generated")
    if "\n" in value or " " in value:
        raise CliError("that doesn't look like a token (it has spaces or line breaks); nothing changed")
    config.set_env(key, value, envf)
    del value
    ui.step("ok", f"{key} saved in {envf} (mode 600)")
    return _channel_next(ctx, a.target)


def _channel_next(ctx: Ctx, name: str) -> int:
    ch, ui, root = CHANNELS[name], ctx.ui, ctx.need_root()
    if name == "whatsapp":
        if not config.is_set("WA_CLI", _env_file(ctx)):
            config.set_env("WA_CLI", "docker exec wacli-sync wacli", _env_file(ctx))
        ui.note("  the rest of WhatsApp (wacli in docker, the QR, the bridge):")
        return init_sh(ctx, "channels")
    routes = root / ch["routes"]
    ui.step("ok" if routes.is_file() else "skip", f"routes: {ch['routes']}",
            fix=None if routes.is_file() else f"create {ch['routes']} (your chats and trusted senders; "
                                              "see bridges/routes.example.json)")
    ui.note("  then generate and start the bridge:")
    ui.cmd("astryx init")
    ui.cmd(f"sudo ./scripts/deploy.sh units && sudo systemctl enable --now {ch['unit']}")
    return 0


def cmd_channels(ctx: Ctx, a) -> int:
    root = ctx.need_root()
    ctx.ui.header("channels", "credentials show only as set / missing")
    env = config.read_env(_env_file(ctx))
    rows = []
    for name, ch in CHANNELS.items():
        state = out(["systemctl", "is-active", ch["unit"]]) or "inactive"
        rows.append((name, "set" if env.get(ch["key"]) else "missing",
                     "yes" if (root / ch["routes"]).is_file() else "no", state))
    ctx.ui.table("", ["channel", "credential", "routes", "bridge"], rows)
    ctx.ui.blank()
    ctx.ui.dim("  connect one: astryx connect telegram|discord|whatsapp")
    return 0


def cmd_wall(ctx: Ctx, a) -> int:
    return init_sh(ctx, "wall")


def cmd_join(ctx: Ctx, a) -> int:
    return init_sh(ctx, "join", a.url)


def cmd_migrate(ctx: Ctx, a) -> int:
    ctx.ui.note("not yet: schema.sql is applied by `astryx init` (the migration runner is plan-10224 S2).")
    return 0


def cmd_upgrade(ctx: Ctx, a) -> int:
    ui = ctx.ui
    ui.header("upgrade")
    dev = paths.checkout_root()
    if dev is not None:
        ui.step("skip", f"this is a dev checkout ({dev}): it upgrades with git, not pip",
                fix=f"git -C {dev} pull   then   astryx init")
        return 0
    r = run([sys.executable, "-m", "pip", "install", "-U", "astryx"])
    if r.returncode != 0:
        raise CliError("pip could not upgrade astryx", fix=f"{sys.executable} -m pip install -U astryx")
    ui.step("ok", "package upgraded")
    # -P: never put cwd on sys.path. Run from inside a HOME, `-m astryx` would load HOME/astryx.py and the OLD
    # src/astryx copy beside it instead of the package pip just upgraded.
    r = run([sys.executable, "-P", "-m", "astryx", "init", "--yes", "--home", str(ctx.home)])
    if r.returncode != 0:
        raise CliError("init after the upgrade stopped", fix="astryx doctor", code=r.returncode)
    ui.note("  restart to load the new code, then ask the seed for a restart sweep:")
    ui.cmd("astryx down && astryx up")
    return 0


def cmd_version(ctx: Ctx, a) -> int:
    print(f"astryx {astryx.__version__}")
    print(f"  code   {paths.code()}")
    print(f"  home   {ctx.home}  ({ctx.rung})")
    print(f"  python {platform.python_version()} ({sys.executable})")
    return 0


# ------------------------------------------------------------------ parser
VERBS = [
    ("init", cmd_init, "set up an org here and start the seed (idempotent)"),
    ("doctor", cmd_doctor, "check everything; print the fix for anything wrong"),
    ("status", cmd_status, "residents, services, the pulse, the observatory"),
    ("up", cmd_up, "start the services and the pulse"),
    ("down", cmd_down, "pause the pulse (with a reason) and stop the services"),
    ("pause", cmd_pause, "pause or resume the org's clock"),
    ("spawn", cmd_spawn, "bring an agent to life (or resume it)"),
    ("retire", cmd_retire, "how to retire an agent"),
    ("connect", cmd_connect, "wire a channel (telegram|discord|whatsapp), or watch an agent"),
    ("channels", cmd_channels, "which channels are wired"),
    ("federate", cmd_federate, "join the network of orgs"),
    ("join", cmd_join, "introduce this org to a peer"),
    ("wall", cmd_wall, "watch the org think"),
    ("migrate", cmd_migrate, "apply database migrations"),
    ("upgrade", cmd_upgrade, "upgrade astryx, then re-run init"),
    ("version", cmd_version, "version, code and home paths"),
]


class _Fmt(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=22, width=min(100, shutil.get_terminal_size().columns))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="astryx", formatter_class=_Fmt,
        description="ASTRYX — an org of Claude Code agents on one machine.\n\n"
                    "Start with `astryx init`: it checks the machine, sets up the org, and starts the seed,\n"
                    "which walks you through the rest.",
        epilog="Every verb works by hand too. Home: --home, else ASTRYX_HOME (a git checkout ignores it unless it\n"
               "names that checkout), else the org you're in.\n"
               "Docs: README.md · CLAUDE.md")
    p.add_argument("--home", metavar="DIR", help="the org's home directory")
    sub = p.add_subparsers(dest="verb", metavar="<command>", title="commands")
    sp = {}
    for name, fn, help_ in VERBS:
        sp[name] = s = sub.add_parser(name, help=help_, description=help_[0].upper() + help_[1:] + ".",
                                      formatter_class=_Fmt)
        s.set_defaults(fn=fn)
        s.add_argument("--home", metavar="DIR", default=argparse.SUPPRESS, help="the org's home directory")
    sp["init"].add_argument("--yes", "-y", action="store_true", help="don't ask; accept the defaults")
    for v in ("up", "down"):
        sp[v].add_argument("--print", action="store_true", help="only print the commands")
    sp["down"].add_argument("--reason", help="why (recorded with the pause)")
    sp["pause"].add_argument("action", choices=["on", "off", "status"])
    sp["pause"].add_argument("reason", nargs="?", help="why (required for `on`)")
    sp["pause"].add_argument("until", nargs="?", help='when it ends, e.g. "tomorrow 9am"')
    sp["spawn"].add_argument("agent")
    sp["retire"].add_argument("agent")
    sp["connect"].add_argument("target", metavar="telegram|discord|whatsapp|<agent>")
    sp["connect"].add_argument("--replace", action="store_true", help="replace a credential that is already set")
    sp["join"].add_argument("url", metavar="PEER_URL")
    sp["federate"].set_defaults(rest=[])   # every argument the CLI doesn't know passes to the wizard, in order (main)
    return p


PASSTHROUGH = ("federate",)   # verbs whose own flags (--relay, --skip, ...) belong to the tool behind them


def main(argv=None) -> int:
    p = parser()
    # argparse's REMAINDER can't begin with a `--flag`: a passthrough verb takes every argument the CLI
    # itself doesn't know, so `astryx federate --home D --relay URL` gives --home to us and the rest to it
    a, extra = p.parse_known_args(argv)
    if extra:
        if getattr(a, "verb", None) not in PASSTHROUGH:
            p.error(f"unrecognized arguments: {' '.join(extra)}")
        a.rest = extra
    if not getattr(a, "verb", None):
        p.print_help()
        return 0
    ui = UI()
    try:
        ctx = Ctx(getattr(a, "home", None), ui)
        return int(a.fn(ctx, a) or 0)
    except CliError as e:
        ui.error(f"✗ {e}")
        if e.fix:
            ui.warn(f"  fix: {e.fix}")
        return e.code
    except KeyboardInterrupt:
        ui.blank()
        ui.dim("interrupted; nothing more was done.")
        return 130
    except (EOFError, BrokenPipeError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
