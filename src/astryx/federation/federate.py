#!/usr/bin/env python3
"""astryx · federate — connect this org to the internet of agents.

    astryx federate                       # interactive
    venv/bin/python src/astryx/federation/federate.py --relay [URL] [--introduce|--no-introduce] [--unlisted]
    venv/bin/python src/astryx/federation/federate.py --public-url https://org.example.com [--force]
    venv/bin/python src/astryx/federation/federate.py --skip

Two ways in. (1) Through the relay: no port forwarding, works from any home network; the
gateway holds an outbound connection to the relay and collects its mail there. (2) Your own
public address: a forwarded port 8845 (or a tunnel) that the relay can reach from outside.
Writes ASTRYX_RELAY / ASTRYX_URL to .env in place (other lines untouched, no value printed),
then offers to introduce the org to the founder's org. Called by `astryx init` and the seed.
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402
import argparse
import sys
from pathlib import Path

import httpx
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey

REPO = repo_root(__file__)
sys.path.insert(0, str(REPO))
from astryx.federation import introduce as intro  # noqa: E402

DEFAULT_RELAY = "https://relay.umairfiaz.com"
RESTART = "sudo systemctl restart astryx-gateway"


# ------------------------------------------------------------------ .env, in place
def set_env(path: Path, values: dict) -> None:
    """Rewrite KEY=... lines in place, append the missing keys, keep every other line."""
    lines = path.read_text().splitlines() if path.exists() else []
    left = dict(values)
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in left:
            out.append(f"{k}={left.pop(k)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in left.items()]
    path.write_text("\n".join(out) + "\n")


def _pubkey(env: dict) -> str:
    return SigningKey(env["ASTRYX_SECRET_KEY"].encode(), encoder=HexEncoder).verify_key.encode(
        HexEncoder).decode()


# ------------------------------------------------------------------ the two ways in
def check_reach(relay: str, url: str, pubkey: str) -> tuple[bool, str]:
    """Ask the relay to reach <url>/astryx/identity from outside; it must answer with OUR key."""
    try:
        r = httpx.get(f"{relay}/relay/reach", params={"url": url}, timeout=20).json()
    except Exception as e:
        return False, f"could not ask the relay at {relay} ({type(e).__name__})"
    if not r.get("reachable"):
        return False, r.get("error") or "not reachable"
    if r.get("pubkey") != pubkey:
        return False, f"{url} answered, but as a different org ({r.get('org')}): wrong host or port"
    return True, f"{url} answers from outside as this org"


PORT_HELP = """\
  Your gateway was not reachable from outside. To fix it:
    1. Router: forward TCP port 8845 to this machine's LAN address
       (often under "Port forwarding" or "Virtual server").
    2. Firewall on this machine: allow 8845, e.g.  sudo ufw allow 8845/tcp
    3. The gateway must be running:  systemctl status astryx-gateway
    4. Use the address the world sees (your public IP or a domain pointing at it),
       e.g. http://203.0.113.7:8845. Some ISPs block inbound ports (CGNAT): then
       choose the relay instead; it needs no forwarding."""


def ask(prompt: str, default: str = "") -> str:
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ""
    return v or default


def yes(prompt: str, default=True) -> bool:
    v = ask(prompt + (" [Y/n] " if default else " [y/N] ")).lower()
    return default if not v else v.startswith("y")


def founder(relay: str) -> dict | None:
    try:
        return httpx.get(f"{relay}/relay/host", timeout=20).json()
    except Exception:
        return None


def do_introduce(relay: str, env_path: Path) -> int:
    host = founder(relay)
    if not host or not host.get("org"):
        print(f"  ✗ the relay at {relay} did not say who hosts it; introduce later with "
              "src/astryx/federation/introduce.py")
        return 1
    try:
        them = intro.introduce(host.get("url") or relay, intro.load_env(env_path))
    except Exception as e:
        print(f"  ✗ introduction to {host['org']} failed: {e}")
        return 1
    row = intro.peer_row(intro.load_env(env_path), them["org"])
    print(f"  ✓ introduced to {them['org']}. Peer row:")
    if row:
        print(f"      org={row['org']}  url={row['url']}  status={row['status']}  "
              f"key={row['pubkey'][:16]}…")
    print(f"    agents can now: send(to='seed@{them['org']}', body='hello')")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="connect this org to the internet of agents")
    way = ap.add_mutually_exclusive_group()
    way.add_argument("--relay", nargs="?", const=DEFAULT_RELAY, metavar="URL",
                     help=f"connect through a relay (default {DEFAULT_RELAY})")
    way.add_argument("--public-url", metavar="URL", help="this org's own public gateway address")
    way.add_argument("--skip", action="store_true", help="not now")
    ap.add_argument("--relay-url", default=None, help="the relay used to test --public-url")
    ap.add_argument("--introduce", dest="introduce", action="store_true", default=None)
    ap.add_argument("--no-introduce", dest="introduce", action="store_false")
    ap.add_argument("--unlisted", action="store_true", help="stay out of the relay directory")
    ap.add_argument("--force", action="store_true", help="write --public-url even if unreachable")
    ap.add_argument("--env-file", default=str(paths.estate(__file__) / ".env"))
    a = ap.parse_args(argv)
    env_path = Path(a.env_file)
    interactive = a.relay is None and a.public_url is None and not a.skip

    if not env_path.exists() or "ASTRYX_SECRET_KEY" not in intro.load_env(env_path):
        print("✗ this org has no identity yet (ASTRYX_SECRET_KEY in .env): run `astryx init` first")
        return 1
    env = intro.load_env(env_path)
    me = env.get("ASTRYX_ORG", "?")

    if interactive:
        print(f"Federation: your org '{me}' can talk to other orgs (the internet of agents).\n")
        print("How should your org reach the internet of agents?")
        print(f"  1) Through the relay at {DEFAULT_RELAY[8:]}  (recommended for home networks;"
              " no port forwarding)")
        print("  2) My own public IP or domain, with port 8845 forwarded to this machine")
        print("  3) Not now")
        choice = ask("Choose 1, 2 or 3 [1]: ", "1")
        if choice == "1":
            a.relay = DEFAULT_RELAY
        elif choice == "2":
            a.public_url = ask("Your gateway's public URL (e.g. http://203.0.113.7:8845): ")
            if not a.public_url:
                print("No URL given; nothing changed.")
                return 1
        else:
            a.skip = True

    if a.skip:
        print("Federation skipped; nothing changed. Run `astryx federate` any time.")
        return 0

    if a.relay:
        relay = a.relay.rstrip("/")
        listed = not a.unlisted
        if interactive:
            listed = yes("List this org in the relay directory, so other orgs can find it by name?")
        set_env(env_path, {"ASTRYX_RELAY": relay, "ASTRYX_URL": "",
                           "ASTRYX_RELAY_LISTED": "1" if listed else "0"})
        print(f"✓ .env: ASTRYX_RELAY set to {relay}, ASTRYX_URL cleared (no port forwarding needed)")
    else:
        url = a.public_url.rstrip("/")
        relay = (a.relay_url or env.get("ASTRYX_RELAY") or DEFAULT_RELAY).rstrip("/")
        if not url.startswith(("http://", "https://")):
            print("✗ the URL must start with http:// or https://")
            return 1
        print(f"… asking the relay to reach {url} from outside")
        ok, why = check_reach(relay, url, _pubkey(env))
        print(("✓ " if ok else "✗ ") + why)
        if not ok:
            print(PORT_HELP)
            if not (a.force or (interactive and yes("Save this URL anyway?", default=False))):
                print("Nothing changed. Fix the forwarding and run `astryx federate` again.")
                return 2
        set_env(env_path, {"ASTRYX_URL": url, "ASTRYX_RELAY": ""})
        print(f"✓ .env: ASTRYX_URL set to {url}")

    print(f"  Restart the gateway so it takes effect:  {RESTART}")

    want = a.introduce
    if want is None:
        want = yes("Introduce your org to the founder's org (umairfiaz.com)?") if interactive else False
    if want:
        return do_introduce(relay, env_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
