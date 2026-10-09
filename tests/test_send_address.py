#!/usr/bin/env python3
"""Oracle for send's address check: nucleus/address.py (the authority) and channel/address.mjs (the seam
server.mjs calls before it writes a row). seed #37905's arms, plus the consumer pairing.

    venv/bin/python tests/test_send_address.py

  A. authority, on a TEMP agents/ tree (never the live roster):
     - a nickname is refused WITH its canonical name ("a3" → abstractor-3), a typo by edit distance;
     - every surface class passes; a malformed surface is refused, the wrong separator gets the dash form;
     - a charter added after the first check passes on the next call (read at call time, no restart);
     - name@<peer> is the gateway's (passes); name@local is judged here; an .example.md is not a resident;
       a malformed org ("seed@", "seed@local ") is refused rather than handed to federation.
  B. pairing: each surface class names a consumer file that really runs its predicate, and every
     to_agent predicate a bridge runs is admitted by some class. A new bridge class missing from
     SURFACES would make send refuse a deliverable name, and a class with no consumer would admit a
     dead letter; both go RED here.
  C. the JS seam, executed under node: a refusal THROWS with the suggestion (isError for the sender);
     a surface resolves; an unevaluable check ALLOWS with a visible note; a just-added charter passes
     on the next call (each call is a fresh python). No node → ○ NOT SEARCHED, exit 77 (partial).
  D. server.mjs's send awaits checkAddress BEFORE its INSERT, for local recipients only, on the SAME
     identifier it writes as to_agent (parity: the value judged is the value written, a3 #38028).
Exit 0 pass · 1 fail · 77 partial (C not searched).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _k in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_k]
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus import address  # noqa: E402

fails, skips = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


tmp = Path(tempfile.mkdtemp(prefix="sendaddr-"))
AG = tmp / "agents"
for rel in ("seed.md", "steward/steward.md", "abstractors/abstractor-3.md", "abstractors/abstractor-4.md",
            "painter.example.md"):
    (AG / rel).parent.mkdir(parents=True, exist_ok=True)
    (AG / rel).write_text(f"# {Path(rel).stem}\n")

try:
    print("A. the authority (temp agents/ tree):")
    ok, msg = address.check("a3", AG)
    check("a nickname is refused, naming the canonical resident", not ok and "did you mean abstractor-3?" in msg, msg)
    ok, msg = address.check("stewrd", AG)
    check("a typo is refused with the close name", not ok and "steward" in msg, msg)
    check("the refusal says nothing was sent", "nothing was sent" in msg, msg)
    for to in ("owner", "wa-923001234567", "tg-12345", "dc-998877", "cv-bob", "canvas-12"):
        ok, msg = address.check(to, AG)
        check(f"surface {to!r} passes ({address.surface_of(to)})", ok, msg)
    for to in ("canvas-x", "dc:123", "owners", "quasar"):
        check(f"{to!r} is refused", not address.check(to, AG)[0])
    check("the wrong separator suggests the dash form (dc:123 → dc-123)",
          "did you mean dc-123?" in address.check("dc:123", AG)[1], address.check("dc:123", AG)[1])
    check("an .example.md is not a resident", not address.check("painter", AG)[0])
    (AG / "painter.md").write_text("# painter\n")
    check("a charter added after the first check passes on the next call (no restart)",
          address.check("painter", AG)[0])
    check("name@<peer org> is the gateway's to judge → passes", address.check("anyone@peer.example", AG)[0])
    check("name@local is judged here", address.check("seed@local", AG)[0] and not address.check("a3@local", AG)[0])
    check("empty is refused", not address.check("", AG)[0])
    for to in ("seed@", "seed@local ", "seed@ peer.example", "seed@Peer"):    # a3 #38032: the ORG half too
        ok, msg = address.check(to, AG)
        check(f"a malformed org is refused, never handed to federation: {to!r}", not ok and "no such org" in msg, msg)
    for to in ("seed ", " seed", "seed\n", "abstractor-3 @local"):     # a3 #38028 A1: never normalized
        ok, msg = address.check(to, AG)
        check(f"whitespace is not normalized away: {to!r} is refused, suggesting the real name",
              not ok and ("seed" in msg or "abstractor-3" in msg), msg)

    print("\nB. surface classes ↔ the consumers that deliver them:")
    for cls, rx, consumer, pred in address.SURFACES:
        src = (REPO / consumer).read_text()
        check(f"{cls}: {consumer} runs {pred}", pred in src)
    run = set()
    for f in sorted((REPO / "bridges").glob("*.py")):
        src = f.read_text()
        run |= {("like", m) for m in re.findall(r"to_agent LIKE '([a-z]+-)%'", src)}
        run |= {("eq", m) for m in re.findall(r"to_agent='([a-z]+)'", src)}
    probe = {("like", p): f"{p}1" for _, p in run if _ == "like"} | {("eq", n): n for _, n in run if _ == "eq"}
    unadmitted = sorted(f"{k[1]}" for k, name in probe.items() if not address.surface_of(name))
    check(f"every to_agent class a bridge delivers is admitted ({len(run)} found)", run and not unadmitted,
          str(unadmitted))

    print("\nC. the JS seam (channel/address.mjs), executed:")
    node = shutil.which("node")
    if not node:
        print("  ○ NOT SEARCHED  node is not on PATH, so the seam was not executed")
        skips.append("JS seam")
    else:
        shim = tmp / "addr_under_test.py"           # the REAL authority, pointed at the temp tree by argument
        shim.write_text("import sys\nsys.path.insert(0, %r)\nfrom pathlib import Path\nfrom nucleus import address\n"
                        "ok, msg = address.check(sys.argv[1], Path(%r))\nprint(msg)\nsys.exit(0 if ok else 2)\n"
                        % (str(REPO), str(AG)))
        js = ("import { checkAddress } from %s;\n"
              "const o = { py: %s, addr: %s };\n"
              "const r = {};\n"
              "try { await checkAddress('a3', o); r.a3 = 'resolved' } catch (e) { r.a3 = 'threw: ' + e.message }\n"
              "try { await checkAddress('seed ', o); r.ws = 'resolved' } catch (e) { r.ws = 'threw' }\n"
              "r.owner = await checkAddress('owner', o);\n"
              "r.broken = await checkAddress('a3', { py: '/nonexistent/python', addr: o.addr });\n"
              "try { await checkAddress('newcomer', o); r.before = 'resolved' } catch (e) { r.before = 'threw' }\n"
              "(await import('node:fs')).writeFileSync(%s, '# newcomer\\n');\n"
              "r.after = await checkAddress('newcomer', o);\n"
              "console.log(JSON.stringify(r));\n") % (
            json.dumps((REPO / "channel" / "address.mjs").as_uri()), json.dumps(sys.executable),
            json.dumps(str(shim)), json.dumps(str(AG / "newcomer.md")))
        p = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
        try:
            r = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            r = {}
            check("the seam ran", False, (p.stdout + p.stderr)[-400:])
        if r:
            check("a refusal THROWS with the suggestion (the sender's isError)",
                  r["a3"].startswith("threw:") and "did you mean abstractor-3?" in r["a3"], r["a3"])
            check("a surface resolves with no note", r["owner"] == {"ok": True, "note": ""}, str(r["owner"]))
            check("'seed ' THROWS through the seam too (nothing normalizes it on the way)", r["ws"] == "threw", r["ws"])
            check("an unevaluable check ALLOWS, with a visible note (never mutes the org)",
                  r["broken"]["ok"] and "address unchecked" in r["broken"]["note"], str(r["broken"]))
            check("a charter added mid-session: refused before, passes after, same ear",
                  r["before"] == "threw" and r["after"]["ok"], f"{r['before']} / {r['after']}")

    print("\nD. server.mjs wiring:")
    srv = (REPO / "channel" / "server.mjs").read_text()
    send = srv[srv.index("if (name === 'send')"):srv.index("if (name === 'subscribe')")]
    check("send awaits checkAddress before its INSERT",
          "await checkAddress(" in send and send.index("await checkAddress(") < send.index("INSERT INTO messages"))
    check("...EVERY send is judged: a local row by its to_agent, any other by the (to_agent, to_org) as written",
          "await checkAddress(toOrg === 'local' ? toAgent : `${toAgent}@${toOrg}`)" in send)
    # PARITY (a3 #38028): the value checked is byte-identical to the to_agent the INSERT writes. Both must be
    # the SAME identifier, bound once from the split and never reassigned in between.
    arg = re.search(r"await checkAddress\(toOrg === 'local' \? (\w+) :", send)
    ins = re.search(r"INSERT INTO messages \(from_agent, from_org, to_agent[^`]*`,\s*\[AGENT, (\w+), (\w+),", send)
    between = send[send.index("await checkAddress("):send.index("INSERT INTO messages")]
    check("parity: send checks the exact identifier it INSERTs as to_agent, unreassigned in between",
          arg and ins and arg.group(1) == ins.group(1) and ins.group(2) == "toOrg"
          and "`${" + ins.group(1) + "}@${toOrg}`" in send
          and not re.search(rf"\b{arg.group(1)}\s*=[^=]", between),
          f"checked={arg and arg.group(1)} inserted={ins and ins.group(1)}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if fails:
    print(f"\nFAIL: {len(fails)} arm(s)")
    sys.exit(1)
if skips:
    print(f"\nSKIP (partial): {', '.join(skips)}, the other arms passed")
    sys.exit(77)
print("\nALL PASS")
