#!/usr/bin/env python3
"""Oracle: init.sh's units() DECLARES senses, geoloc and growbot (seed #43920: all three ran or sat in systemd while
nothing generated them, so doctor read them as undeclared and a regenerate + deploy would have deleted two live ones).

The units() block is extracted from init.sh and run in bash (-euo pipefail) against a throwaway tree, each signal alone:
  senses   src/astryx/pulse/senses.py + a sensors/<agent>/*.py → astryx-senses.service; no sensor → none (writing a sensor IS
           deploying; an org without one grows no service).
  geoloc   bridges/geoloc.py + $HOME/.config/astryx/geoloc.env → astryx-geoloc.service (0.0.0.0:8766: the phone posts to
           it); either one absent → none.
  growbot  src/astryx/contrib/growbot_body.py + a LIVE charter granting growbot → the unit, ALWAYS; a REMOTE body (GROWBOT_BODY_URL
           elsewhere) puts it in UNITS_EXPECT_DISABLED (installed, NOT enabled), a local or empty one doesn't; a grant only
           in an .example.md → no unit.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


block = re.search(r"^units\(\) \{.*?^\}$", (REPO / "init.sh").read_text(), re.S | re.M)
want("init.sh carries the units() generator", bool(block))
if not block:
    sys.exit(1)


def gen(files: dict, env_text: str = "OBS_KEY=x\n") -> dict:
    """files: {relpath: text}; 'HOME/…' paths land under the throwaway $HOME."""
    with tempfile.TemporaryDirectory() as td:
        t = Path(td) / "org"
        home = Path(td) / "home"
        t.mkdir()
        home.mkdir()
        for rel, text in files.items():
            p = (home / rel[5:]) if rel.startswith("HOME/") else (t / rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (t / ".env").write_text(env_text)
        (t / "units.sh").write_text(block.group(0) + '\nUNITS_DIR=out units\necho "EXPECT=[${UNITS_EXPECT_DISABLED:-}]"\n')
        r = subprocess.run(["bash", "-euo", "pipefail", "units.sh"], cwd=t, capture_output=True, text=True,
                           env={"HOME": str(home), "USER": "tester", "PATH": "/usr/bin:/bin"})
        out = t / "out"
        m = re.search(r"EXPECT=\[(.*)\]", r.stdout)
        norm = lambda x: x.replace(str(t), "<ORG>").replace(str(home), "<HOME>")   # noqa: E731 (per-tree paths)
        return {"rc": r.returncode, "err": r.stderr, "expect": (m.group(1).split() if m else None),
                "units": {p.name: norm(p.read_text()) for p in out.iterdir()} if out.is_dir() else {}}


base = gen({})
want("the bare tree generates (rc 0) and declares none of the three",
     base["rc"] == 0 and not {"astryx-senses.service", "astryx-geoloc.service", "astryx-growbot.service"} & set(base["units"]),
     f"{base['rc']} {base['err'][-200:]} {sorted(base['units'])}")

print("senses:")
no_sensor = gen({"src/astryx/pulse/senses.py": ""})
want("RED control: the server module with NO sensor → no senses unit", "astryx-senses.service" not in no_sensor["units"])
s = gen({"src/astryx/pulse/senses.py": "", "sensors/seed/ping.py": ""})
su = s["units"].get("astryx-senses.service", "")
want("module + one sensor → astryx-senses.service, running src/astryx/pulse/senses.py, restarting, with [Install]",
     "src/astryx/pulse/senses.py" in su and "Restart=always" in su and "[Install]" in su and "User=tester" in su, su)

print("geoloc:")
want("RED control: the bridge without its env file → no geoloc unit",
     "astryx-geoloc.service" not in gen({"bridges/geoloc.py": ""})["units"])
want("RED control: the env file without the bridge → no geoloc unit",
     "astryx-geoloc.service" not in gen({"HOME/.config/astryx/geoloc.env": ""})["units"])
g = gen({"bridges/geoloc.py": "", "HOME/.config/astryx/geoloc.env": ""})
gu = g["units"].get("astryx-geoloc.service", "")
want("bridge + env file → astryx-geoloc.service on 0.0.0.0:8766 (the phone posts to it), env file from $HOME",
     "geoloc:app --host 0.0.0.0 --port 8766" in gu and "/.config/astryx/geoloc.env" in gu and "[Install]" in gu, gu)

print("growbot:")
grant = {"src/astryx/contrib/growbot_body.py": "", "agents/growbot.md": "# growbot\nGrants: growbot\n"}
want("RED control: a grant only in an .example.md → no growbot unit",
     "astryx-growbot.service" not in gen({"src/astryx/contrib/growbot_body.py": "",
                                          "agents/growbot.example.md": "Grants: growbot\n"})["units"])
loc = gen(grant)
want("a LOCAL body (no GROWBOT_BODY_URL) → the unit, and NOT expected-disabled (it must be enabled)",
     "astryx-growbot.service" in loc["units"] and loc["expect"] == [], f"{sorted(loc['units'])} {loc['expect']}")
lh = gen(grant, "OBS_KEY=x\nGROWBOT_BODY_URL=http://127.0.0.1:8470\n")
want("a loopback body URL counts as local", "astryx-growbot.service" in lh["units"] and lh["expect"] == [], str(lh["expect"]))
rem = gen(grant, "OBS_KEY=x\nGROWBOT_BODY_URL=http://192.0.2.7\n")
want("a REMOTE body → the unit is STILL declared (it exists on disk), and expected installed-but-disabled",
     "astryx-growbot.service" in rem["units"] and rem["expect"] == ["astryx-growbot.service"],
     f"{sorted(rem['units'])} {rem['expect']}")
want("…and the declared unit is the same file either way (only its STATE differs)",
     rem["units"].get("astryx-growbot.service") == loc["units"].get("astryx-growbot.service"))

# a3 #43932: the two consumers of the declaration, driven without a real systemd (a stub `systemctl` first on PATH)
print("enable list + doctor state (stub systemctl):")
src = (REPO / "init.sh").read_text()
helpers = src[src.index("_enable_list() {"):src.index("\nunits() {")]


def state(table: dict, expect_off: str):
    """table: {unit: is-enabled answer, or None for not-found}; returns the four lists _units_state fills."""
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "bin").mkdir()
        rows = "\n".join(f"{u} {v or 'not-found'}" for u, v in table.items())
        (t / "table").write_text(rows + "\n")
        (t / "bin" / "systemctl").write_text(
            "#!/usr/bin/env bash\n[ \"$1\" = is-enabled ] || exit 0\n"
            f"a=$(awk -v u=\"$2\" '$1==u{{print $2}}' {t}/table); [ -n \"$a\" ] || a=not-found\n"
            'echo "$a"; [ "$a" = enabled ] || [ "$a" = static ] && exit 0; [ "$a" = not-found ] && exit 4; exit 1\n')
        (t / "bin" / "systemctl").chmod(0o755)
        (t / "s.sh").write_text(helpers + f'\nUNITS_EXPECT_DISABLED="{expect_off}"\n_units_state {" ".join(table)}\n'
                                'echo "NE=[$notenabled] WO=[$wrongly_on] OM=[$off_missing] OK=[$off_ok]"\n')
        r = subprocess.run(["bash", "-euo", "pipefail", str(t / "s.sh")], capture_output=True, text=True,
                           env={"PATH": f"{t / 'bin'}:/usr/bin:/bin"})
        m = re.search(r"NE=\[(.*?)\] WO=\[(.*?)\] OM=\[(.*?)\] OK=\[(.*?)\]", r.stdout)
        return tuple(x.split() for x in m.groups()) if m else (r.returncode, r.stderr[-200:])


T = {"a-norm-en.service": "enabled", "a-norm-dis.service": "disabled", "a-norm-nf.service": None,
     "b-off-en.service": "enabled", "b-off-dis.service": "disabled", "b-off-nf.service": None}
OFF = "b-off-en.service b-off-dis.service b-off-nf.service"
ne, wo, om, ok_ = state(T, OFF)
want("normal × enabled → listed nowhere", "a-norm-en.service" not in ne + wo + om + ok_, str((ne, wo, om, ok_)))
want("normal × disabled → not enabled (won't survive a reboot)", "a-norm-dis.service" in ne)
want("normal × not-found → not enabled", "a-norm-nf.service" in ne)
want("declared-off × enabled → WRONGLY ON (a host service for a remote body)", wo == ["b-off-en.service"], str(wo))
want("declared-off × disabled → the ONLY name the ok line may carry", ok_ == ["b-off-dis.service"], str(ok_))
want("RED CONTROL (a3 F2): declared-off × not-found → NOT INSTALLED, never 'installed-but-disabled'",
     om == ["b-off-nf.service"] and "b-off-nf.service" not in ok_, str((om, ok_)))


def enable_list(files: dict, expect_off: str, *units):
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        for n, txt in files.items():
            (t / n).write_text(txt)
        (t / "s.sh").write_text(helpers + f'\nUNITS_EXPECT_DISABLED="{expect_off}"\necho "L=[$(_enable_list {t} {" ".join(units)})]"\n')
        r = subprocess.run(["bash", "-euo", "pipefail", str(t / "s.sh")], capture_output=True, text=True)
        m = re.search(r"L=\[(.*)\]", r.stdout)
        return m.group(1).split() if m else [f"ERR {r.stderr[-120:]}"]


inst = "[Unit]\n[Install]\nWantedBy=multi-user.target\n"
L = enable_list({"astryx-growbot.service": inst, "astryx-senses.service": inst, "astryx-pulse.service": "[Unit]\n"},
                "astryx-growbot.service", "astryx-growbot.service", "astryx-senses.service", "astryx-pulse.service")
want("RED CONTROL (a3 F1): a REMOTE body's growbot is NOT in the list the setup path tells the owner to enable",
     "astryx-growbot.service" not in L, str(L))
want("…an [Install] unit is, and a unit without [Install] (timer-driven) isn't", L == ["astryx-senses.service"], str(L))
L2 = enable_list({"astryx-growbot.service": inst}, "", "astryx-growbot.service")
want("…and a LOCAL body's growbot IS (nothing declared off)", L2 == ["astryx-growbot.service"], str(L2))
want("both call sites use the one helper (the setup print and doctor's remediation)",
     src.count("inst=$(_enable_list units") == 1 and src.count('inst=$(_enable_list "$GEN"') == 1)
print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
