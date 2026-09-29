"""Authored mutants for nucleus/spawn.sh's goal-4227 wiring (the registry door + the tool nudge),
run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_spawn_wiring.py

Each is a plausible way the wiring breaks while the file still looks right: the door dropped,
a JSON comma that only breaks when a grant is spliced in, the nudge moved into usage.py's group,
or the nudge given usage.py's longer timeout. The Q mutants each remove ONE --render guard: a
render that writes the DB, starts tmux, refuses a live agent, writes the REAL home, loosens its
permissions, or can land a token inside the repo. The oracle runs spawn.sh against shims, so
even a guard-less mutant starts nothing real.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "spawn.sh"
ORACLE = REPO / "tests" / "test_spawn_wiring.py"
ENV = "SPAWN_SRC"

MUTANTS = {
    "P1 the door is not wired":
        ('},\n  "tools": { "command": "$ROOT/venv/bin/python", "args": ["$ROOT/mcp/tools/server.py"] }$EXTRA } }',
         '}$EXTRA } }'),
    # A trailing comma that is valid only when nothing follows: invisible until a grant splices
    # in ($EXTRA starts with its own comma).
    "P2 a comma that breaks only with a grant spliced in":
        ('["$ROOT/mcp/tools/server.py"] }$EXTRA } }', '["$ROOT/mcp/tools/server.py"] },$EXTRA } }'),
    # Same group as usage.py: the nudge then shares usage.py's entry, the layout a4 excluded (W1).
    "P3 the nudge shares usage.py's group":
        ('"timeout": 5 } ] },\n      { "hooks": [\n      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/nudge.py"',
         '"timeout": 5 },\n      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/nudge.py"'),
    "P4 the nudge gets usage.py's timeout":
        ('hooks/nudge.py", "timeout": 3 }', 'hooks/nudge.py", "timeout": 5 }'),

    "Q1 render writes the heartbeat trigger row":
        ('[ -z "$RENDER" ] && psql "$DSN" -qc "INSERT INTO triggers (agent, name, schedule, kind)\n',
         'psql "$DSN" -qc "INSERT INTO triggers (agent, name, schedule, kind)\n'),
    "Q2 render stops at 'already resident'":
        ('if [ -z "$RENDER" ] && tmux has-session -t "=$SESS"', 'if tmux has-session -t "=$SESS"'),
    "Q3 render falls through to the body (tmux, claude, boot row)":
        ('if [ -n "$RENDER" ]; then echo "$AGENT rendered into $HOME_D (no side effects)"; exit 0; fi',
         'true'),
    "Q4 render writes the REAL home":
        ('[ -n "$RENDER" ] && HOME_D="$OUT"', 'true'),
    "Q5 render without umask 077":
        ('  umask 077\n', ''),
    "Q6 render into the repo allowed":
        ('    "$(realpath -m "$ROOT")"/*) echo "spawn --render: <outdir> must be outside the repo ($OUT)"; exit 1;;',
         '    /nonexistent-zz/*) exit 1;;'),
    "Q7 render runs the live-body pgrep guard":
        ('if [ -z "$RENDER" ] && ! tmux has-session -t "=ax-$AGENT"', 'if ! tmux has-session -t "=ax-$AGENT"'),
    # Create, THEN check: a refused render still leaves a directory inside the repo.
    "Q8 outdir created before the inside-repo check":
        ('  umask 077\n  OUT="$(realpath -m "$OUT")"', '  umask 077\n  mkdir -p "$OUT"\n  OUT="$(realpath -m "$OUT")"'),
}
