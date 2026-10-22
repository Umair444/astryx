"""Authored mutants for the owner-surface census's G2 (tests/test_owner_surface.py), applied to observatory/api/chat.py:
a new messages writer reached by a CALL to a helper, never by SQL text in the file (a1 #62307 W-H), in each spelling.

    venv/bin/python devtools/mutation_probe.py tests/mutants_owner_surface_chat.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "observatory" / "api" / "chat.py"
ORACLE = REPO / "tests" / "test_owner_surface.py"
ENV = "SURFACE_CHAT_SRC"

ANCHOR = "# ------------------------------------------------------------------------------------------------------ dictate"
MUTANTS = {
    "W-H a /chat route writes the wire through common.wire_insert (a1 #62307)":
        (ANCHOR, "from bridges.common import wire_insert  # noqa: E402\n\n\n@router.post('/api/chat/sneak')\n"
                 "async def sneak(request: Request):\n    await wire_insert(_pool(request), 'owner', 'seed', 'x')\n\n\n" + ANCHOR),
    "W-A the same, aliased (from bridges.common import wire_insert as w)":
        (ANCHOR, "from bridges.common import wire_insert as w  # noqa: E402\n\n\n@router.post('/api/chat/sneak')\n"
                 "async def sneak(request: Request):\n    await w(_pool(request), 'owner', 'seed', 'x')\n\n\n" + ANCHOR),
    "W-M the same, through the module (import bridges.common as bc; bc.wire_insert)":
        (ANCHOR, "import bridges.common as bc  # noqa: E402\n\n\n@router.post('/api/chat/sneak')\n"
                 "async def sneak(request: Request):\n    await bc.wire_insert(_pool(request), 'owner', 'seed', 'x')\n\n\n" + ANCHOR),
    "X2 a REBINDING: `_W = wire_insert` at module level, then `await _W(...)` (a1 #62309)":
        (ANCHOR, "from bridges.common import wire_insert  # noqa: E402\n_W = wire_insert\n\n\n@router.post('/api/chat/sneak')\n"
                 "async def sneak(request: Request):\n    await _W(_pool(request), 'owner', 'seed', 'x')\n\n\n" + ANCHOR),
    "X3 a functools.partial(wire_insert, pool) spelling (a1 #62309)":
        (ANCHOR, "import functools  # noqa: E402\nfrom bridges.common import wire_insert  # noqa: E402\n\n\n"
                 "@router.post('/api/chat/sneak')\nasync def sneak(request: Request):\n"
                 "    send = functools.partial(wire_insert, _pool(request))\n    await send('owner', 'seed', 'x')\n\n\n" + ANCHOR),
    "W-U a repo-internal import that doesn't resolve is UNKNOWN, never a pass":
        (ANCHOR, "from bridges.no_such_module import helper  # noqa: E402\n\n\nasync def sneak():\n    await helper()\n\n\n" + ANCHOR),
}
