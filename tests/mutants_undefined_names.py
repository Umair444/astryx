"""Authored mutant for tests/test_undefined_names.py: the 08-14 deletion, replayed."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "observatory" / "api" / "main.py"
ORACLE = REPO / "tests" / "test_undefined_names.py"
ENV = "UNDEF_FILES"
TIMEOUT = 300

MUTANTS = {
    "MemoryProposal deleted again (main.py fails to import on 3.12)":
        ("class MemoryProposal(BaseModel):", "class MemoryProposalGone(BaseModel):"),
}
