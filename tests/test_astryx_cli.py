#!/usr/bin/env python3
"""Oracle: the `astryx` CLI (plan-10224 S3). Every external command goes through cli.RUNNER and every secret
through cli.SECRET_PROMPT; both are stubbed here, so nothing runs: no tmux, no systemctl, no sudo, no init.sh.

Arms: --help reads every verb; each verb dispatches to the right script with HOME as cwd and ASTRYX_HOME set;
user errors print one line and a fix, never a traceback; `init` stops on a hard preflight failure, refuses to run
unconfirmed off a terminal, installs only the allowlisted tree into a fresh HOME and hands off to the seed;
credentials (connect, channels, status) are read hidden, written to .env in place at mode 600, and never printed.
"""
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from astryx import cli  # noqa: E402

fails = []
OBS = "obs-SECRET-a1b2c3"
TOKEN = "tg-SECRET-7f6e5d4c"


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


class Fake:
    def __init__(self, sudo=False, init_rc=0, charter=""):
        self.calls, self.sudo, self.init_rc, self.charter = [], sudo, init_rc, charter

    def __call__(self, cmd, cwd=None, env=None, timeout=None, text=True, capture_output=False, check=False):
        self.calls.append({"cmd": list(cmd), "cwd": cwd, "env": env})
        c, rc, so = list(cmd), 0, ""
        if c[:2] == ["tmux", "ls"]:   # org-home: matches a MOCKED call's argv (one org: orgs.tmux() is ["tmux"])
            so = "ax-seed\nax-forge\nscratch\n"
        elif c[:2] == ["systemctl", "list-units"]:
            so = ("astryx-observatory.service loaded active running obs\n"
                  "astryx-pulse.timer loaded active waiting pulse\n")
        elif c[:2] == ["systemctl", "list-timers"]:
            so = json.dumps([{"next": 1791967260000000, "last": 1791967200000000, "unit": "astryx-pulse.timer"}])
        elif c[:2] == ["systemctl", "list-unit-files"]:
            so = ("astryx-observatory.service enabled enabled\nastryx-pulse.service static -\n"
                  "astryx-pulse.timer enabled enabled\nastryx-runner@.service static -\n")
        elif c[:2] == ["systemctl", "is-active"]:
            so = "active"
        elif c[:3] == ["sudo", "-n", "true"]:
            rc = 0 if self.sudo else 1
        elif len(c) > 1 and c[1].endswith("charter.py"):
            rc, so = (0, self.charter) if self.charter else (1, "")
        elif len(c) > 1 and c[0] == "bash" and c[1].endswith("init.sh") and len(c) == 2:
            rc = self.init_rc
        return subprocess.CompletedProcess(cmd, rc, so if capture_output else None, "")

    def of(self, pred):
        return [x for x in self.calls if pred(x["cmd"])]


def home_tree():
    h = Path(tempfile.mkdtemp(prefix="astryx-cli-")).resolve()
    (h / "nucleus").mkdir()
    for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
        (h / _d).mkdir(parents=True, exist_ok=True)
    for f in ("init.sh", "scripts/pause.sh", "scripts/spawn.sh"):
        (h / f).write_text("#!/bin/sh\n")
    (h / ".env").write_text(f"ASTRYX_ORG=testorg\nOBS_KEY={OBS}\n# keep me\nASTRYX_DSN=postgresql://x\n")
    os.chmod(h / ".env", 0o640)
    return h


def call(argv, fake, prompt=None, stdin=""):
    cli.RUNNER = fake
    cli.SECRET_PROMPT = prompt or (lambda p="": (_ for _ in ()).throw(AssertionError("unexpected secret prompt")))
    buf = io.StringIO()
    old_in = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                rc = cli.main(argv)
            except SystemExit as e:
                rc = e.code
    finally:
        sys.stdin = old_in
    return rc, buf.getvalue()


