#!/usr/bin/env python3
"""Oracle: the shipped ORG BACKUP trigger and the shims' one source (plan-10224 add-org-parity). DB-free: each arm runs
src/astryx/pulse/shipped_triggers/org_backup.py in a child with subprocess.Popen recorded (nothing is launched).

  B1 in a cog org (a fixture two-org registry; the child's cwd its HOME, found by its .astryx marker, NO ASTRYX_HOME in
     its env): run_backup launches <code>/scripts/backup.sh with cwd the CODE tree and ASTRYX_HOME = that HOME set
     EXPLICITLY in the launched env (an inherited one would be no HOME at all here), logging to HOME/var/runners/
  B2 its staleness alarm (no dump in HOME/backups) names the ORG from its .env FILE ("[fxorg-a]"), never the process
     env's ASTRYX_ORG (set to another org's); restore-verify the same, launching scripts/restore_verify.sh
  B3 a fresh dump in HOME/backups: no alarm (the artifact is the HOME's, recovered); the CHECKOUT's dump never counts
  B4 one org (no registry): the estate is the checkout, ASTRYX_HOME = it
  B5 shims: every shim registers exactly the names NAMES says (trigger_names' reader), org_backup's both and NOT blind
     (a blind file in an org's triggers/ turns every later "absent" into "deferred"); `shims write` writes SHIMS' text
  B6 one source: init.sh writes every shipped shim through `shims write <name> triggers/seed` and has no heredoc of its
     own left; the names it writes are exactly SHIMS' minus org_backup (cog_add_org's own)
Seams: ORG_BACKUP_SRC (a mutant org_backup.py, tests/mutants_org_backup.py), SHIMS_SRC (a mutant shims.py, run by path
and loaded from it; tests/mutants_shims.py). Exit 0 · 1.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("ORG_BACKUP_SRC") or REPO / "src/astryx/pulse/shipped_triggers/org_backup.py")
SHIMS_SRC = Path(os.environ.get("SHIMS_SRC") or REPO / "src/astryx/pulse/shipped_triggers/shims.py")
CODE = SRC.resolve().parents[4]   # the tree the subject sits in (its repo_root): REPO, or the probe's seat for a mutant
sys.path.insert(0, str(REPO / "src"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


CHILD = r"""
import importlib.util, json, subprocess, sys, types
rec = []
class P:
    def __init__(self, cmd, **kw):
        rec.append({"cmd": cmd, "cwd": str(kw.get("cwd")), "home": (kw.get("env") or {}).get("ASTRYX_HOME"),
                    "has_env": "env" in kw, "log": getattr(kw.get("stdout"), "name", None)})
