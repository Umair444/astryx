"""devtools/exposure_census.py (plan-11859 U0, D5): every door this host opens to a network is classed, or ACCUSED.
Hermetic: census() and the parsers are driven on fixtures shaped like this host's real `ss -ltnpH` and cloudflared
config. The LIVE run is host state, not code, so it never gates a push; its first result (10-22: senses :8460 and
geoloc :8766 accused, a1 BC-1) is in the commit and goes to the owner with the J2 LAN question.

    venv/bin/python tests/test_exposure_census.py      (EXPOSURE_SRC: mutation_probe's channel)
"""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = os.environ.get("EXPOSURE_SRC") or str(REPO / "devtools" / "exposure_census.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


spec = importlib.util.spec_from_file_location("exposure_under_test", SRC)
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)
DECL = {"astryx-observatory": {"scope": "cog", "port": 8090}, "astryx-gateway": {"scope": "cog", "port": 8845},
        "astryx-observatory-org": {"scope": "org", "registry_port": True}, "astryx-canvas": {"scope": "org", "port": 8091},
        "astryx-senses": {"scope": "org"}, "astryx-geoloc": {"scope": "org"}, "astryx-whatsapp": {"scope": "org"}}
OK = [("0.0.0.0", 8090, "astryx-observatory"), ("0.0.0.0", 8845, "astryx-gateway"),
      ("127.0.0.1", 8190, "astryx-observatory-org"), ("127.0.0.1", 18190, "astryx-observatory-org@lab"),
      ("127.0.0.1", 18091, "astryx-canvas@lab"), ("172.17.0.1", 8477, "astryx-whatsapp"),
      ("0.0.0.0", 22, None), ("0.0.0.0", 445, None), ("[::]", 9091, None), ("127.0.0.1", 8767, "genesis-observer")]
REG = {("astryx-observatory-org", "lab"): 18190, ("astryx-canvas", "lab"): 18091}
TUN = [("localhost", 8090), ("localhost", 8845), ("localhost", 8767)]


def run(listeners=(), targets=(), decl=None, reg=REG):
    return ec.census(list(OK) + list(listeners), list(TUN) + list(targets), decl or DECL, reg)


def main():
    base = run()
    check("this host's healthy shape is CLEAN: front, gateway, loopback backends, a bridge-only intake, host services, "
          "the observer behind the tunnel", base == [], str(base))
    f = run([("0.0.0.0", 8460, "astryx-senses")])
    check("a1 BC-1: an ORG-scoped service on 0.0.0.0 is ACCUSED (it reaches the org without the front)",
          len(f) == 1 and "ACCUSED 0.0.0.0:8460 astryx-senses" in f[0] and "ORG-scoped" in f[0], str(f))
    check("…the same service on loopback is fine", run([("127.0.0.1", 8460, "astryx-senses")]) == [])
    f = run([("0.0.0.0", 31337, None)])
    check("an UNKNOWN listener is ACCUSED (an exemption manifest's unknown member defaults to accused)",
          len(f) == 1 and "UNKNOWN listener" in f[0], str(f))
    f = run([("0.0.0.0", 22, "astryx-shell")], decl={**DECL, "astryx-shell": {"scope": "org"}})
    check("a host-owned PORT doesn't excuse an astryx unit that binds it", len(f) == 1 and "ACCUSED" in f[0], str(f))
    f = run([("0.0.0.0", 8477, "astryx-whatsapp")])
    check("the intake on 0.0.0.0, not the docker bridge, is ACCUSED (its exemption is bridge-only)",
          len(f) == 1 and "ACCUSED 0.0.0.0:8477" in f[0], str(f))
    f = run(targets=[("localhost", 8190)])
    check("a tunnel target that is an ORG BACKEND is a finding (published past the front)",
          len(f) == 1 and "tunnel target localhost:8190" in f[0], str(f))
    f = run(targets=[("localhost", 9999)])
    check("a tunnel target nothing listens on is a finding (a dangling door)", len(f) == 1 and "dangling" in f[0], str(f))
    f = run([("127.0.0.1", 8500, "astryx-newthing")])
    check("a1 BC-2: an astryx unit listening with NO declaration is a finding (the two instruments disagree)",
          len(f) == 1 and "no entry in org_units.json" in f[0], str(f))
    f = run([("127.0.0.1", 8099, "astryx-canvas")])
    check("…a declared unit on a port its declaration doesn't name is a finding", len(f) == 1 and "8091" in f[0], str(f))
    f = ec.census([("127.0.0.1", 18092, "astryx-canvas@lab")], [], DECL, REG)
    check("…an ORG INSTANCE is checked against the cog REGISTRY's port, not org_units.json's (the primary's)",
          len(f) == 1 and "18091 (the cog registry)" in f[0], str(f))
    check("…and the instance on its registry port is fine", ec.census([("127.0.0.1", 18091, "astryx-canvas@lab")], [],
                                                                    DECL, REG) == [])

    ss = ("LISTEN 0 2048 0.0.0.0:8460 0.0.0.0:* users:((\"python\",pid=2627,fd=6))\n"
          "LISTEN 0 50 0.0.0.0:445 0.0.0.0:*\n"
          "LISTEN 0 4096 [::]:9091 [::]:*\n"
          "LISTEN 0 2048 127.0.0.1:18191 0.0.0.0:* users:((\"uvicorn\",pid=3087,fd=3))\n")
    rows = ec.parse_ss(ss)
    check("parse_ss: real `ss -ltnpH` lines, with and without a process, IPv6 included",
          rows == [("0.0.0.0", 8460, 2627), ("0.0.0.0", 445, None), ("[::]", 9091, None), ("127.0.0.1", 18191, 3087)],
          str(rows))
    cf = ("tunnel: abc\ningress:\n  - hostname: a.example\n    service: http://localhost:8090\n"
          "  - hostname: b.example\n    service: http://127.0.0.1:8845\n  - service: http_status:404\n")
    check("parse_tunnel: the http targets only (hostnames are never read; the 404 default is no target)",
          ec.parse_tunnel(cf) == [("localhost", 8090), ("127.0.0.1", 8845)], str(ec.parse_tunnel(cf)))
    print(f"\n{'FAIL' if fails else 'PASS'}: exposure census ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
