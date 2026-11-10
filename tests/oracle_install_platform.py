#!/usr/bin/env python3
"""devtools/mutation_probe.py runs a PYTHON oracle; tests/test_install_platform.sh is shell. This runs that suite as
check.sh does (bash, from the repo root) and exits with its code, so the installer's mutants are judged by the very
arms check.sh runs. The mutant reaches the suite through INSTALL_SRC (inherited)."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.exit(subprocess.run(["bash", str(REPO / "tests" / "test_install_platform.sh")], cwd=REPO).returncode)
