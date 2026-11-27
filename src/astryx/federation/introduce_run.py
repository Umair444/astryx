#!/usr/bin/env python3
"""astryx · introduce_run — introduce.py's two flows, for a caller that must never hold the org's secret key.

    venv/bin/python src/astryx/federation/introduce_run.py --env <home>/.env http://their-host:8845
    venv/bin/python src/astryx/federation/introduce_run.py --env <home>/.env their-org        # through ASTRYX_RELAY

The observatory runs this as a short child process (observatory/api/federation.py), so the key that signs our hello is
loaded here and dies with this process. Same arguments and same functions as introduce.py's CLI; the outcome is ONE
JSON line on stdout (never the key, never the .env): {"ok": true, "via", "org", "url", "pubkey"} with rc 0, or
{"ok": false, "error"} with rc 1 (an introduction refused, a reply that doesn't verify, no relay, a network failure).
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402

from astryx.federation import introduce as intro  # noqa: E402


def run(target: str, env_path: str | None) -> tuple[int, dict]:
    try:
        env = intro.load_env(env_path)
        if target.startswith(("http://", "https://")):
            via, them = "url", intro.introduce(target, env)
        else:
            via, them = "relay", intro.introduce_via_relay(target, env)
    except RuntimeError as e:
        return 1, {"ok": False, "error": str(e)[:300]}
    except Exception as e:  # noqa: BLE001 — a network or file failure is an outcome to report, by its type only
        return 1, {"ok": False, "error": f"{type(e).__name__}: introduction failed"}
    return 0, {"ok": True, "via": via, "org": them.get("org"), "url": them.get("url"), "pubkey": them.get("pubkey")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", help="the org home's .env (default: this checkout's estate)")
    ap.add_argument("target")
    a = ap.parse_args(argv)
    rc, out = run(a.target, a.env)
    print(json.dumps(out))
    return rc


if __name__ == "__main__":
    sys.exit(main())
