"""sqlguard driver shim (goal 4243, the RUNTIME half). Loaded as `sitecustomize` via PYTHONPATH, which check.sh
sets ITSELF (the runner-env law). Inert unless ASTRYX_SQLGUARD_DIR is set.

For every statement a real driver executes (psycopg 3 sync/async cursors, asyncpg connections), it appends
one JSON line to $ASTRYX_SQLGUARD_DIR/trace-<pid>-<n>.jsonl:
  t       normalised text (nucleus.sqlguard.normalize, the same function the inventory uses)
  db      database name;   schema  the effective schema (connect options, then any SET search_path seen)
  frames  [relpath, co_qualname, line] for every REPO frame, innermost first (the attribution input)
  ok      succeeded?;  err  exception class on failure;  rows  row/affected count (-1 unknown)
  p       {col: [raw values, capped at 2]} for COMPUTED BOOL columns only: ftable(i)=0 AND OID 16 (#21888)
  rels    base-relation OIDs behind the result (ftable != 0);  stamped  true/false/null (fixture DBs only)
  gate    the check.sh gate label (ASTRYX_SQLGUARD_GATE)

RULES THIS FILE KEEPS:
  * It never runs a statement on the CALLER's connection. The schema comes from connection options plus the
    text of SET search_path / set_config statements it sees. Stamp checks use a SEPARATE connection per
    fixture database, under a recursion guard, so the caller's transaction state is never touched.
  * (P) reads raw values from the libpq result (pgresult.get_value), so the caller's cursor position is
    unchanged.
  * Fail-open on its OWN errors: each one is written as a {"shim_error": class} record and swallowed. The
    judge treats any count > 0 as a NOT SEARCHED run. It must never read as EXECUTED, and never raise into the
    code under test.
  * Catalog caches are keyed (dbname, oid) (M1): OIDs are per database.
This file is the one declared inventory exemption (it cannot observe its own guarded reads).
"""
import os

_DIR = os.environ.get("ASTRYX_SQLGUARD_DIR")

