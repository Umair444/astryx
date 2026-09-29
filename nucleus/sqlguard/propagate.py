"""The ONE opt-in helper for oracles that launch a subject with their own env (a3 #22252 F-a).

    env = {"PATH": ..., "ASTRYX_AGENT": ...}
    subprocess.run([...], env=propagate.env_for_child(env))

Without it, the shim records the launch as an untraced child, and that script's unobserved sites grade NOT
SEARCHED (named, clocked). With it, the child is observed and its sites can climb. It adds ONLY the sqlguard
variables and the shim's PYTHONPATH entry, and only when a sqlguard run is active. Outside check.sh it returns
the env unchanged, so the oracle's stated env is never widened outside a trace. One helper, never a per-test
copy: five ddl() copies is how the org learned that.
"""
import os

_SHIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shim")


def env_for_child(env: dict) -> dict:
    if not os.environ.get("ASTRYX_SQLGUARD_DIR"):
        return env
    out = dict(env)
    for k, v in os.environ.items():
        if k.startswith("ASTRYX_SQLGUARD_"):
            out[k] = v
    out["PYTHONPATH"] = _SHIM + (os.pathsep + out["PYTHONPATH"] if out.get("PYTHONPATH") else "")
    return out
