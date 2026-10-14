"""astryx · hear_worker — the CHILD that runs one agent's sensors/<agent>/hear.py (plan-8674 S2, a4 #42048 D3).

Started by src/astryx/hearing/hear_pool.py inside bwrap: no network, no /home (so no .env, no repo), an env of PATH and LANG
only (no DSN of any kind), stdout and stderr on /dev/null so a debug print(utt) lands nowhere. It reads one JSON
utterance per line on stdin and answers one JSON decision per line on the pipe fd named in argv, the only way out.

    def hear(utt: dict) -> dict      # utt = {"id", "ts", "text", "view"}
        {"decision": "pass", "matched_name": "<your name>"}   wake me (optionally "span": [start, end] in words)
        {"decision": "ignore"}                                 not for me

Whatever comes back is checked by the dispatcher, never trusted (hear_pool.validate).
"""
import importlib.util
import json
import os
import sys


def main(path: str, fd: int) -> None:
    out = os.fdopen(fd, "w", buffering=1)
    try:
        spec = importlib.util.spec_from_file_location("hear", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = mod.hear
    except Exception as e:
        fn, load_err = None, type(e).__name__
    out.write('{"ready": true}\n')                  # the pool's deadline starts after this, not at cold start
    for line in sys.stdin:
        if fn is None:
            out.write(json.dumps({"error": f"load {load_err}"}) + "\n")
            continue
        try:
            d = fn(json.loads(line))
            out.write(json.dumps(d if isinstance(d, dict) else {"error": "not a dict"}) + "\n")
        except Exception as e:
            out.write(json.dumps({"error": type(e).__name__}) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