if _DIR:
    import itertools
    import json
    import re
    import sys
    import threading
    import time

    _REPO = os.path.realpath(os.environ.get("ASTRYX_SQLGUARD_ROOT")
                             or os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    _SELF = os.path.realpath(__file__)
    _PKG = os.path.dirname(os.path.dirname(_SELF))   # the sqlguard package THIS shim ships with, not the subject
    _GATE = os.environ.get("ASTRYX_SQLGUARD_GATE", "")
    _FX_PREFIX = "astryx_fx_"
    _local = threading.local()
    _lock = threading.Lock()
    _seq = itertools.count()
    _out = None
    _stamp_cache = {}                        # (dbname, oid) -> bool
    import weakref
    _schema = weakref.WeakKeyDictionary()     # conn -> schema (id() is reused after GC; a weak key isn't)
    _SET_PATH = re.compile(r"^set (?:session |local )?search_path (?:to|=) \"?([a-z0-9_]+)")
    _SET_CFG = re.compile(r"set_config\('search_path', ?'\"?([a-z0-9_]+)")

    def _emit(rec):
        global _out
        try:
            with _lock:
                if _out is None:
                    os.makedirs(_DIR, exist_ok=True)
                    _out = open(os.path.join(_DIR, f"trace-{os.getpid()}-{next(_seq)}-{int(time.time())}.jsonl"),
                                "a", buffering=1)
                _out.write(json.dumps(rec, separators=(",", ":")) + "\n")
        except Exception:
            pass

    def _err(e):
        _emit({"shim_error": type(e).__name__, "gate": _GATE})

    def _frames():
        out, f = [], sys._getframe(2)
        while f is not None and len(out) < 40:
            fn = os.path.realpath(f.f_code.co_filename)
            if fn.startswith(_REPO + os.sep) and fn != _SELF and f"{os.sep}venv{os.sep}" not in fn:
                out.append([os.path.relpath(fn, _REPO), f.f_code.co_qualname, f.f_lineno])
            f = f.f_back
        return out

    _mods = {}

    def _private(name):
        """Load a sqlguard helper by FILE PATH under a private name. Touching sys.path would change the traced
        program's own import resolution, which is a side effect on the subject. It's still ONE normalisation
        (the same file the inventory imports), not a copy."""
        if name not in _mods:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"_sqlguard_{name}", os.path.join(_PKG, f"{name}.py"))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            _mods[name] = m
        return _mods[name]

    def _norm(text):
        return _private("normalize").norm(text)

    def _initial_schema(options):
        m = re.search(r"search_path=\"?([A-Za-z0-9_]+)", (options or "") + " " + os.environ.get("PGOPTIONS", ""))
        return m.group(1).lower() if m else "public"

    def _track(conn_key, options, t):
        if conn_key not in _schema:
            _schema[conn_key] = _initial_schema(options)
        m = _SET_PATH.match(t) or _SET_CFG.search(t)
        if m:
            _schema[conn_key] = m.group(1)
        return _schema[conn_key]

    def _stamped(dbname, oids):
        """True iff EVERY relation carries a valid signature stamp (current schema.sql sha + recomputed sig)."""
        if not dbname.startswith(_FX_PREFIX) or not oids:
            return None
        todo = [o for o in oids if (dbname, o) not in _stamp_cache]
        if todo:
            _local.busy = True
            try:
                stamp_valid = _private("fixture").stamp_valid
                for o in todo:
                    _stamp_cache[(dbname, o)] = stamp_valid(dbname, o)
            finally:
                _local.busy = False
        return all(_stamp_cache[(dbname, o)] for o in oids)

    def _query_text(q, conn):
        if isinstance(q, bytes):
            return q.decode("utf-8", "replace")
        if isinstance(q, str):
            return q
        return q.as_string(conn)                       # psycopg.sql.Composed (a1's B2)

    def _record_psycopg(cur, query, ok, err):
        conn = cur.connection
        t = _norm(_query_text(query, conn))
        dbname = conn.info.dbname
        rec = {"t": t, "db": dbname, "schema": _track(conn, getattr(conn.info, "options", ""), t),
               "frames": _frames(), "ok": ok, "gate": _GATE}
        if not ok:
            rec["err"] = err
            _emit(rec)
            return
        rec["rows"] = cur.rowcount if cur.rowcount is not None else -1
        p, rels = {}, set()
        res, desc = cur.pgresult, cur.description
        if res is not None and desc:
            n = min(res.ntuples, 2000)
            for i, col in enumerate(desc):
                ft = res.ftable(i)
                if ft:
                    rels.add(ft)
                elif col.type_code == 16:              # computed bool: the only graded (P) column
                    seen = []
                    for r in range(n):
                        v = res.get_value(r, i)
                        v = None if v is None else bytes(v).decode("latin-1")
                        if v not in seen:
                            seen.append(v)
                            if len(seen) == 2:
                                break
                    p[str(i)] = seen
        rec["p"], rec["rels"] = p, sorted(rels)
        rec["stamped"] = _stamped(dbname, sorted(rels))
        _emit(rec)

    def _wrap_sync(orig):
        def execute(self, query, *a, **k):
            if getattr(_local, "busy", False):
                return orig(self, query, *a, **k)
            try:
                r = orig(self, query, *a, **k)
            except Exception as e:
                try:
                    _record_psycopg(self, query, False, type(e).__name__)
                except Exception as ee:
                    _err(ee)
                raise
            try:
                _record_psycopg(self, query, True, None)
            except Exception as ee:
                _err(ee)
            return r
        return execute

    def _wrap_async(orig):
        async def execute(self, query, *a, **k):
            if getattr(_local, "busy", False):
                return await orig(self, query, *a, **k)
            try:
                r = await orig(self, query, *a, **k)
            except Exception as e:
                try:
                    _record_psycopg(self, query, False, type(e).__name__)
                except Exception as ee:
                    _err(ee)
                raise
            try:
                _record_psycopg(self, query, True, None)
            except Exception as ee:
                _err(ee)
            return r
        return execute

    _STATUS_N = re.compile(r"(\d+)\s*$")

    def _wrap_asyncpg(name, orig):
        async def method(self, query, *a, **k):
            try:
                r = await orig(self, query, *a, **k)
            except Exception as e:
                try:
                    _emit({"t": _norm(query), "db": getattr(getattr(self, "_params", None), "database", "?"),
                           "schema": "public", "frames": _frames(), "ok": False, "err": type(e).__name__,
                           "gate": _GATE, "driver": "asyncpg"})
                except Exception as ee:
                    _err(ee)
                raise
            try:
                if name in ("fetch",):
                    rows = len(r)
                elif name == "fetchrow":
                    rows = 0 if r is None else 1
                elif name == "execute" and isinstance(r, str):
                    m = _STATUS_N.search(r)
                    rows = int(m.group(1)) if m else -1
                else:
                    rows = -1
                # (P) is NOT-EVALUATED on asyncpg: its Attribute has no table OID (a1's B1).
                _emit({"t": _norm(query), "db": getattr(getattr(self, "_params", None), "database", "?"),
                       "schema": "public", "frames": _frames(), "ok": True, "rows": rows, "p": None,
                       "rels": [], "stamped": None, "gate": _GATE, "driver": "asyncpg"})
            except Exception as ee:
                _err(ee)
            return r
        return method

    def _patch_psycopg(mod):
        for cls_name, wrap in (("Cursor", _wrap_sync), ("AsyncCursor", _wrap_async)):
            cls = getattr(mod, cls_name, None)
            if cls is not None and not getattr(cls, "_sqlguard", False):
                cls.execute = wrap(cls.execute)
                cls.executemany = wrap(cls.executemany)
                cls._sqlguard = True

    def _patch_asyncpg(mod):
        cls = getattr(mod, "Connection", None)
        if cls is not None and not getattr(cls, "_sqlguard", False):
            for n in ("execute", "executemany", "fetch", "fetchrow", "fetchval"):
                if hasattr(cls, n):
                    setattr(cls, n, _wrap_asyncpg(n, getattr(cls, n)))
            cls._sqlguard = True

    # Lazy: patch when (and only if) the process imports a driver, so a python process that never touches
    # a database pays nothing.
    import importlib.abc
    import importlib.machinery

    class _Finder(importlib.abc.MetaPathFinder):
        _PATCH = {"psycopg": _patch_psycopg, "asyncpg": _patch_asyncpg}

        def find_spec(self, name, path, target=None):
            if name not in self._PATCH or getattr(_local, "finding", False):
                return None
            _local.finding = True
            try:
                spec = importlib.machinery.PathFinder.find_spec(name, path)
            finally:
                _local.finding = False
            if spec is None or spec.loader is None:
                return None
            orig_exec, patch = spec.loader.exec_module, self._PATCH[name]

            def exec_module(module):
                orig_exec(module)
                try:
                    patch(module)
                except Exception as e:
                    _err(e)
            spec.loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _Finder())
    for _m, _p in (("psycopg", _patch_psycopg), ("asyncpg", _patch_asyncpg)):
        if _m in sys.modules:                          # already imported (e.g. by site hooks): patch now
            try:
                _p(sys.modules[_m])
            except Exception as _e:
                _err(_e)
