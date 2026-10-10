#!/usr/bin/env python3
"""astryx · ear_census — hearing's COPIER CENSUS and SNAPPER arms (plan-8674 S1; #42048 D1, #42059 correction).

D1 moved the raw transcript into its own database, so a copier that FORGETS the ear doesn't copy it. What can still
reach it is a copier that NAMES it, or one that copies the whole cluster. This arm looks for exactly those, estate-
wide, on the LIVE root, with the binary-grep discipline of estate_grep.sh (no .gitignore blindness: homes/, triggers/
and the gitignored estate are searched).

THE PHYSICAL TOKENS ARE DERIVED, NEVER LISTED (#42059's correction). The live cluster is NOT init.sh's default
volume: the DSN goes to 127.0.0.1:5432 → container genesis-pg, whose data is a BIND mount. A token list written from
init.sh would read GREEN while blind to the real path. So at run time: the DSN's host:port → the ONE container
publishing it (`docker ps`) → its data mounts (`docker inspect`: bind sources + volume names). If that can't be
resolved the arm exits 77 BLIND, never GREEN.

RED on a code line that:
  - names astryx_ear (outside the ear's own files, which are its doors);
  - runs pg_dumpall or pg_basebackup (whole-cluster copiers reach the ear without naming it);
  - runs pg_dump with a NON-LITERAL database argument (a variable could be the ear), unless the exact line is a
    REVIEWED pin (nucleus/ear_census_reviewed.json) whose binding this run re-verifies;
  - copies (tar/rsync/cp/scp/dd/restic/borg/rclone/docker cp/shutil/tarfile) a path that is the data source, inside
    it, or an ANCESTOR of it (a home backup copies the cluster), or `docker cp`s the container itself.

The corpus is CODE-SHAPED files (scripts, python, units, crontabs, json/yaml/toml config, shebang files) under the
root, plus the user crontab and the deployed systemd units. Comments and python docstrings are not code. Transcripts,
logs and markdown are not copier sites (a resident running `pg_dump astryx_ear` ad hoc leaves no file: that is the
READER census's catch, via the login trigger).

GRADE: DETECTION, token-shaped. Bounds, stated: a copier built by string assembly at run time, a relative path
resolved against an unknown cwd, a copy of `/` itself, and snapshotters other than snapper are not graded here.

SNAPPER ARM (a2): RED if any snapper config's subvolume would CONTAIN the data source in its snapshots: the
subvolume is an ancestor of the source AND no subvolume/mount boundary (a different st_dev, or a btrfs subvolume root,
inode 256) lies between them. Today: config `root` → `/`, the data is on @home (mounted at /home, its own subvolume):
GREEN for a real reason.

    venv/bin/python -m nucleus.ear_census [copiers|snapper]     0 GREEN, 1 RED, 77 BLIND
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tokenize
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
EXIT_BLIND = 77
REVIEWED = REPO / "nucleus" / "ear_census_reviewed.json"
EAR_DB = "astryx_ear"

# The ear's own files may name its database: they ARE its doors. Matched by path SUFFIX, so a worktree's copy counts.
EAR_OWN = ("nucleus/ear_store.py", "nucleus/ear_census.py", "nucleus/ear_census_reviewed.json", "bridges/ear.py",
           "bridges/ear_stt.py", "nucleus/shipped_triggers/ear_census.py", "tests/test_ear_store.py",
           "tests/test_ear_census.py", "tests/test_ear_service.py")
# Wholly exempt: the detector's own patterns, its review ledger (it quotes the lines it pins), and its oracle, which
# PLANTS every copier shape as a string fixture (its arms are what prove the detector).
FIXTURES = ("nucleus/ear_census.py", "nucleus/ear_census_reviewed.json", "tests/test_ear_census.py")
CODE_EXT = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".conf", ".service", ".timer",
            ".yml", ".yaml", ".toml", ".cron", ".sql", ".json", ".ini"}
SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "dist", "__pycache__", ".transcript-aside", ".cache", ".npm"}
MAX_BYTES = 2_000_000

RE_EAR = re.compile(r"astryx_ear\b", re.I)
RE_WHOLE = re.compile(r"(?<![\w-])(pg_dumpall|pg_basebackup)(?![\w-])")
RE_DUMP = re.compile(r"(?<![\w-])pg_dump(?![\w-])")
RE_COPY = re.compile(r"(?<![\w.-])(tar|rsync|cp|scp|dd|restic|borg|rclone|docker\s+cp|shutil\.(?:copytree|copy2?|"
                     r"copyfile|make_archive|move)|tarfile\.open|zipfile\.ZipFile)(?![\w-])")
RE_PATH = re.compile(r"""(?:~|\$\{?HOME\}?|Path\.home\(\))(?:/[^\s'"`;|&)<>,\]]*)?|/[^\s'"`;|&)<>,\]]+""")
DUMP_OPTS_WITH_VALUE = {"-f", "--file", "-F", "--format", "-j", "--jobs", "-Z", "--compress", "-E", "--encoding",
                        "-n", "--schema", "-N", "--exclude-schema", "-t", "--table", "-T", "--exclude-table", "-h",
                        "--host", "-p", "--port", "-U", "--username", "--role", "-S", "--superuser", "--section",
                        "--lock-wait-timeout", "--exclude-table-data", "--filter"}


# ── resolve: the DSN's container and its data mounts (BLIND when unresolvable) ───────────────────────────────
def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def resolve(dsn: str, run=_run) -> dict | None:
    """{'container', 'sources': [paths], 'volumes': [names], 'host', 'port'} or None (BLIND)."""
    from psycopg.conninfo import conninfo_to_dict
    try:
        d = conninfo_to_dict(dsn)
    except Exception:                                              # noqa: BLE001
        return None
    host, port = d.get("host") or "localhost", str(d.get("port") or 5432)
    if host.startswith("/"):
        return None                                                # a unix socket: no published port to map
    hosts = {host} | ({"127.0.0.1", "::1"} if host == "localhost" else set())
    ps = run(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"])
    if ps is None:
        return None
    hits = []
    for line in ps.splitlines():
        name, _, ports = line.partition("\t")
        for ip, p in re.findall(r"(\[?[0-9a-fA-F:.]*\]?):(\d+)->\d+/tcp", ports):
            ip = ip.strip("[]")
            if p == port and (ip in hosts or ip in ("0.0.0.0", "::", "")):
                hits.append(name.strip())
                break
    if len(set(hits)) != 1:
        return None
    ctr = hits[0]
    raw = run(["docker", "inspect", ctr])
    try:
        info = json.loads(raw)[0]
    except (TypeError, ValueError, IndexError):
        return None
    env = dict(e.split("=", 1) for e in (info.get("Config", {}).get("Env") or []) if "=" in e)
    pgdata = env.get("PGDATA", "/var/lib/postgresql/data")

    def related(dest: str) -> bool:                                # dest is PGDATA, above it, or inside it
        dest, pd = dest.rstrip("/") or "/", pgdata.rstrip("/")
        return pd == dest or pd.startswith(dest + "/") or dest.startswith(pd + "/")
    sources, volumes = [], []
    for m in info.get("Mounts") or []:
        if not related(m.get("Destination", "")):
            continue
        if m.get("Source"):
            sources.append(m["Source"].rstrip("/") or "/")
        if m.get("Type") == "volume" and m.get("Name"):
            volumes.append(m["Name"])
    if not sources and not volumes:
        return None                                                # data not on a host path we can see: BLIND
    return {"container": ctr, "sources": sorted(set(sources)), "volumes": sorted(set(volumes)),
            "host": host, "port": port, "pgdata": pgdata}


# ── the corpus ───────────────────────────────────────────────────────────────────────────────────────────────
def _code_shaped(p: Path) -> bool:
    if p.suffix in CODE_EXT:
        return True
    if p.suffix:
        return False
    try:
        with open(p, "rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def corpus(root: Path) -> list[Path]:
    out = []
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            p = Path(dirpath) / f
            if p.is_symlink() or not p.is_file():
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            if _code_shaped(p):
                out.append(p)
    return sorted(out)


def _py_code_lines(src: str) -> dict[int, str]:
    """line_no → the line with comments cut and docstrings blanked. Falls back to raw lines on a parse error."""
    lines = src.splitlines()
    keep = {i + 1: l for i, l in enumerate(lines)}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                r, c = tok.start
                keep[r] = keep[r][:c]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")             # a scanned file's own SyntaxWarnings are not ours
            tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                        and isinstance(first.value.value, str):
                    for n in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                        keep[n] = ""
    except (tokenize.TokenError, SyntaxError, IndentationError, ValueError):
        return {i + 1: l for i, l in enumerate(lines)}
    return keep


def code_lines(path: Path, text: str) -> dict[int, str]:
    if path.suffix == ".py":
        return _py_code_lines(text)
    out = {}
    sqlish = path.suffix == ".sql"
    for i, l in enumerate(text.splitlines(), 1):
        s = l.strip()
        if (s.startswith(("#", "//")) and not s.startswith("#!")) or (sqlish and s.startswith("--")):
            continue
        if sqlish:
            out[i] = re.split(r"\s--\s", l, maxsplit=1)[0]
        else:
            out[i] = re.split(r"\s#\s", l, maxsplit=1)[0] if path.suffix != ".json" else l
    return out


# ── the line classifiers ─────────────────────────────────────────────────────────────────────────────────────
def dump_db(line: str) -> tuple[str, str | None]:
    """('literal', db) | ('nonliteral', None) for the pg_dump invocation on `line`."""
    m = RE_DUMP.search(line)
    rest = line[m.end():]
    # python list form: ["pg_dump", "-Fc", "-d", src] — quoted = literal, a bare name = a variable
    if re.search(r"""["']pg_dump["']""", line):
        toks = re.findall(r"""\s*,?\s*(?:"([^"]*)"|'([^']*)'|([A-Za-z_][\w.\[\]()]*))""", rest.lstrip("\"'"))
        items = [(a or b, False) if (a or b) else (c, True) for a, b, c in toks if (a or b or c)]
    else:
        try:
            items = [(t, False) for t in shlex.split(rest, comments=False)]
        except ValueError:
            items = [(t, False) for t in rest.split()]
        items = [(t, any(ch in t for ch in "$`{}%")) for t, _ in items]
    pos, i = None, 0
    while i < len(items):
        t, var = items[i]
        if t in ("-d", "--dbname") and i + 1 < len(items):
            pos = items[i + 1]
            break
        if t.startswith("--dbname="):
            pos = (t.split("=", 1)[1], var)
            break
        if t in DUMP_OPTS_WITH_VALUE:
            i += 2
            continue
        if t.startswith("-") or t in (">", "|", "&&", ";", "2>&1"):
            if t in (">", "|", "&&", ";"):
                break
            i += 1
            continue
        pos = (t, var)
        break
    if pos is None or pos[1]:
        return "nonliteral", None
    db = pos[0]
    if "://" in db:
        db = db.rsplit("/", 1)[-1].split("?")[0]
    elif "=" in db:
        mm = re.search(r"dbname=([^\s]+)", db)
        if not mm:
            return "nonliteral", None
        db = mm.group(1)
    return "literal", db


def _norm(tok: str, home: str) -> str:
    tok = tok.strip("'\"`")
    for h in ("Path.home()", "${HOME}", "$HOME", "~"):
        if tok.startswith(h):
            tok = home + tok[len(h):]
            break
    return os.path.normpath(tok) if tok.startswith("/") else tok


def touches(path: str, sources: list[str]) -> bool:
    """`path` is a source, inside one, or an ANCESTOR of one ('/' itself excluded: a stated bound)."""
    if path in ("/", "") or not path.startswith("/"):
        return False
    return any(path == s or s.startswith(path.rstrip("/") + "/") or path.startswith(s + "/") for s in sources)


def classify(line: str, phys: dict | None, home: str) -> list[str]:
    kinds = []
    if RE_EAR.search(line):
        kinds.append("names-astryx_ear")
    w = RE_WHOLE.search(line)
    if w:
        kinds.append(w.group(1))
    if RE_DUMP.search(line):
        how, db = dump_db(line)
        if how == "nonliteral":
            kinds.append("pg_dump-nonliteral")
        elif db and db.lower() == EAR_DB:
            kinds.append("pg_dump-astryx_ear")
    if phys and RE_COPY.search(line):
        ctr = phys["container"]
        if re.search(r"docker\s+cp\b", line) and re.search(rf"(?<![\w-]){re.escape(ctr)}(?![\w-])", line):
            kinds.append("docker-cp-container")
        for tok in RE_PATH.findall(line):
            if touches(_norm(tok, home), phys["sources"]):
                kinds.append(f"copies-data-path:{_norm(tok, home)}")
                break
        for v in phys["volumes"]:
            if re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", line):
                kinds.append(f"copies-volume:{v}")
    return kinds


def line_sha(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()[:16]


def load_reviewed(path: Path = REVIEWED) -> list[dict]:
    try:
        return json.loads(path.read_text())["reviewed"]
    except (OSError, ValueError, KeyError):
        return []


def _pin_ok(pin: dict, dsn: str) -> str | None:
    """None if the pin's binding holds THIS run, else why not."""
    if pin.get("resolves") == "ASTRYX_DSN":
        from psycopg.conninfo import conninfo_to_dict
        db = conninfo_to_dict(dsn).get("dbname") if dsn else None
        if not db:
            return "the org DSN has no dbname this run: the pin's binding can't be verified"
        if db.lower() == EAR_DB:
            return "the org DSN now names astryx_ear"
    return None


def extra_files() -> list[Path]:
    """The deployed copiers outside the root: system crontabs and installed units (read if readable)."""
    out = [Path("/etc/crontab")]
    for d in ("/etc/cron.d", "/etc/systemd/system", str(Path.home() / ".config/systemd/user")):
        p = Path(d)
        if p.is_dir():
            out += [f for f in p.iterdir() if f.is_file() and (d.endswith("cron.d") or f.suffix in (".service", ".timer"))]
    return [f for f in out if f.is_file()]


def scan(root: Path, phys: dict | None, reviewed: list[dict] | None = None, dsn: str = "",
         files: list[Path] | None = None, crontab: str | None = None, home: str | None = None) -> dict:
    """{'red': [...], 'pinned': [...], 'files': n}. Each finding: {path, line, kinds, code}."""
    home = home or str(Path.home())
    reviewed = load_reviewed() if reviewed is None else reviewed
    pins = {(p["path"], p["sha"]): p for p in reviewed}
    red, pinned = [], []
    files = corpus(root) if files is None else files
    sources = [(f, str(f.relative_to(root)) if f.is_relative_to(root) else str(f)) for f in files]
    blobs = [(rel, f, None) for f, rel in sources]
    if crontab:
        blobs.append(("crontab:-l", Path("crontab.sh"), crontab))
    for rel, f, text in blobs:
        if text is None:
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
        own = any(rel.endswith(s) for s in EAR_OWN)
        if any(rel.endswith(s) for s in FIXTURES):
            continue
        for n, code in code_lines(f, text).items():
            if not code or not (RE_EAR.search(code) or RE_WHOLE.search(code) or RE_DUMP.search(code)
                                or RE_COPY.search(code)):
                continue
            kinds = classify(code, phys, home)
            if own:
                kinds = [k for k in kinds if k != "names-astryx_ear"]
            if not kinds:
                continue
            hit = {"path": rel, "line": n, "kinds": kinds, "code": code.strip()[:200]}
            pin = pins.get((rel, line_sha(code)))
            if pin and set(kinds) <= set(pin.get("kinds", [])):
                why = _pin_ok(pin, dsn)
                if why is None:
                    pinned.append({**hit, "why": pin["why"]})
                    continue
                hit["kinds"] = kinds + [f"pin-binding-broken: {why}"]
            red.append(hit)
    return {"red": red, "pinned": pinned, "files": len(blobs)}


# ── snapper ──────────────────────────────────────────────────────────────────────────────────────────────────
def snapper_subvolumes(configs_dir: Path = Path("/etc/snapper/configs")) -> list[tuple[str, str]] | None:
    """[(config, subvolume)], [] when snapper isn't configured, None when the configs can't be read (BLIND)."""
    if not configs_dir.exists():
        return []
    try:
        out = []
        for f in sorted(configs_dir.iterdir()):
            m = re.search(r'^SUBVOLUME="?([^"\n]+)"?', f.read_text(), re.M)
            if m:
                out.append((f.name, m.group(1)))
        return out
    except OSError:
        return None


def covers(subvol: str, source: str, stat=os.stat) -> bool:
    """Would a snapshot of `subvol` contain `source`? Ancestor, and no subvolume/mount boundary in between."""
    subvol, source = os.path.normpath(subvol), os.path.normpath(source)
    if not (source == subvol or source.startswith(subvol.rstrip("/") + "/")):
        return False
    top = stat(subvol).st_dev
    p = Path(source)
    chain = [p] + [q for q in p.parents if len(str(q)) > len(subvol.rstrip("/"))]
    for d in chain:
        st = stat(str(d))
        if st.st_dev != top or st.st_ino == 256:                  # another mount, or a btrfs subvolume root
            return False
    return True


def snapper_findings(sources: list[str], configs_dir: Path = Path("/etc/snapper/configs"), stat=os.stat):
    subs = snapper_subvolumes(configs_dir)
    if subs is None:
        return None
    try:
        return [f"snapper config '{c}' (subvolume {s}) snapshots the pg data source {src}"
                for c, s in subs for src in sources if covers(s, src, stat)]
    except OSError:
        return None


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────────────
def main(argv) -> int:
    from nucleus.ear_store import admin_dsn
    what = argv[1] if len(argv) > 1 else "all"
    dsn = admin_dsn()
    phys = resolve(dsn) if dsn else None
    if phys is None:
        print("ear_census: BLIND: the DSN's container (and its data mounts) couldn't be resolved; nothing graded")
        return EXIT_BLIND
    print(f"ear_census: {phys['host']}:{phys['port']} → container {phys['container']}, data "
          f"{', '.join(phys['sources'] + phys['volumes'])}")
    rc = 0
    if what in ("all", "copiers"):
        root = Path(os.environ.get("EAR_CENSUS_ROOT") or REPO)
        res = scan(root, phys, dsn=dsn, files=corpus(root) + extra_files(), crontab=_run(["crontab", "-l"]))
        for h in res["red"]:
            print(f"  RED {h['path']}:{h['line']}  {', '.join(h['kinds'])}  | {h['code'][:120]}")
        print(f"ear_census copiers: {'RED' if res['red'] else 'GREEN'} ({len(res['red'])} red, {len(res['pinned'])} "
              f"reviewed pins held, {res['files']} code files searched under {root} + deployed units/crontabs)")
        rc = max(rc, 1 if res["red"] else 0)
    if what in ("all", "snapper"):
        f = snapper_findings(phys["sources"])
        if f is None:
            print("ear_census snapper: BLIND (configs unreadable)")
            return EXIT_BLIND
        for x in f:
            print(f"  RED {x}")
        print(f"ear_census snapper: {'RED' if f else 'GREEN'} ({len(snapper_subvolumes() or [])} configs)")
        rc = max(rc, 1 if f else 0)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
