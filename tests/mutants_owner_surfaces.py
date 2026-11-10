"""Mutants for bridges/owner_surfaces.py: the one predicate naming the owner rows a bridge delivers, which the
observatory's thread pane must never mark read (a4 #57418). The oracle is tests/test_observatory_thread_read.py,
which loads OWNER_SURFACES_SRC in place of the real module. Each mutant forgets one bridge's thread shape."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "bridges" / "owner_surfaces.py"
ORACLE = REPO / "tests" / "test_observatory_thread_read.py"
ENV = "OWNER_SURFACES_SRC"
MUTANTS = {
    "S1 forgets whatsapp's t- threads": (" OR thread LIKE 't-%'", ""),
    "S2 forgets whatsapp's wa: threads": (" OR thread LIKE 'wa:%'", ""),
    "S3 forgets telegram": (" OR thread LIKE 'tg:%'", ""),
    "S4 forgets discord": ("\"OR thread LIKE 'dc:%' OR", "\"OR"),
    "S5 forgets canvas": (" OR thread LIKE 'cv:%'", ""),
    "S6 forgets tier- threads": (" OR thread LIKE 'tier-%'", ""),
    "S7 forgets the ear": (" OR thread LIKE 'ear-%'", ""),
    "S8 forgets a release on a named thread": ("\"OR delivery->'release' IS NOT NULL)\"", "\")\""),
}
