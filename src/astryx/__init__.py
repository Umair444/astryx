"""astryx — the tiny library agents import to author triggers.

    from astryx import trigger

    @trigger("*/15 * * * *", note="what this watches")
    def my_condition(ctx):
        ...
        return None            # silence, or
        return "message body"  # fire: arrives on your channel as a wire message

Files live in triggers/<agent>/*.py. The pulse discovers decorated functions,
registers them in the triggers table, and evaluates each on its schedule in an
isolated subprocess. ctx gives a check its world:

    ctx.sql(query, params=())   rows from the org's postgres, list of dicts
    ctx.http(url)               a page or API body, 15s timeout
    ctx.state                   dict persisted between runs: baselines, seen
                                ids, yesterday's numbers. Mutate it freely.

The pulse is AT-LEAST-ONCE: a firing's side effect (a send, a row it writes) can
run more than once if the run is interrupted between the effect and the ctx.state
write-back. ctx.state is safe for throttling and baselines; for a side effect that
must not duplicate, dedup on durable state — query the effect itself, or a column —
not ctx.state.

The repo-root shim (astryx.py) executes this file INTO its own namespace, so it stays
import-light and uses no relative imports: the pulse imports it every minute, and both
import paths must yield the one `_registry`.
"""

__version__ = "0.1.0"

_registry: list[dict] = []


def trigger(schedule: str, note: str = ""):
    def wrap(fn):
        _registry.append({"name": fn.__name__, "schedule": schedule,
                          "note": note, "fn": fn})
        return fn
    return wrap
