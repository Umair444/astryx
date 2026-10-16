"""The ONE way an oracle stages the real channel/server.mjs outside the repo (ear survival, wake recovery, the step
doorbell). Staging only server.mjs broke all three on 10-11: 0c95e37 made it import ./trigger_name.mjs statically,
and the lone copy crashed at startup ("the probe server never LISTENed"). So the server's sibling modules are staged
by DERIVATION (every channel/*.mjs), with node_modules linked, never a hand list. A new oracle that stages the
server calls this. tests/test_stage_channel_users.py is a SPELLING detector (it catches the 10-11 spellings and checks
the helper has users); the real boundary is behavioural: a server staged without its siblings can't LISTEN, so its own
oracle reads RED or 77 (a2 #46304)."""
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def stage_server(channel_dir: Path, server: Path) -> Path:
    """Copy `server` (the real server.mjs, or a CHANNEL_SERVER_SRC mutant) into `channel_dir`, plus every sibling
    channel/*.mjs and a node_modules link. Returns the staged server.mjs path."""
    channel_dir.mkdir(parents=True, exist_ok=True)
    for mod in (REPO / "channel").glob("*.mjs"):
        if mod.name != "server.mjs":
            shutil.copy2(mod, channel_dir / mod.name)
    shutil.copy2(server, channel_dir / "server.mjs")
    (channel_dir / "node_modules").symlink_to(REPO / "channel" / "node_modules")
    return channel_dir / "server.mjs"
