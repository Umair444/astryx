"""Build hooks for the astryx wheel and sdist (plan-10224 S1/S3).

Metadata: dependencies and extras come from nucleus/deps.conf, the repo's one dependency authority
(core + cli -> dependencies; media, discord, dev -> extras), so pyproject never carries a second list.

Files: the org's runtime tree (what init.sh needs) ships from git-TRACKED files only, filtered by the
allowlist in src/astryx/_data/manifest.py. In the sdist it sits at its own paths; in the wheel under
astryx/_data/tree/. A build from a source tree that is neither a git checkout nor an unpacked sdist is
refused: walking a working directory would sweep up gitignored files (.env, local.md, homes/).
"""
import os
import runpy
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from hatchling.metadata.plugin.interface import MetadataHookInterface

NOT_ON_PYPI = {"micropython-onchip"}       # deps.conf's dev marker for an on-chip module (never installable)
CORE_GROUPS = ("core", "cli")
EXTRAS = ("media", "discord", "dev")


def deps_groups(root: Path) -> dict:
    groups: dict = {}
    for line in (root / "nucleus" / "deps.conf").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[1] not in NOT_ON_PYPI:
            groups.setdefault(parts[0], []).append(parts[1])
    return groups


class DepsMetadata(MetadataHookInterface):
    PLUGIN_NAME = "custom"

    def update(self, metadata):
        g = deps_groups(Path(self.root))
        metadata["dependencies"] = [s for grp in CORE_GROUPS for s in g.get(grp, [])]
        metadata["optional-dependencies"] = {e: g.get(e, []) for e in EXTRAS}


def tree_files(root: Path) -> list[str]:
    man = runpy.run_path(str(root / "src" / "astryx" / "_data" / "manifest.py"))
    if (root / ".git").exists():
        # The COMMITTED tree (HEAD), not the index: ls-files would ship whatever happens to be staged. A tracked
        # file modified or staged on disk would make the shipped bytes differ from HEAD, so a dirty tree is refused.
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
        if dirty:
            raise RuntimeError("astryx: refusing to build from a dirty tree (commit or discard these first):\n"
                               + dirty)
        out = subprocess.run(["git", "-C", str(root), "ls-tree", "-r", "-z", "--name-only", "HEAD"],
                             capture_output=True, check=True).stdout
        rels = [r for r in out.decode().split("\0") if r]
    elif (root / "PKG-INFO").is_file():                       # an unpacked sdist: already the allowlisted tree
        rels = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
    else:
        raise RuntimeError("astryx: build from a git checkout or an sdist; a bare working tree may hold private files")
    return sorted(r for r in rels if man["wanted"](r)
                  and (root / r).is_file() and not (root / r).is_symlink())


class TreeHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        if version == "editable":            # `pip install -e .`: the checkout IS the tree; copy nothing
            return
        root = Path(self.root)
        taken = set(build_data.get("force_include", {}).values())
        wheel = self.target_name == "wheel"
        for rel in tree_files(root):
            # the wheel carries src/astryx as THE package; a second force-included copy would knock the package's own
            # files out of the selection (hatch drops force-include sources from it). tree.materialize copies the
            # installed package into HOME/src/astryx instead.
            if wheel and rel.startswith("src/astryx/"):
                continue
            dest = f"astryx/_data/tree/{rel}" if wheel else rel
            if dest in taken:
                continue
            build_data["force_include"][os.fspath(root / rel)] = dest
