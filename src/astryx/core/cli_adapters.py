"""The ONE reader of src/astryx/data/cli_adapters.json (plan-11859 U5, D10): load, judge, and build a launch line.

A row that can't launch an agent ON THE WIRE is refused at load, not discovered in a pane: a launcher must carry its
channel flag with the channel server (without them the wire's doorbell is dropped silently: the MCP tools still
work, so the agent looks fine and hears nothing), the {mcp} slot, and its permission flag taking {perm}. A malformed
table RAISES (AdapterError), so spawn refuses rather than falling back to a line nobody declared.

launch() returns the argv; line() its shell form, every element quoted (shlex.join). The pane's shell parses what
spawn types, so a charter's Model: value with a space, `;` or `$(…)` is ONE argument, never split or run (a2 #62560).
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "cli_adapters.json"
ENV = "ASTRYX_CLI_ADAPTERS"          # the oracle's seam: another table (a fixture's), never set in a unit
SLOTS = ("{cli}", "{resume}", "{model}", "{perm}", "{mcp}")


class AdapterError(RuntimeError):
    """The table is malformed or a row can't launch on the wire: refuse, never guess."""


def path() -> Path:
    return Path(os.environ[ENV]) if os.environ.get(ENV) else PATH


def load(p: Path | None = None) -> dict:
    """{cli: row}, every row judged."""
    p = p or path()
    try:
        rows = json.loads(Path(p).read_text())["adapters"]
        assert isinstance(rows, dict) and rows
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise AdapterError(f"cli adapters {p}: unreadable or no `adapters`") from None
    for cli, r in rows.items():
        cr = r.get("credentials") if isinstance(r, dict) else None
        if not (isinstance(cr, dict) and set(cr) == {"subscription", "metered"}
                and all(isinstance(v, list) and all(isinstance(k, str) and k for k in v) for v in cr.values())):
            raise AdapterError(f"cli adapters: {cli} needs credentials {{subscription: [...], metered: [...]}}")
        if r.get("launcher") is not True:
            if not r.get("why"):
                raise AdapterError(f"cli adapters: {cli} has no launcher and no `why`: a refusal must say why")
            continue
        lt = r.get("launch")
        if not (isinstance(lt, list) and lt and all(isinstance(t, str) for t in lt)):
            raise AdapterError(f"cli adapters: {cli}'s launch must be a list of strings")
        if lt[0] != "{cli}" or "{mcp}" not in lt or "{resume}" not in lt or "{model}" not in lt:
            raise AdapterError(f"cli adapters: {cli}'s launch must start at {{cli}} and carry {{resume}}, {{model}}, "
                               "{mcp}")
        for flag, value, what in ((r.get("channel_flag"), r.get("channel_server"), "the wire's channel"),
                                  (r.get("permission_flag"), "{perm}", "its permission mode")):
            if not (flag and value and any(lt[i] == flag and lt[i + 1] == value for i in range(len(lt) - 1))):
                raise AdapterError(f"cli adapters: {cli}'s launch lacks {what} ({flag} {value}): an agent launched "
                                   "without it is deaf or runs the wrong mode")
    return rows


def credentials(rows: dict | None = None) -> dict:
    """{cli: {"subscription": (keys...), "metered": (keys...)}}: runtime_env.CLIS."""
    rows = load() if rows is None else rows
    return {c: {k: tuple(v) for k, v in r["credentials"].items()} for c, r in rows.items()}


def launchers(rows: dict | None = None) -> set:
    rows = load() if rows is None else rows
    return {c for c, r in rows.items() if r.get("launcher") is True}


def launch(cli: str, *, binary: str, model: str, perm: str, mcp: str, resume: str | None = None,
           rows: dict | None = None) -> list[str]:
    """The argv that launches an agent on `cli`. Raises AdapterError for a CLI with no launcher (its why)."""
    rows = load() if rows is None else rows
    r = rows.get(cli)
    if r is None:
        raise AdapterError(f"{cli} is no CLI the adapter table knows")
    if r.get("launcher") is not True:
        raise AdapterError(r["why"])
    fill = {"{cli}": [binary], "{resume}": ["--resume", resume] if resume else [], "{model}": [model],
            "{perm}": [perm], "{mcp}": [mcp]}
    out = []
    for t in r["launch"]:
        out += fill.get(t, [t])
    return out


def line(argv: list[str]) -> str:
    return shlex.join(argv)
