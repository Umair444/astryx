"""Mutants for plan-9139 S1e, src/astryx/security/release_migrate.py (a3 BC-2, #55033 D1-D3). The oracle is
tests/test_release_migrate.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "src" / "astryx" / "security" / "release_migrate.py"
ORACLE = REPO / "tests" / "test_release_migrate.py"
ENV = "RELEASE_MIGRATE_SRC"
MUTANTS = {
    "X1 D1 broken: a migrated row keeps the receipt's rendered text":
        ('KEEP = frozenset({"ok", "handle", "message_id", "door", "migrated"})',
         'KEEP = frozenset({"ok", "handle", "message_id", "door", "migrated", "rendered"})'),
    "X2 D2 broken: a migrated marker passes without its pointer":
        ("    if MIGRATED_RX.fullmatch(body) and not _obj(d.get(\"migrated\")).get(\"pointer\"):\n        return False",
         "    if False:\n        return False"),
    "X3 D2 broken: a marker is matched as a PREFIX (text after it passes)":
        ("    return isinstance(s, str) and any(rx.fullmatch(s) for rx in rxs)",
         "    return isinstance(s, str) and any(rx.match(s) for rx in rxs)"),
    "X4 rows delivered to the route's handle on another thread are missed":
        ("\"SELECT id, body, delivery FROM messages WHERE thread = %s OR delivery->>'handle' = %s \"",
         "\"SELECT id, body, delivery FROM messages WHERE thread = %s OR (false AND delivery->>'handle' = %s) \""),
    "X5 D1 broken: an unknown delivery key (a caption) passes the census":
        ('DOOR_KEYS = KEEP | {"release", "ingress", "ingress_withheld", "rendered", "error", "sender_jid", "phone",',
         'DOOR_KEYS = KEEP | {"caption", "release", "ingress", "ingress_withheld", "rendered", "error", "sender_jid", "phone",'),
    "X6 not idempotent: a clean row is moved again":
        ("        if route_clean(body, delivery):\n            continue", "        if False:\n            continue"),
    "X7 a move that leaves the census non-zero is committed":
        ("            if not after[\"database_clean\"]:", "            if False:"),
    "X8 a step's text survives the move":
        ("        cur.execute(\"UPDATE steps SET content = %s, meta = %s WHERE id = %s\",",
         "        cur.execute(\"UPDATE steps SET content = content || %s, meta = %s WHERE id = %s\","),
    "X9 a turn's usage block is lost (the economy can't bill it)":
        ("Jsonb({\"withheld\": \"migrated\", \"usage\": _obj(r).get(\"usage\"), \"migrated\": mig})",
         "Jsonb({\"withheld\": \"migrated\", \"usage\": None, \"migrated\": mig})"),
    "X10 the transcript residual isn't counted (history reads clean while it exists)":
        ("    return {\"transcript_files\": len(files), \"transcript_bytes\": sum(p.stat().st_size for p in files),",
         "    return {\"transcript_files\": 0, \"transcript_bytes\": 0,"),
    "X12 only top-level transcript files count (a file under <session>/subagents/ is missed; a3 F1)":
        ("    files = [p for p in td.rglob(\"*\") if p.is_file() and not p.is_symlink()] if td.is_dir() else []",
         "    files = [p for p in td.glob(\"*.jsonl\") if p.is_file()] if td.is_dir() else []"),
    "X13 a route with no chat is migrated (a census of nothing reads clean; a3 N4)":
        ("    if not hits[0].get(\"chat\"):", "    if False:"),
    "X14 refresh.sh's .transcript-aside isn't counted (the moved history reads as gone; seed #57083)":
        ("            \"aside_files\": len(af), \"aside_bytes\": sum(p.stat().st_size for p in af),",
         "            \"aside_files\": 0, \"aside_bytes\": 0,"),
    "X15 only top-level aside files count (the moved <session>/subagents/ tree is missed)":
        ("    af = [p for p in aside.rglob(\"*\") if p.is_file() and not p.is_symlink()] if aside.is_dir() else []",
         "    af = [p for p in aside.glob(\"*\") if p.is_file() and not p.is_symlink()] if aside.is_dir() else []"),
    "X16 the aside is treated like the live sink (excluded from history_clean)":
        ("if k != \"transcript_is_live_sink\")", "if k not in (\"transcript_is_live_sink\", \"aside_files\", \"aside_bytes\"))"),
    "X11 --apply reads the key AFTER writing (no key fails mid-move)":
        ("        key = R.mac_key() if a.apply else None", "        key = None"),
}