def main():
    os.environ.pop("ASTRYX_HOME", None)
    cli._overview = lambda: {"agents": 2, "live": 2, "org": "testorg"}

    # ---- help
    rc, o = call(["--help"], Fake())
    arm("--help exits 0 and lists every verb", rc == 0 and all(f"    {v}" in o for v, _, _ in cli.VERBS), o[:300])
    for v, _, _ in cli.VERBS:
        rc, o = call([v, "--help"], Fake())
        if rc != 0 or "usage: astryx " + v not in o:
            arm(f"`astryx {v} --help`", False, o[:200])
            break
    else:
        arm("every verb's --help exits 0", True)
    rc, o = call([], Fake())
    arm("no verb prints the help, rc 0", rc == 0 and "astryx init" in o)

    h = home_tree()
    H = ["--home", str(h)]

    # ---- plain dispatch
    for argv, want in ((["doctor"], ["bash", str(h / "init.sh"), "doctor"]),
                       (["wall"], ["bash", str(h / "init.sh"), "wall"]),
                       (["join", "http://peer:8845"], ["bash", str(h / "init.sh"), "join", "http://peer:8845"]),
                       (["connect", "forge"], ["bash", str(h / "init.sh"), "connect", "forge"]),
                       (["spawn", "forge"], ["bash", str(h / "scripts/spawn.sh"), "forge"]),
                       (["pause", "on", "maintenance", "tomorrow 9am"],
                        ["bash", str(h / "scripts/pause.sh"), "on", "maintenance", "tomorrow 9am"]),
                       (["pause", "status"], ["bash", str(h / "scripts/pause.sh"), "status"])):
        f = Fake()
        rc, o = call(argv + H, f)
        c = f.calls[-1] if f.calls else {}
        arm(f"`astryx {' '.join(argv)}` -> {' '.join(want[1:])[len(str(h)) + 1:]}",
            rc == 0 and c.get("cmd") == want and c.get("cwd") == h and c["env"].get("ASTRYX_HOME") == str(h),
            str(c)[:300])
    f = Fake()
    rc, o = call(["pause", "on"] + H, f)
    arm("`pause on` without a reason: rc 2, a fix, nothing run", rc == 2 and "fix:" in o and not f.calls, o)

    # ---- down / up
    f = Fake(sudo=False)
    rc, o = call(["down", "--reason", "disk work"] + H, f)
    arm("down without sudo PRINTS pause.sh on + systemctl stop, runs neither",
        rc == 0 and "pause.sh on 'disk work'" in o and "sudo systemctl stop astryx-observatory.service" in o
        and not f.of(lambda c: "pause.sh" in " ".join(c) or c[:2] == ["sudo", "systemctl"]), o)
    arm("down never stops the pulse with a bare systemctl (it pauses with a reason)",
        "astryx-pulse.timer" not in o and "astryx-runner@" not in o, o)
    f = Fake(sudo=True)
    rc, o = call(["down"] + H, f)
    ran = [x["cmd"] for x in f.calls if x["cmd"][0] in (str(h / "scripts/pause.sh"), "sudo") and x["cmd"][1] != "-n"]
    arm("down with sudo RUNS pause.sh on <reason> first, then the stop",
        len(ran) == 2 and ran[0][:2] == [str(h / "scripts/pause.sh"), "on"] and ran[0][2]
        and ran[1] == ["sudo", "systemctl", "stop", "astryx-observatory.service"], str(ran))
    (h / "var").mkdir()
    (h / "var" / "org_pause.json").write_text(json.dumps({"reason": "disk work"}))
    f = Fake(sudo=True)
    rc, o = call(["up"] + H, f)
    ran = [x["cmd"] for x in f.calls if x["cmd"][0] in (str(h / "scripts/pause.sh"), "sudo") and x["cmd"][1] != "-n"]
    arm("up while paused: start the services, then pause.sh off (never a bare timer start)",
        ran == [["sudo", "systemctl", "start", "astryx-observatory.service"], [str(h / "scripts/pause.sh"), "off"]],
        str(ran))
    (h / "var" / "org_pause.json").unlink()
    f = Fake(sudo=True)
    rc, o = call(["up", "--print"] + H, f)
    arm("up --print runs nothing and names the timer start",
        "sudo systemctl start astryx-pulse.timer" in o and not f.of(lambda c: c[:2] == ["sudo", "systemctl"]), o)

    # ---- federate
    # goal 10224 S4: the wizard ships IN the package (astryx.federation.federate), so "not there yet" can't
    # happen. The fake is a module object in its place, never the real wizard (it would knock on the live relay).
    import types
    fake = types.ModuleType("astryx.federation.federate")
    fake.main = lambda argv: (h / "fed.out").write_text(repr(argv)) and 0
    real_fed = sys.modules.get("astryx.federation.federate")
    sys.modules["astryx.federation.federate"] = fake
    sys.path.insert(0, str(h))
    rc, o = call(["federate"] + H + ["relay"], Fake())
    arm("federate calls astryx.federation.federate.main(rest) when it exists",
        rc == 0 and (h / "fed.out").is_file() and (h / "fed.out").read_text() == "['relay']",
        (h / "fed.out").read_text() if (h / "fed.out").is_file() else o)
    rc, o = call(["federate"] + H + ["--relay", "https://r.example", "--no-introduce"], Fake())
    arm("federate passes its own --flags through to the wizard (argparse REMAINDER can't)",
        rc == 0 and (h / "fed.out").is_file()
        and (h / "fed.out").read_text() == "['--relay', 'https://r.example', '--no-introduce']",
        (h / "fed.out").read_text() if (h / "fed.out").is_file() else o)
    rc, o = call(["status"] + H + ["--bogus"], Fake())
    arm("an unknown flag on a NON-passthrough verb is still an error", rc != 0, (rc, o))
    sys.path.remove(str(h))
    if real_fed is None:
        sys.modules.pop("astryx.federation.federate", None)
    else:
        sys.modules["astryx.federation.federate"] = real_fed

    # ---- migrate / version / retire / user errors
    rc, o = call(["migrate"] + H, Fake())
    arm("migrate: not yet, schema.sql is applied by init", rc == 0 and "not yet" in o and "schema.sql" in o, o)
    rc, o = call(["version"] + H, Fake())
    arm("version prints the version and the home", rc == 0 and o.startswith("astryx 0.") and str(h) in o, o)
    real_root = cli.paths.checkout_root
    cli.paths.checkout_root = lambda *a: None                               # as from a wheel install
    f = Fake()
    rc, o = call(["upgrade"] + H, f)
    cmds = [x["cmd"] for x in f.calls]
    arm("upgrade (wheel): pip -U astryx, then init with -P (cwd never shadows the new package), restart hint",
        rc == 0 and cmds[0][1:] == ["-m", "pip", "install", "-U", "astryx"]
        and cmds[1][1:] == ["-P", "-m", "astryx", "init", "--yes", "--home", str(h)] and "astryx down && astryx up" in o,
        str(cmds) + o)
    cli.paths.checkout_root = real_root
    f = Fake()
    rc, o = call(["upgrade"] + H, f)
    arm("upgrade in a dev checkout: git, not pip; nothing run", rc == 0 and "git" in o and not f.calls, o)
    rc, o = call(["retire", "seed"] + H, Fake())
    arm("retire seed: refused with one line, no traceback", rc == 1 and "Traceback" not in o and "seed" in o, o)
    f = Fake(charter=str(h / "agents/forge.md"))
    rc, o = call(["retire", "forge"] + H, f)
    arm("retire <agent>: prints the tombstone + kill-session guidance, runs neither",
        rc == 0 and "## Tombstone" in o and "tmux kill-session -t ax-forge" in o
        and not f.of(lambda c: c[0] == "tmux"), o)
    empty = Path(tempfile.mkdtemp(prefix="astryx-empty-"))
    rc, o = call(["spawn", "x", "--home", str(empty)], Fake())
    arm("a verb with no org at HOME: one line + `fix: astryx init`, no traceback",
        rc == 1 and "fix: astryx init" in o and "Traceback" not in o, o)
    r = subprocess.run([sys.executable, "-m", "astryx", "frobnicate"], cwd=REPO / "src", capture_output=True,
                       text=True, timeout=60)
    arm("an unknown verb: argparse usage, rc 2, no traceback",
        r.returncode == 2 and "Traceback" not in r.stderr and "invalid choice" in r.stderr, r.stderr[-300:])

    # ---- doctor with no org: the machine preflight, never init.sh
    cli_which, cli_pre = cli.WHICH, cli.preflight
    cli.WHICH = lambda n: None
    f = Fake()
    rc, o = call(["doctor", "--home", str(empty)], f)
    arm("doctor with no org runs the preflight (✗ + fix lines), not init.sh",
        rc == 1 and "✗" in o and "fix:" in o and not f.of(lambda c: c[0] == "bash"), o[:400])
    cli.WHICH = cli_which

    # ---- init
    ok = [{"state": "ok", "label": "x", "fix": None, "hard": True, "detail": None}]
    cli.preflight = lambda: [dict(ok[0], state="fail", label="docker", fix="install docker")]
    f = Fake()
    rc, o = call(["init", "--yes"] + H, f)
    arm("init stops on a hard preflight failure, prints the fix, runs nothing",
        rc == 1 and "fix: install docker" in o and not f.of(lambda c: c[0] == "bash"), o)
    cli.preflight = lambda: ok
    f = Fake()
    rc, o = call(["init"] + H, f, stdin="")
    arm("init off a terminal without --yes: refuses, runs nothing",
        rc == 1 and "--yes" in o and not f.of(lambda c: c[0] == "bash"), o)
    fresh = Path(tempfile.mkdtemp(prefix="astryx-fresh-")) / "org"
    f = Fake()
    rc, o = call(["init", "--yes", "--home", str(fresh)], f)
    initc = f.of(lambda c: c[:2] == ["bash", str(fresh / "init.sh")])
    arm("init --yes into a fresh HOME: says full control + dedicated VM, installs the tree, runs its init.sh",
        rc == 0 and "full control" in o and "dedicated VM" in o and (fresh / "init.sh").is_file()
        and len(initc) == 1 and initc[0]["cwd"] == fresh, o[-600:])
    arm("init hands off to the seed (attach + observatory, key by location only)",
        "the seed is up" in o and "tmux attach -t ax-seed" in o and "as OBS_KEY" in o, o[-400:])
    arm("the installed tree holds the allowlist only (no tests/, harness/, docs/, .env, local.md, homes/)",
        (fresh / "scripts" / "spawn.sh").is_file() and (fresh / "agents" / "seed" / "seed.md").is_file()
        and not any((fresh / x).exists() for x in ("tests", "harness", "docs", ".env", "local.md", "homes")),
        str(sorted(p.name for p in fresh.iterdir())))
    arm("scripts are executable, the marker is written, the dispatcher link is relative",
        os.access(fresh / "init.sh", os.X_OK) and os.access(fresh / "scripts" / "pause.sh", os.X_OK)
        and (fresh / ".astryx").is_file() and os.readlink(fresh / "astryx") == "init.sh")
    f = Fake(init_rc=3)
    rc, o = call(["init", "--yes", "--home", str(fresh)], f)
    arm("init.sh failing: its rc comes back with `fix: astryx doctor`, no traceback",
        rc == 3 and "astryx doctor" in o and "Traceback" not in o, o[-300:])
    cli.preflight = cli_pre

    # ---- credentials: hidden prompt, in-place .env edit, never printed
    before = (h / ".env").read_text()
    asked = []
    rc, o = call(["connect", "telegram"] + H, Fake(), prompt=lambda p="": asked.append(p) or TOKEN)
    after = (h / ".env").read_text()
    arm("connect telegram reads the token through the hidden prompt", rc == 0 and len(asked) == 1, str(asked) + o)
    arm("connect telegram: .env keeps every other line and gains TG_BOT_TOKEN",
        after == before + f"TG_BOT_TOKEN={TOKEN}\n", repr(after))
    arm("connect telegram: .env is mode 600", stat.S_IMODE(os.stat(h / ".env").st_mode) == 0o600)
    arm("connect telegram: the token never reaches stdout", TOKEN not in o and "TG_BOT_TOKEN" in o, o)
    rc, o = call(["connect", "telegram"] + H, Fake())                      # set already, not a tty: kept
    arm("connect telegram again off a terminal: kept, no prompt", rc == 0 and "already set" in o, o)
    rc, o = call(["connect", "telegram", "--replace"] + H, Fake(), prompt=lambda p="": "tg-NEW-1")
    arm("connect telegram --replace swaps the value on the same line",
        (h / ".env").read_text() == before + "TG_BOT_TOKEN=tg-NEW-1\n" and "tg-NEW-1" not in o)
    rc, o = call(["connect", "discord"] + H, Fake(), prompt=lambda p="": "")
    arm("connect discord with nothing entered: nothing changed, rc 1",
        rc == 1 and "DISCORD_BOT_TOKEN" not in (h / ".env").read_text(), o)
    f = Fake()
    rc, o = call(["connect", "whatsapp"] + H, f, prompt=lambda p="": "")
    env = cli.config.read_env(h / ".env")
    gen = env.get("WA_WEBHOOK_SECRET", "")
    arm("connect whatsapp, Enter: a secret is generated, stored, never printed; init.sh channels runs",
        rc == 0 and len(gen) == 64 and gen not in o and env.get("WA_CLI") == "docker exec wacli-sync wacli"
        and f.of(lambda c: c == ["bash", str(h / "init.sh"), "channels"]), o)
    rc, o = call(["channels"] + H, Fake())
    arm("channels shows set/missing and no credential value",
        rc == 0 and "set" in o and "missing" in o and not any(v in o for v in ("tg-NEW-1", gen, OBS)), o)
    rc, o = call(["status"] + H, Fake())
    arm("status: residents, units, pulse, observatory, and WHERE the key lives, never the key",
        rc == 0 and "seed" in o and "astryx-observatory.service" in o and "next fire" in o
        and f"in {h / '.env'} as OBS_KEY" in o and OBS not in o, o)
    wa = [ln for ln in (REPO / "init.sh").read_text().splitlines() if "--webhook-secret" in ln]
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / ".env").write_text("WA_WEBHOOK_SECRET=deadbeefcafe0123\n")
        r = subprocess.run(["bash", "-c", 'say(){ echo -e "$*"; }\n' + "\n".join(wa)], cwd=td, capture_output=True,
                           text=True, timeout=30)
    arm("init.sh's WhatsApp docker line, rendered, reads the secret from .env and never prints it",
        len(wa) == 1 and "deadbeef" not in r.stdout and "$(sed -n 's/^WA_WEBHOOK_SECRET=//p'" in r.stdout,
        r.stdout + r.stderr)

    for d in (h, empty, fresh.parent):
        shutil.rmtree(d, ignore_errors=True)
    print(f"\n{'FAIL' if fails else 'ALL PASS'}: astryx cli ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
