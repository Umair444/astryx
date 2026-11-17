#!/usr/bin/env python3
"""Oracle: the mid-task line (owner 11-18, 13133; homes/seed/progress-requests/DESIGN.md). A person's message from
another chat while the agent is mid-turn on other work goes straight in, with one line telling the agent its choice:
a helper bound by msg_id for an urgent short ask, else finish first and send that chat 'on it'. channel/midtask.mjs,
executed under node against a recording pool.

  M1 busy on another chat's request: the line, naming this message's id
  M2 idle (its newest step is a turn end, or none in 15 min): no line
  M3 the same chat writing again while busy on it: no line (the same work)
  M4 busy on work of unknown scope: the line (it is mid-task on something)
  M5 not a person (an agent's message): no line; a member (a role) and a channel person are people
  M6 the database can't be read: no line, never a throw
  M7 the line carries no double quote (it rides in a tag attribute), and server.mjs stamps it as the `mid_task`
     attribute, never into the content (medic 13157)
Exit 0 · 1 · 77 (no node)."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


JS = r"""
import { midTask } from %(mod)s
const pool = (step, sameThread, broken) => ({
  async query(sql, args) {
    if (broken) throw new Error('db down')
    if (sql.includes('FROM steps')) return { rows: step ? [step] : [] }
    if (sql.includes('FROM messages')) return { rows: sameThread ? [{ '?column?': 1 }] : [] }
    return { rows: [] }
  },
})
const owner = { id: 900, from_agent: 'owner', from_org: 'whatsapp', thread: 'wa:B' }
const tool = { kind: 'tool', meta: { turn_msgs: [800] } }
const out = {
  m1: await midTask(owner, { pool: pool(tool, false), agent: 'seed' }),
  m2a: await midTask(owner, { pool: pool({ kind: 'response', meta: {} }, false), agent: 'seed' }),
  m2b: await midTask(owner, { pool: pool(null, false), agent: 'seed' }),
  m3: await midTask(owner, { pool: pool(tool, true), agent: 'seed' }),
  m4: await midTask(owner, { pool: pool({ kind: 'tool', meta: {} }, false), agent: 'seed' }),
  m5agent: await midTask({ id: 901, from_agent: 'db', from_org: 'local', thread: 't-x' }, { pool: pool(tool, false), agent: 'seed' }),
  m5wa: await midTask({ id: 902, from_agent: 'wa-923000000000', from_org: 'whatsapp', thread: 'wa:C' }, { pool: pool(tool, false), agent: 'seed' }),
  m6: await midTask(owner, { pool: pool(tool, false, true), agent: 'seed' }),
}
console.log(JSON.stringify(out))
"""


def main() -> int:
    if not shutil.which("node"):
        print("  SKIP  node is not installed")
        return 77
    js = JS % {"mod": json.dumps(str(REPO / "channel" / "midtask.mjs"))}
    p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
    if p.returncode:
        print(p.stderr[-800:])
        return 1
    o = json.loads(p.stdout.strip().splitlines()[-1])
    arm("M1 busy on another chat's request: the line, naming this message's id", bool(o["m1"]) and "msg_id=900" in o["m1"]
        and "helper" in o["m1"] and "on it" in o["m1"], o["m1"])
    arm("M2 idle (a turn end, or no step in 15 min): no line", o["m2a"] is None and o["m2b"] is None, (o["m2a"], o["m2b"]))
    arm("M3 the same chat writing again while busy on it: no line", o["m3"] is None, o["m3"])
    arm("M4 busy on work of unknown scope: the line", bool(o["m4"]), o["m4"])
    arm("M5 an agent's message gets no line; a channel person does", o["m5agent"] is None and bool(o["m5wa"]),
        (o["m5agent"], o["m5wa"]))
    arm("M6 the database can't be read: no line, never a throw", o["m6"] is None, o["m6"])
    arm("M7 the line carries no double quote (it is a tag attribute)", '"' not in (o["m1"] or ""), o["m1"])
    src = (REPO / "channel" / "server.mjs").read_text()
    push = src[src.index("async function pushMessage(row)"):src.index("async function deliverMessage(id)")]
    arm("M7 server.mjs stamps it as the mid_task attribute, never into the content",
        "mid_task: busy" in push and not re.search(r"content\s*=.*busy", push), push[-400:])
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the mid-task line")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
