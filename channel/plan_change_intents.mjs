// The JS reader of nucleus/plan_change_intents (plan_quorum). Its own module so tests/test_plan_lifecycle.py
// can EXECUTE it against the Python reader (triggers/seed/plan_consensus.py change_intents()), not just grep it
// (a1 #30442). The two readers share ONE grammar, stated here and there identically:
//   a leading BOM is dropped; lines split on \n; each line is stripped of [ \t\r]; a blank line or one starting
//   with '#' is skipped; EVERY other line must be a bare intent ^[a-z_]+$, else THROW naming the line.
//   The set must contain 'revise', else THROW.
// Loud on anything else: an inline comment ("design  # note") would otherwise become the token
// "design  # note", silently drop 'design', and bring back the plan-4918 defect with no sound.
import { readFileSync } from 'node:fs'

export function changeIntents(path) {
  const text = readFileSync(path, 'utf8').replace(/^﻿/, '')
  const out = []
  text.split('\n').forEach((raw, i) => {
    const l = raw.replace(/^[ \t\r]+|[ \t\r]+$/g, '')
    if (!l || l.startsWith('#')) return
    if (!/^[a-z_]+$/.test(l)) throw new Error(`${path}:${i + 1}: ${JSON.stringify(l)} is not a bare intent`)
    out.push(l)
  })
  if (!out.includes('revise')) throw new Error(`${path} lists no revise`)
  return out
}
