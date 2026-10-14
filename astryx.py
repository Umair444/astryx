"""Shim: the astryx package lives in src/astryx/ (plan-10224 S1). `from astryx import trigger` as before.

The pulse discovers triggers with cwd = the org root, so `import astryx` finds THIS file before any
installed package. It can't import the package (the names collide), so it BECOMES it: it runs
src/astryx/__init__.py in its own namespace and sets `__path__`, so `astryx.trigger`, `astryx._registry`
and `astryx.paths` are the package's, and a process holds ONE `astryx` module and ONE `_registry`
whichever path won. Without src/astryx beside it (a test tree that copied only this file), it binds to an
astryx package found on sys.path instead. Oracle: tests/test_astryx_registry.py.
"""
import os as _os
import sys as _sys


def _locate():
    here = _os.path.dirname(_os.path.abspath(__file__))
    beside = _os.path.join(here, "src", "astryx")
    if _os.path.isfile(_os.path.join(beside, "__init__.py")):
        return beside
    for entry in _sys.path:
        base = _os.path.abspath(entry or _os.getcwd())
        if base != here and _os.path.isfile(_os.path.join(base, "astryx", "__init__.py")):
            return _os.path.join(base, "astryx")
    raise ImportError("astryx: no src/astryx/ beside astryx.py and no astryx package on sys.path")


__path__ = [_locate()]
__package__ = __name__
_init = _os.path.join(__path__[0], "__init__.py")
with open(_init, encoding="utf-8") as _f:
    exec(compile(_f.read(), _init, "exec"))
del _f, _init, _locate, _os, _sys

if __name__ == "__main__":         # `python -m astryx` from the org root runs THIS file, not __main__.py
    from astryx.cli import main
    raise SystemExit(main())