subprocess.Popen = P
spec = importlib.util.spec_from_file_location("org_backup_under_test", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ctx = types.SimpleNamespace(state={})
out = {"backup": m.run_backup(ctx), "verify": m.run_restore_verify(types.SimpleNamespace(state={})), "rec": rec}
print("OUT " + json.dumps(out))
"""


def child(cwd, env):
    r = subprocess.run([sys.executable, "-c", CHILD, str(SRC)], cwd=cwd, capture_output=True, text=True, timeout=60,
                       env={**env, "PYTHONPATH": str(REPO / "src")})
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("OUT ")), None)
    return json.loads(line[4:]) if line else {"err": (r.stdout + r.stderr)[-600:]}


def main():
    t = Path(tempfile.mkdtemp(prefix="orgbackup-")).resolve()
    homes = {}
    for o in ("a", "b"):
        h = t / f"home-{o}"
        (h / "backups").mkdir(parents=True)
        (h / ".astryx").write_text("astryx home\n")
        (h / ".env").write_text(f"ASTRYX_ORG=fxorg-{o}\nASTRYX_DSN=postgresql://nobody@127.0.0.1:1/fxorg_{o}\n")
        homes[o] = h
    reg = t / "cog.json"
    reg.write_text(json.dumps({"orgs": {f"fx{o}": {"home": str(h), "db": f"fxorg_{o}"} for o, h in homes.items()}}))
    base = {k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_")}
    cog = {**base, "ASTRYX_COG_REGISTRY": str(reg), "ASTRYX_ORG": "primary.example"}   # another org's name, by env

    print("B1 A COG ORG: THE CODE TREE RUNS, THE HOME IS NAMED EXPLICITLY")
    o = child(homes["a"], cog)
    rec = o.get("rec", [])
    b = next((x for x in rec if x["cmd"][-1].endswith("backup.sh")), None)
    check("run_backup launches <code>/scripts/backup.sh", b is not None
          and b["cmd"] == ["bash", str(CODE / "scripts" / "backup.sh")], str(o.get("err") or rec))
    check("...with cwd the CODE tree (backup.sh takes ROOT=$PWD)", b is not None and b["cwd"] == str(CODE), str(b))
    check("...and ASTRYX_HOME = the org's HOME set in the launched env (none in the child's own)",
          b is not None and b["has_env"] and b["home"] == str(homes["a"]), str(b))
    check("...logging into the HOME's var/runners/", b is not None and b["log"] == str(homes["a"] / "var/runners/backup.log"),
          str(b))

    print("\nB2 THE ALARM NAMES THE ORG FROM ITS .env FILE")
    check("no dump: the backup alarm names [fxorg-a] (the process env says primary.example)",
          (o.get("backup") or "").startswith("[fxorg-a] org backup is STALE") and "primary.example" not in o["backup"],
          str(o.get("backup")))
    v = next((x for x in rec if x["cmd"][-1].endswith("restore_verify.sh")), None)
    check("run_restore_verify launches scripts/restore_verify.sh, the same HOME, and its alarm names [fxorg-a]",
          v is not None and v["cmd"] == ["bash", str(CODE / "scripts" / "restore_verify.sh")]
          and v["home"] == str(homes["a"]) and (o.get("verify") or "").startswith("[fxorg-a] restore-verify is STALE"),
          f"{v} {o.get('verify')}")

    print("\nB3 THE ARTIFACT IS THE HOME'S")
    (homes["a"] / "backups" / "astryx-fx.dump").write_text("PGDMP")
    o3 = child(homes["a"], cog)
    check("a fresh dump in HOME/backups: no backup alarm", o3.get("backup") is None, str(o3))
    (homes["a"] / "backups" / "astryx-fx.dump").unlink()
    o4 = child(homes["b"], cog)
    check("org b, no dump of ITS own: its alarm names [fxorg-b] (a's HOME is not its)",
          (o4.get("backup") or "").startswith("[fxorg-b]"), str(o4))

    print("\nB4 ONE ORG (NO REGISTRY): THE CHECKOUT IS THE ESTATE")
    one = {**base, "ASTRYX_COG_REGISTRY": str(t / "none" / "cog.json")}
    o5 = child(t, one)
    b5 = next((x for x in o5.get("rec", []) if x["cmd"][-1].endswith("backup.sh")), None)
    check("ASTRYX_HOME is the checkout, cwd the checkout", b5 is not None and b5["home"] == str(CODE)
          and b5["cwd"] == str(CODE), str(o5.get("err") or b5))

    print("\nB5 SHIMS: THE NAMES THEY REGISTER, NONE OF org_backup's BLIND")
    import importlib.util
    from astryx.core import trigger_names as tn
    spec = importlib.util.spec_from_file_location("shims_under_test", SHIMS_SRC)
    shims = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shims)
    sd = t / "shims"
    sd.mkdir()
    for s in shims.SHIMS:
        r = subprocess.run([sys.executable, str(SHIMS_SRC), "write", s, str(sd)], capture_output=True, text=True,
                           env={**base, "ASTRYX_COG_REGISTRY": str(t / "none" / "cog.json")})
        p = sd / f"{s}.py"
        check(f"`shims write {s}` writes SHIMS' text", r.returncode == 0 and p.is_file()
              and p.read_text() == shims.SHIMS[s], r.stderr[-200:])
        got = tn.names(p, REPO) if p.is_file() else None
        check(f"{s} registers exactly {list(shims.NAMES[s])}", got is not None
              and got.names == set(shims.NAMES[s]), str(got and sorted(got.names)))
    ob = tn.names(sd / "org_backup.py", REPO)
    check("org_backup's shim is NOT blind", ob.blind == [], str(ob.blind))
    want = {"context_compact": {"context_compact"}, "pr_review": {"pr_review"}, "agent_heal": {"agent_heal"},
            "phone_resume_sweep": {"phone_resume_sweep"}, "windows_idle_stop": {"windows_idle_stop"},
            "upstream_prs": {"upstream_prs"}, "org_backup": {"run_backup", "run_restore_verify"}}
    check("each shim registers ITS trigger's names (re-derived here, never read back from NAMES)",
          set(shims.SHIMS) == set(want) and all(tn.names(sd / f"{s}.py", REPO).names == w for s, w in want.items()),
          str({s: sorted(tn.names(sd / f"{s}.py", REPO).names) for s in want if (sd / f"{s}.py").is_file()}))

    print("\nB6 ONE SOURCE: init.sh WRITES EVERY SHIM THROUGH shims.py")
    init = (REPO / "init.sh").read_text()
    written = set(re.findall(r"astryx\.pulse\.shipped_triggers\.shims write (\w+) triggers/seed", init))
    check("init.sh writes exactly the seven shims, each through `shims write` (org_backup: seed #61526)",
          written == {"context_compact", "pr_review", "phone_resume_sweep", "windows_idle_stop", "agent_heal",
                      "upstream_prs", "org_backup"}, str(sorted(written)))
    check("...and no heredoc of its own writes a triggers/seed shim",
          not re.search(r"cat > triggers/seed/\w+\.py", init), "a heredoc is left")
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else "ALL PASS: org backup + shims")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
