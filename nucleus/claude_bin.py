"""Where the `claude` CLI is, for code that shells out to it from a SERVICE.

A systemd unit runs with systemd's bare PATH (/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin), and
the CLI lives in the user's ~/.local/bin (a mise wrapper). A bare "claude" then raises FileNotFoundError
— vega in the observatory went dark that way after a plain `systemctl restart` (owner, 2026-10-09:
"I lost my train of thought"). Resolve it once, explicitly: $CLAUDE_BIN, then PATH, then ~/.local/bin.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def claude_bin() -> str:
    explicit = os.environ.get("CLAUDE_BIN")
    if explicit:
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "claude"
    return str(local) if local.is_file() else "claude"
