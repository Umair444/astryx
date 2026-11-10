"""Authored mutants for src/astryx/pulse/watch.py (plan-12214). venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_watch.py"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "pulse" / "watch.py"
ORACLE = REPO / "tests" / "test_trigger_watch.py"
ENV = "WATCH_SRC"

MUTANTS = {
    "a swallowed wake records its rows as told (F1h)":
        ('accepted=accepted, swallowed=swallowed)', 'accepted=accepted, swallowed=accepted)'),
    "a departure isn't recorded":
        ('seen = {k: v for k, v in state.get("seen", {}).items() if k in cur}', 'seen = dict(state.get("seen", {}))'),
    "a wake's room isn't split: a busy feed starves a due row":
        ('new_room = BODY if not due else (BODY // 2 if new else 0)', 'new_room = BODY'),
    "an unshown row is consumed":
        ('{k: stamp for k, _ in shown_new + still}', '{k: stamp for k in cur}'),
    "due rows go in query order, not least recently fired":
        ('sorted(((k, seen[k]) for k in cur if k in seen), key=lambda x: x[1])', '((k, seen[k]) for k in cur if k in seen)'),
    "staggered rows don't share a wake":
        ('elif age >= renag / 2:', 'elif False:'),
    "a renag fires on every evaluation":
        ('if age >= renag:', 'if age >= timedelta(0):'),
    "storm reads accepted memory, not the previous evaluation":
        ('prev = set(state.get("prev", []))', 'prev = set(state.get("seen", {}))'),
    "storm never fires":
        ('if churn >= STORM_K:', 'if False:'),
    "an after's first-true is lost when no wake goes":
        ('base = {**state, "since": since}', 'base = {**state}'),
    "after is ignored":
        ('if after is not None and now - _at(since) < after:', 'if False:'),
    "a false evaluation doesn't reset while":
        ('clear = {k: v for k, v in state.items() if k not in ("since", "last")}', 'clear = dict(state)'),
    "while re-nags every evaluation":
        ('if last is not None and (renag is None or now - last < renag):', 'if False:'),
    "over cap wakes on every evaluation":
        ('if last is not None and now - last < OVER_CAP_RENAG:', 'if False:'),
    "over cap goes silent for good":
        ('if last is not None and now - last < OVER_CAP_RENAG:', 'if last is not None:'),
    "over cap writes over row memory":
        ('accepted={**state, "over_cap": now.isoformat()}, swallowed=base)', 'accepted={"over_cap": now.isoformat()}, swallowed=base)'),
    "a wake can pass say()'s 3000-byte cut":
        ('BODY = 2400 ', 'BODY = 9000 '),
}
