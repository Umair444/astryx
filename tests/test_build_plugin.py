"""The plugin repo is GENERATED from this one (devtools/build_plugin.py); its copies must match the repo (drift).

The plugin ships copies: channel/*.mjs, the channel's package.json and lockfile, LICENSE, the seed's charter and
onboarding runbook. A copy that drifts from the repo is a plugin running yesterday's wire. So:
  * a fresh build matches the repo file for file (check() finds nothing), and every copy is byte-equal to its source;
  * check() is a real detector: a changed copy, a missing file and an extra file each read as a difference;
  * the build's own invariants: marketplace.json names the plugin with source "./"; package.json and the lockfile's
    root agree (Claude Code skips the lockfile install otherwise) and list every package server.mjs imports;
    the manifest's server runs channel/server.mjs from ${CLAUDE_PLUGIN_ROOT} with the plugin-mode env; nothing a
    directory submission blocks on (no symlinks, no .DS_Store, no CLAUDE.md, a README of 40+ words);
  * dist/astryx-plugin, when it exists, matches the repo (a stale build is drift too).
Pure stdlib. Run: venv/bin/python tests/test_build_plugin.py
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "nucleus"))
import build_plugin as bp  # noqa: E402

fails = 0


def arm(name: str, ok: bool, detail: str = "") -> None:
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[-400:]}]" if detail and not ok else ""))
    fails += not ok


tmp = Path(tempfile.mkdtemp(prefix="build-plugin-"))
try:
    out = tmp / "astryx-plugin"
    written = bp.build(out)
    arm("build: a fresh build matches the repo (check finds nothing)", bp.check(out) == [], "\n".join(bp.check(out)))

    copies = {f"channel/{p.name}": p for p in (REPO / "channel").glob("*.mjs")}
    copies.update({"package.json": REPO / "channel" / "package.json",
                   "package-lock.json": REPO / "channel" / "package-lock.json",
                   "LICENSE": REPO / "LICENSE", "skills/onboard/onboard.md": REPO / "agents" / "seed" / "onboard.md"})
    bad = [k for k, src in copies.items() if (out / k).read_bytes() != src.read_bytes()]
    arm("copies: every channel module, package file, LICENSE and onboard.md is byte-equal to the repo", not bad,
        ", ".join(bad))
    arm("copies: every channel/*.mjs is shipped (server.mjs imports its siblings)",
        set(copies) <= set(written) and "channel/server.mjs" in written and "channel/home.mjs" in written)
    seed = (out / "agents" / "seed.md").read_text()
    arm("seed subagent: carries the tracked seed charter and onboarding runbook verbatim",
        (REPO / "agents/seed/seed.md").read_text().strip() in seed
        and (REPO / "agents/seed/onboard.md").read_text().strip() in seed
        and seed.startswith("---\nname: seed\ndescription: "))
    plugin_src = {p.relative_to(REPO / "plugin").as_posix() for p in (REPO / "plugin").rglob("*")
                  if p.is_file() and "templates" not in p.parts and "__pycache__" not in p.parts}
    arm("plugin/: every source file is shipped as is (templates/ excepted)",
        all((out / r).read_bytes() == (REPO / "plugin" / r).read_bytes() for r in plugin_src)
        and not (out / "templates").exists())

    # the detector detects
    (out / "channel" / "server.mjs").write_text("// drifted\n")
    (out / "README.md").unlink()
    (out / "stray.txt").write_text("x")
    probs = bp.check(out)
    arm("check: a changed copy, a missing file and an extra file each read as a difference",
        "changed channel/server.mjs" in probs and "missing README.md" in probs and "extra stray.txt" in probs,
        "\n".join(probs))
    bp.build(out)
    arm("build: a rebuild over a drifted dir restores it", bp.check(out) == [])
    (out / ".git").mkdir()
    (out / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    bp.build(out)
    arm("build: a rebuild keeps the plugin repo's .git", (out / ".git" / "HEAD").is_file() and bp.check(out) == [])
    shutil.rmtree(out / ".git")

    # the build's own invariants
    mk = json.loads((out / ".claude-plugin" / "marketplace.json").read_text())
    arm("marketplace.json: named astryx, owner set, one plugin 'astryx' at source ./",
        mk.get("name") == "astryx" and mk.get("owner", {}).get("name")
        and [(p["name"], p["source"]) for p in mk.get("plugins", [])] == [("astryx", "./")], json.dumps(mk))
    pkg = json.loads((out / "package.json").read_text())
    lock = json.loads((out / "package-lock.json").read_text())
    arm("package.json and the lockfile's root list the same dependencies",
        pkg.get("dependencies") == lock["packages"][""].get("dependencies"),
        f"{pkg.get('dependencies')} vs {lock['packages'][''].get('dependencies')}")
    imported = set()
    for p in (out / "channel").glob("*.mjs"):
        for m in re.finditer(r"""(?:from|import\()\s*['"]([^'"./][^'"]*)['"]""", p.read_text()):
            spec = m.group(1)
            if not spec.startswith("node:"):
                imported.add("/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0])
    arm("package.json lists every package the channel imports (zod included)",
        imported and imported <= set(pkg.get("dependencies", {})), f"{sorted(imported)} vs {pkg.get('dependencies')}")
    arm("lockfile: v2/v3 and every package pinned to an exact registry version over https",
        lock.get("lockfileVersion") in (2, 3)
        and all(re.fullmatch(r"\d+\.\d+\.\d+", v.get("version", "")) and v.get("resolved", "").startswith("https://")
                for k, v in lock["packages"].items() if k))
    man = json.loads((out / ".claude-plugin" / "plugin.json").read_text())
    srv = man["mcpServers"]["astryx"]
    arm("manifest: the astryx server runs ${CLAUDE_PLUGIN_ROOT}/channel/server.mjs in plugin mode",
        srv["args"] == ["${CLAUDE_PLUGIN_ROOT}/channel/server.mjs"]
        and srv["env"].get("ASTRYX_ONE_BODY") == "1" and "ASTRYX_JOIN_DIR" in srv["env"]
        and srv["env"].get("ASTRYX_HOME") == "${user_config.astryx_home}"
        and man["userConfig"]["dsn"].get("sensitive") is True
        and man["channels"] == [{"server": "astryx", "displayName": "ASTRYX wire"}], json.dumps(srv))
    lic = (REPO / "LICENSE").read_text()
    arm("manifest: author is the LICENSE's name, repo and homepage are the project's",
        man["author"]["name"] in lic and man["homepage"] == "https://github.com/Umair444/astryx"
        and man["license"] == "MIT")
    links = [p for p in out.rglob("*") if p.is_symlink()]
    junk = [p for p in out.rglob("*") if p.name in (".DS_Store", "Thumbs.db", "desktop.ini", "CLAUDE.md")]
    arm("directory rules: no symlinks, no OS junk, no CLAUDE.md", not links and not junk, f"{links} {junk}")
    words = len(re.sub(r"```.*?```", "", (out / "README.md").read_text(), flags=re.S).split())
    arm("directory rules: README of at least 40 words outside code blocks", words >= 40, str(words))
    big = [p for p in out.rglob("*") if p.is_file() and p.stat().st_size > 256 * 1024
           and p.name != "package-lock.json"]
    arm("directory rules: no file over 256 KiB (the lockfile aside), and well under 512 files",
        not big and len(written) < 512, f"{big} {len(written)}")
    disclose = (out / "README.md").read_text()
    arm("README discloses what runs: postgres, the checkout's python, the dev-channels flag, bypassPermissions",
        all(s in disclose for s in ("postgres", "venv/bin/python", "--dangerously-load-development-channels",
                                    "bypassPermissions", "package-lock.json")))
    secretish = [p for p in out.rglob("*") if p.is_file() and p.name != "package-lock.json"
                 and re.search(rb"(?i)(postgres(ql)?://[^\s@/]+:[^\s@/]+@|sk-ant-|ghp_[A-Za-z0-9]{20})", p.read_bytes())]
    arm("no secrets: no credentialed DSN or token in any shipped file", not secretish, str(secretish))

    # the real dist dir, if one was built
    dist = bp.DEFAULT_OUT
    if dist.exists():
        probs = bp.check(dist)
        arm(f"dist: {dist.relative_to(REPO)} matches the repo (rebuild: python devtools/build_plugin.py)",
            probs == [], "\n".join(probs))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PASS" if not fails else f"FAIL: {fails} arm(s)")
sys.exit(1 if fails else 0)
