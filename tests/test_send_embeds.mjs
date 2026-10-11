#!/usr/bin/env node
// send's embed check (channel/embeds.mjs, wired in channel/server.mjs). Pure: writes only a scratch dir.
// Three parts: the rules; PARITY with the bridges' own grammar (bridges/common.py split_polls/split_files, pulled out
// by ast and run under stdlib python, so no venv is needed); and the WIRING in server.mjs.
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, relative } from 'node:path'
import { execFileSync } from 'node:child_process'
import { embedProblems } from '../channel/embeds.mjs'

let fails = 0
const arm = (n, ok) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${n}`); if (!ok) fails++ }
const root = mkdtempSync(join(tmpdir(), 'embeds-'))
const real = join(root, 'shot.jpeg'); writeFileSync(real, 'x')

const OK = [
  'plain text, no embeds',
  'Pick one [[poll: Send? | Yes | No]]',
  'multi [[poll: Which? | a | b | c | multi=2]]',
  `see [[file:${real}]] and [[poll: Go? | Go | Wait]]`,
  `ten [[poll: Q | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10]]`,
]
// the two real misses (10-10 msg 42289, 10-11 msg 49126) end exactly like the first two rows
const BAD = [
  ['unclosed poll at the end (the real miss)', `text\n[[poll: Submit the application as shown? | Submit | Hold, I'll edit`],
  ['unclosed poll before a file embed', `[[poll: Q | a | b  [[file:${real}]]`],
  ['unclosed file', `[[file:${real}`],
  ['poll with one option', '[[poll: Q | only]]'],
  ['poll with multi= but one option', '[[poll: Q | only | multi=2]]'],
  ['poll with no options', '[[poll: just a question]]'],
  ['poll with 11 options', '[[poll: Q | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11]]'],
  ['relative file path (to a file that exists from the cwd)', `[[file:${relative(process.cwd(), real)}]]`],
  ['missing file', `[[file:${join(root, 'nope.pdf')}]]`],
  ['directory, not a file', `[[file:${root}]]`],
]
for (const b of OK) arm(`accepted: ${JSON.stringify(b.slice(0, 50))}`, embedProblems(b).length === 0)
for (const [n, b] of BAD) arm(`refused: ${n}`, embedProblems(b).length > 0)
arm('the refusal names what to fix', /closing "\]\]"/.test(embedProblems(BAD[0][1])[0] || ''))

// PARITY: every accepted body renders exactly its polls/files under the bridge grammar, with nothing left in the text
// that looks like an embed; every refused POLL body renders either no poll or a truncated one.
const py = `
import ast, json, re, sys
from pathlib import Path
src = open(sys.argv[1]).read()
tree = ast.parse(src)
keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in ('split_files', 'split_polls'))
        or (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'POLL_RE' for t in n.targets))]
ns = {'re': re, 'Path': Path}
exec(compile(ast.Module(body=keep, type_ignores=[]), 'grammar', 'exec'), ns)
out = []
for body in json.loads(sys.argv[2]):
    text, files = ns['split_files'](body)
    text, polls = ns['split_polls'](text, max_options=10)
    out.append({'text': text, 'files': files, 'polls': [[q, o] for q, o, _ in polls]})
print(json.dumps(out))
`
const common = new URL('../bridges/common.py', import.meta.url).pathname
const rendered = (bodies) => JSON.parse(execFileSync('python3', ['-I', '-c', py, common, JSON.stringify(bodies)], { encoding: 'utf8' }))
const okR = rendered(OK)
arm('parity: accepted bodies leave no embed syntax in the text', okR.every((r) => !/\[\[(poll|file):/.test(r.text)))
arm('parity: accepted bodies yield the expected poll/file counts', JSON.stringify(okR.map((r) => [r.polls.length, r.files.length])) === '[[0,0],[1,0],[1,0],[1,1],[1,0]]')
arm('parity: the 10-option poll keeps all 10', okR[4].polls[0][1].length === 10)
const badPolls = rendered(BAD.slice(0, 7).map(([, b]) => b))
arm('parity: unclosed poll renders NO poll and leaves raw brackets (the bug)', badPolls[0].polls.length === 0 && badPolls[0].text.includes('[[poll:'))
arm('parity: a one-option poll is silently dropped AND stripped from the text', badPolls[3].polls.length === 0 && !badPolls[3].text.includes('Q'))
arm('parity: an 11-option poll is silently truncated to 10', badPolls[6].polls[0][1].length === 10)

// WIRING: in server.mjs's send branch the check is gated on channelBound, returns before the INSERT, and says so.
const src = readFileSync(new URL('../channel/server.mjs', import.meta.url), 'utf8')
const s0 = src.indexOf("if (name === 'send')"), s1 = src.indexOf("if (name === 'subscribe')")
const send = src.slice(s0, s1)
const chk = send.indexOf('embedProblems(a.body)'), ins = send.indexOf('INSERT INTO messages')
arm('server.mjs: send calls embedProblems(a.body)', chk > 0)
arm('server.mjs: the check runs before the INSERT', chk > 0 && chk < ins)
arm('server.mjs: the check is inside `if (channelBound)`', /if \(channelBound\) \{\n(?:(?!\n    \}).)*embedProblems\(a\.body\)/s.test(send))
arm('server.mjs: channelBound is defined before the check', send.indexOf('const channelBound') > 0 && send.indexOf('const channelBound') < chk)
arm('server.mjs: a refusal returns "nothing sent"', /send REFUSED, nothing sent/.test(send))
rmSync(root, { recursive: true, force: true })
console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
