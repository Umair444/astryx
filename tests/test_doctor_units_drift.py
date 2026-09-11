#!/usr/bin/env python3
"""Oracle for the doctor units-drift LIVE-ORPHAN message (init.sh, medic's ad3fec6).

    venv/bin/python tests/test_doctor_units_drift.py     (also run by nucleus/check.sh)

THE FOOTGUN THIS PINS. doctor's units-drift check compares units/ on disk against the
freshly-DERIVED set; an "orphan" is a unit on disk that the derivation emits no block for.
The naive remedy "rerun ./init.sh to regenerate" (+ a deploy) DELETES an orphan — and when
that orphan is a RUNNING service (geoloc/senses were the live case) the regenerate takes
perception + location intake down. ad3fec6 splits orphans by `systemctl is-active`: a LIVE
orphan routes to manual reconciliation and the destructive advice is withheld. This arm
pins that split so a future edit cannot silently restore a service-deleting instruction. A
message whose regression is a NOISE revert is fine unpinned; one whose regression is a
SERVICE-DELETE is not — the counterfactual-value case where RED-first earns its place.

WHY A SHELL-OUT, NOT AN IMPORT. The logic is bash inline in init.sh's monolithic doctor(),
not a sourceable function, and init.sh `cd`s to its own dir and reads the real units/ — so
it cannot be pointed at a fixture units-root without copying the repo (fragile under the
top-level set -e) or writing into the shared units/ (a seam that writes production). So the
arm drives the REAL doctor and hermetically owns the ONE input it can: LIVENESS, via a
`systemctl` PATH-shim. Drift itself comes from the host's real unit state.

  * PRECONDITION, classified not assumed (a SKIP is a third state — exit 77):
      - no systemd                       -> the units block is unreachable (clone/WSL/macOS)
      - doctor never reached the block   -> deps crashed earlier checks (corpus shown)
      - drift exists but has NO orphan   -> the live-orphan branch is unreachable
        (a missing-only drift or a clean set cannot delete a running service; the guard
         fires exactly when an orphan exists, which is the correct polarity, not a hole)
  * When an orphan IS present a systemctl SHIM forces that orphan is-active=0 (delegating
    every other systemctl call to the real binary, so no other doctor check is perturbed),
    and the arm asserts the message FLIPS:
      - the OLD destructive header ("drifted from the generated set — rerun ...") is ABSENT
        <- the RED-catcher: pre-ad3fec6 emits exactly this line for a live orphan, so the
           arm FIRES against it; the fixed header says "do NOT 'rerun ...'" and would pass a
           naive "rerun ... absent" check, which is why the key is the OLD header, not the
           bare phrase
      - the manual-reconciliation header is PRESENT ("do NOT", "Reconcile by hand")
      - the shimmed orphan is labelled ("regenerate would DELETE it: <unit>") — which proves
        the shim drove the LIVE classification, not whatever the unit's ambient state was

RED-FIRST, verified on-host: against the pre-ad3fec6 init.sh this arm FAILS (the OLD header
is present for the live orphan); against ad3fec6 it PASSES. A message-format change on either
side is a migration for this arm too — update the header strings with the code.

COST: drives ./init.sh doctor twice (discovery + assertion), a few seconds; read-only (doctor
mutates nothing; it regenerates into a mktemp and removes it).
"""
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = Path(os.environ.get("DOCTOR_INIT_SRC") or (REPO / "init.sh"))
EXIT_SKIP = 77
fails = []

OLD_DESTRUCTIVE = "drifted from the generated set — rerun ./init.sh to regenerate"
DRIFT_MARK = "units/ has drifted"
CLEAN_MARK = "units/ ≡ generated set"


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok and detail:
        print(f"        {detail}")
    if not ok:
        fails.append(name)


def skip(reason):
    print(f"SKIP: {reason}")
    sys.exit(EXIT_SKIP)


def run_doctor(extra_path=None):
    env = dict(os.environ)
    if extra_path:
        env["PATH"] = f"{extra_path}{os.pathsep}{env.get('PATH', '')}"
    p = subprocess.run(["bash", str(INIT), "doctor"], cwd=REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    return p.stdout + p.stderr


# ── PRECONDITION ──────────────────────────────────────────────────────────────────
if not INIT.exists():
    check("init.sh exists to be driven", False,
          f"{INIT} is tracked; its absence is a finding, not a skip")
    print(f"\n{len(fails)} FAILED: {fails}")
    sys.exit(1)

if not Path("/run/systemd/system").exists():
    skip("no systemd (/run/systemd/system absent) — doctor's units-drift block is unreachable "
         "on this host (fresh clone / WSL without systemd / macOS). Nothing verified.")

base = run_doctor()

if DRIFT_MARK not in base and CLEAN_MARK not in base:
    skip("doctor did not reach the units-drift block (no drift/clean marker in its output) — "
         f"an earlier check likely aborted (missing deps). Not verified. Saw tail: {base[-300:]!r}")

# Orphan lines carry the unit name after the final ':' — matches both label forms
# ("orphan (on disk, nothing generates it): X" and "orphan — LIVE ...: X").
orphans = list(dict.fromkeys(re.findall(r"orphan[^\n]*?:\s*(astryx-[\w.-]+)", base)))
if not orphans:
    skip("units/ has no on-disk orphan in this host's current state — the live-orphan footgun "
         "branch is unreachable, so there is nothing to pin. Not a hole: the branch cannot "
         "delete a running service without an orphan, and the guard fires exactly when one exists.")

target = orphans[0]

# ── SHIM: force is-active=active for the target orphan; delegate everything else ────
real_systemctl = shutil.which("systemctl") or "/usr/bin/systemctl"
with tempfile.TemporaryDirectory() as d:
    shimdir = Path(d)
    shim = shimdir / "systemctl"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f"REAL={shlex.quote(real_systemctl)}\n"
        f"TARGET={shlex.quote(target)}\n"
        'if [ "$1" = "is-active" ]; then\n'
        '  for a in "$@"; do [ "$a" = "$TARGET" ] && exit 0; done\n'
        'fi\n'
        'exec "$REAL" "$@"\n'
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    out = run_doctor(extra_path=str(shimdir))

tail = out[-500:]
check("a LIVE orphan is NOT told to self-delete via 'rerun ./init.sh to regenerate'",
      OLD_DESTRUCTIVE not in out,
      f"the pre-ad3fec6 header is present — a regenerate would DELETE the running unit "
      f"({target}). out tail: {tail!r}")
check("...the drift is routed to MANUAL reconciliation instead",
      "do NOT" in out and "Reconcile by hand" in out,
      f"expected the live-orphan header. out tail: {tail!r}")
check(f"...and the shimmed orphan is labelled delete-on-regenerate ({target})",
      f"regenerate would DELETE it: {target}" in out,
      f"proves the shim's is-active drove the LIVE classification, not ambient liveness. "
      f"out tail: {tail!r}")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
