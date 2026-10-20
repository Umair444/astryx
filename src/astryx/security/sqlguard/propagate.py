"""The ONE opt-in helper for oracles that launch a subject with their own env (a3 #22252 F-a).

    env = {"PATH": ..., "ASTRYX_AGENT": ...}
    subprocess.run([...], env=propagate.env_for_child(env))

Without it, the shim records the launch as an untraced child, and that script's unobserved sites grade NOT
SEARCHED (named, clocked). With it, the child is observed and its sites can climb. It adds ONLY the sqlguard
variables and the shim's PYTHONPATH entry, and only when a sqlguard run is active. Outside check.sh it returns
the env unchanged, so the oracle's stated env is never widened outside a trace. One helper, never a per-test
copy: five ddl() copies is how the org learned that.

THE COG REGISTRY PIN is carried too, in AND out of a trace, but only when the parent has one and the oracle's env
didn't name its own (steward #61378, seed #61381). check.sh:51 and estate.gate() pin the parent to a registry naming
no file; a fresh child env dropped it, so on a cog host the child read /etc/astryx/cog.json, the LIVE orgs, from a
fake tree: tool ledger, session strip and tool nudge read "0 rows" on 10-20. It is carried, never invented, so a
child can't disagree with its parent about the cog, and an oracle that sets its own registry (test_canvas_cog) keeps it.
"""
import os

_SHIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shim")


REGISTRY = "ASTRYX_COG_REGISTRY"


def env_for_child(env: dict) -> dict:
    if REGISTRY in os.environ and REGISTRY not in env:
        env = {**env, REGISTRY: os.environ[REGISTRY]}
    if not os.environ.get("ASTRYX_SQLGUARD_DIR"):
        return env
    out = dict(env)
    for k, v in os.environ.items():
        if k.startswith("ASTRYX_SQLGUARD_"):
            out[k] = v
    out["PYTHONPATH"] = _SHIM + (os.pathsep + out["PYTHONPATH"] if out.get("PYTHONPATH") else "")
    return out
