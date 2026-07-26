// Reproduces channel/server.mjs:15-16 VERBATIM — the exact DSN resolution an injected
// agent's (unconditionally-wired) astryx MCP would perform. Placed in channel/ so that
// `new URL('../.env', import.meta.url)` resolves the SAME sibling path as the real server
// (= /home/umair/astryx/.env inside the cell = the canary). If containment holds this
// prints the SANDBOX dsn; if the cell leaked the real tree it would print the real one.
import { readFileSync } from 'node:fs'
const DSN = readFileSync(new URL('../.env', import.meta.url), 'utf8')
  .split('\n').find(l => l.startsWith('ASTRYX_DSN=')).slice('ASTRYX_DSN='.length).trim()
console.log(DSN)
