#!/usr/bin/env python3
"""exposure_census.py: every door this host opens to a network, classed, or ACCUSED (plan-11859 U0, D5; a3 J1, a1 BC-1/2).

The invariant: every path from a public node to an org backend passes the cog's front (D2's mandatory verify is the
primary guard; this is the detector for the day it regresses). Its domain is DERIVED, never hand-listed:
  - LISTENERS from the live socket table (`ss -ltnpH`), each mapped to its systemd unit through /proc/<pid>/cgroup;
  - FORWARDER TARGETS from the tunnel's config (cloudflared's `service:` lines, read for targets only).
Each non-loopback listener is classed:
  front       the cog's front (astryx-observatory, scope cog)
  federation  the gateway (astryx-gateway, scope cog: signed envelopes, its own auth)
  intake      a service that binds the DOCKER BRIDGE only and checks its own secret (INTAKE, each with a reason)
  host        a host-owned service, not astryx (HOST, by port, each with a reason)
  ruled       an astryx unit whose public bind was RULED (OWNER_RULED: the ruling's message id and its evidence)
and anything else is ACCUSED: an org-scoped astryx service on a LAN address reaches the org without the front, and an
UNKNOWN listener is accused too (an exemption manifest's unknown member defaults to accused, never to fine).
Each forwarder target must be a loopback port whose listener is the front, the gateway, or TUNNEL_OK's (with a reason);
an org backend, or a target nothing listens on, is a finding.
The declaration is checked against the socket table (a1 BC-2): an astryx unit listening without an entry in
data/org_units.json, or on a port its entry doesn't declare, is a finding (two instruments that must agree).

rc 0 every door classed; 1 findings (named); 77 NOT SEARCHED (the socket table or the tunnel config can't be read:
a census that can't see a domain never reads green). `census()` is pure, so the oracle drives it on fixtures.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECL = REPO / "src" / "astryx" / "data" / "org_units.json"
TUNNEL = Path("/etc/cloudflared/config.yml")
CLASSES = {"astryx-observatory": "front", "astryx-gateway": "federation"}
INTAKE = {
    "astryx-whatsapp": "the wacli webhook (CLAUDE.md: <docker host>:8477/hook), bound to the docker bridge only and "
                       "checked against WA_WEBHOOK_SECRET",
}
HOST = {
    22: "sshd (the host's own)", 139: "samba (the host's own)", 445: "samba (the host's own)",
    53: "a DNS stub (the host's resolver)", 8096: "the host's docker media stack (not astryx)",
    9091: "the host's docker media stack (not astryx)", 51413: "the host's docker media stack (not astryx)",
}
# exempt by a RULING, not by a class: the unit, the ruling's message id, and its evidence (an unknown unit stays accused)
OWNER_RULED = {
    "astryx-geoloc": "seed #62033 (10-22, from the evidence): its clients are the owner's phone over the internet (carrier "
                     "IPs) posting location, so the intake needs the public bind. A token check on its POST is a goal of its own",
}
TUNNEL_OK = {8767: "the genesis observer: the public visitor surface (VEGA), loopback, not an org backend"}


def loopback(addr: str) -> bool:
    return addr.startswith(("127.", "[::1]", "::1")) or "%lo" in addr


def bridge(addr: str) -> bool:
    return addr.startswith("172.17.")


def census(listeners, targets, decl: dict, registry: dict | None = None) -> list:
    """listeners: [(addr, port, unit | None)], a unit as systemd names it (`astryx-canvas@lab` for an org instance);
    targets: [(host, port)]; decl: org_units.json's units; registry: {(stem, org): port} from the cog registry, the
    authority for an ORG instance's port (org_units.json's `port` is the primary's). -> [finding, ...]."""
    bad = []
    by_port = {}
    for addr, port, full in listeners:
        unit, _, inst = (full or "").partition("@")
        unit = unit or None
        by_port.setdefault(port, []).append((addr, unit))
        if unit and unit.startswith("astryx-"):
            d = decl.get(unit)
            want = (registry or {}).get((unit, inst)) if inst else d.get("port") if d else None
            if d is None:
                bad.append(f"{addr}:{port} {full}: an astryx unit listening with no entry in org_units.json "
                           f"(the declaration and the socket table disagree)")
            elif inst and want is None and registry is not None:
                bad.append(f"{addr}:{port} {full}: an org instance the cog registry gives no port for this unit")
            elif want is not None and want != port and not (d.get("registry_port") and not inst):
                bad.append(f"{addr}:{port} {full}: its declared port is {want} "
                           f"({'the cog registry' if inst else 'org_units.json'}), the socket table says {port}")
        if loopback(addr):
            continue
        cls = CLASSES.get(unit or "")
        if cls and (decl.get(unit) or {}).get("scope") == "cog":
            continue
        if bridge(addr) and unit in INTAKE:
            continue
        if unit in OWNER_RULED:
            continue
        if (unit is None or not unit.startswith("astryx-")) and port in HOST:
            continue
        what = "an ORG-scoped astryx service" if (decl.get(unit or "") or {}).get("scope") == "org" else \
            "an astryx service" if (unit or "").startswith("astryx-") else "an UNKNOWN listener"
        bad.append(f"ACCUSED {addr}:{port} {unit or '(no unit seen)'}: {what} reachable from the network without "
                   f"the front")
    for host, port in targets:
        units = [u for a, u in by_port.get(port, []) if loopback(a) or a.startswith(("0.0.0.0", "[::]", "*"))]
        if not units:
            bad.append(f"tunnel target {host}:{port}: nothing listens there (a dangling door)")
        elif port in TUNNEL_OK or any(CLASSES.get(u or "") for u in units):
            continue
        else:
            bad.append(f"tunnel target {host}:{port} ({', '.join(str(u) for u in units)}): published to the public "
                       f"internet and neither the front, the gateway nor a declared surface")
    return bad


