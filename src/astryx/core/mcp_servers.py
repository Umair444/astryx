#!/usr/bin/env python3
"""astryx · mcp_servers — THE one list of the org's tool servers, and who gets each (owner 11-17: "tools tab in obs is
not inheritting it … fix it").

mcp/registry.json names every MCP server an agent can hold, and each entry says who gets it:
  who: "every"     every resident (the wire, the registry door, hands, influence, channels)
  who: "grant"     a resident whose charter's `Grants:` line names it (or one of its `grants` aliases: mail ← gmail)
  who: "opt-in"    every resident, once the org's .env sets `optin` to 1 (phone ← ANDROID_ENABLED)
Its command, args and env may name the spawn's own values: $ROOT $AGENT $ORGH $NODE $NPX $HOME_D $UID. A relative path
is the checkout's. spawn.sh writes each agent's .mcp.json from THIS (render), the observatory's Tools tab lists THIS
(with who), and mcp/scan.py and compose launch a server through launch(): no second list anywhere.

    mcp_servers.py render --root DIR --agent A --home DIR --orgh DIR --node PATH --grants "a b" [--optin K=V]
        prints {"mcpServers": {...}} for that agent; an unknown grant is a warning on stderr
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REGISTRY = REPO / "mcp" / "registry.json"
VARS = ("$ROOT", "$AGENT", "$ORGH", "$NODE", "$NPX", "$HOME_D", "$UID")


def load() -> dict:
    return json.loads(REGISTRY.read_text())


def _expand(v: str, ctx: dict) -> str:
    for k in VARS:
        v = v.replace(k, str(ctx.get(k[1:], "")))
    return v


def _path(v: str, ctx: dict) -> str:
    """A command or an argument: the spawn's values filled in; a relative file path is the checkout's."""
    out = _expand(v, ctx)
    if v.startswith(("$", "/", "-", "@")) or "/" not in v:
        return out
    return str(Path(ctx.get("ROOT") or REPO) / out)


def launch(name: str, entry: dict, ctx: dict | None = None) -> dict:
    """The {command, args, env?} that starts one server, for .mcp.json, mcp/scan.py or compose."""
    ctx = {"ROOT": REPO, "UID": os.getuid(), "AGENT": "scan", "ORGH": REPO, "HOME_D": REPO,
           "NODE": "node", "NPX": "npx", **(ctx or {})}
    out = {"command": _path(entry["command"], ctx), "args": [_path(a, ctx) for a in entry.get("args", [])]}
    if entry.get("env"):
        out["env"] = {k: _expand(v, ctx) for k, v in entry["env"].items()}
    return out


def for_agent(grants: list[str], ctx: dict, optins: dict[str, str]) -> tuple[dict, list[str]]:
    """(the agent's mcpServers, the grants no server answers to). Every-servers first, then opted-in ones, then each
    granted server in its charter's order."""
    reg = load()
    out = {n: launch(n, e, ctx) for n, e in reg.items() if e.get("who") == "every"}
    out |= {n: launch(n, e, ctx) for n, e in reg.items()
            if e.get("who") == "opt-in" and optins.get(e.get("optin", "")) == "1"}
    unknown = []
    for g in grants:
        hit = [n for n, e in reg.items() if e.get("who") == "grant" and g in (e.get("grants") or [n])]
        if not hit:
            unknown.append(g)
        for n in hit:
            out.setdefault(n, launch(n, reg[n], ctx))
    return out, unknown


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="astryx.core.mcp_servers")
    ap.add_argument("cmd", choices=["render"])
    ap.add_argument("--root", default=str(REPO), help="the checkout the servers run from (spawn's $ROOT)")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--orgh", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--grants", default="")
    ap.add_argument("--optin", action="append", default=[], help="KEY=VALUE from the org's .env")
    a = ap.parse_args()
    ctx = {"ROOT": a.root, "AGENT": a.agent, "ORGH": a.orgh, "HOME_D": a.home, "NODE": a.node,
           "NPX": str(Path(a.node).parent / "npx"), "UID": os.getuid()}
    optins = dict(kv.split("=", 1) for kv in a.optin if "=" in kv)
    servers, unknown = for_agent(a.grants.replace(",", " ").split(), ctx, optins)
    for g in unknown:
        print(f"warning: unknown grant '{g}'", file=sys.stderr)
    print(json.dumps({"mcpServers": servers}, indent=2))
