"""astryx — the tiny library agents import to author triggers (the full docs: src/astryx/__init__.py).

    from astryx import trigger

    @trigger("*/15 * * * *", note="what this watches")
    def my_condition(ctx):
        return None            # silence, or a message body to fire

The pulse discovers triggers with cwd = the org root, so `import astryx` finds THIS file before any installed
package, and a process holds ONE `astryx` module and ONE `_registry` whichever path won. This file is
SELF-SUFFICIENT for that: `_registry` and `trigger` below are a copy of src/astryx/__init__.py's (pinned identical
by tests/test_astryx_registry.py), with no exec and no import of src/, so a checkout caught mid-write (this file
written, src/astryx/ not yet) still loads every trigger, and trigger_names' static reader sees plain defs.
`__path__` points at src/astryx/ when it's there, so `astryx.paths`, `astryx.config` and `astryx.cli` resolve as
the package's submodules; `__version__` is read from it on first use.
"""
import os as _os


def _src():
    d = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "src", "astryx")
    return [d] if _os.path.isfile(_os.path.join(d, "__init__.py")) else []


__path__ = _src()


def __getattr__(name):
    if name == "__version__":
        from astryx._version import __version__ as v
        return v
    raise AttributeError(f"module 'astryx' has no attribute {name!r}")


_registry: list[dict] = []


def trigger(schedule: str, note: str = ""):
    def wrap(fn):
        _registry.append({"name": fn.__name__, "schedule": schedule,
                          "note": note, "fn": fn})
        return fn
    return wrap


if __name__ == "__main__":         # `python -m astryx` from the org root runs THIS file, not __main__.py
    from astryx.cli import main
    raise SystemExit(main())