SS_LINE = re.compile(r"^\S+\s+\d+\s+\d+\s+(?P<addr>\S+):(?P<port>\d+)\s+\S+(?:\s+(?P<proc>users:\(.*\)))?")


def parse_ss(text: str) -> list:
    """`ss -ltnpH` lines -> [(addr, port, pid | None)]."""
    out = []
    for ln in text.splitlines():
        m = SS_LINE.match(ln.strip())
        if m:
            pid = re.search(r"pid=(\d+)", m.group("proc") or "")
            out.append((m.group("addr"), int(m.group("port")), int(pid.group(1)) if pid else None))
    return out


def parse_tunnel(text: str) -> list:
    """cloudflared config -> [(host, port)] of its `service:` http targets (hostnames are never read)."""
    return [(m.group(1), int(m.group(2))) for m in re.finditer(r"service:\s*https?://([^:/\s]+):(\d+)", text)]


def unit_of(pid) -> str | None:
    """The systemd unit a pid runs in, instance kept (`astryx-canvas@lab`), from /proc/<pid>/cgroup (no secret there)."""
    if pid is None:
        return None
    try:
        m = re.search(r"/([^/]+)\.service", Path(f"/proc/{pid}/cgroup").read_text())
    except OSError:
        return None
    return m.group(1) if m else None


def registry_ports() -> dict | None:
    """{(unit stem, org): port} from the cog registry (astryx.orgs.load), or None on one org / no registry."""
    try:
        sys.path.insert(0, str(REPO / "src"))
        from astryx import orgs
        reg = orgs.load() or {}
    except Exception:                                  # noqa: BLE001 — no readable registry: the check says so
        return None
    return {(stem, org): port for org, e in reg.items() for stem, port in (e.get("ports") or {}).items()} or None


def main() -> int:
    try:
        ss = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"exposure census: NOT SEARCHED, the socket table can't be read ({e})")
        return 77
    rows = parse_ss(ss.stdout)
    if ss.returncode or not rows:
        print(f"exposure census: NOT SEARCHED, `ss -ltnpH` gave rc {ss.returncode} and {len(rows)} listener(s)")
        return 77
    listeners = [(a, p, unit_of(pid)) for a, p, pid in rows]
    try:
        targets = parse_tunnel(TUNNEL.read_text()) if TUNNEL.exists() else []
        tunnel_note = f"{len(targets)} tunnel target(s) from {TUNNEL}" if TUNNEL.exists() else f"no {TUNNEL}: no tunnel"
    except OSError as e:
        print(f"exposure census: NOT SEARCHED, the tunnel config {TUNNEL} can't be read ({e})")
        return 77
    decl = json.loads(DECL.read_text())["units"]
    reg = registry_ports()
    bad = census(listeners, targets, decl, reg)
    public = sorted({(a, p) for a, p, _ in listeners if not loopback(a)}, key=lambda x: x[1])
    print(f"exposure census: {len(listeners)} listener(s), {len(public)} non-loopback; {tunnel_note}; "
          f"{'cog registry: ' + str(len(reg)) + ' org port(s)' if reg else 'no cog registry (instance ports unchecked)'}")
    for f in bad:
        print(f"  {f}")
    print(f"exposure census: {'FINDINGS (' + str(len(bad)) + ')' if bad else 'every door classed'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
