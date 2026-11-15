// Code in an answer (owner 11-15): fenced blocks draw as code; SQL pasted without a fence is fenced first.
// Called by tests/test_chat_code.py:  node tests/chat_code_test.ts
import { codeBlock, codeLang, expandPasteTokens, fenceBareCode, fenceBareSql, fencePaste, pasteToken } from '../observatory/web/src/chat/thread/code.ts'

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        ${JSON.stringify(got)}`}`); if (!ok) fails++ }

// the 12138 shape: a label line, then SQL with COUNT(*) and indentation, then a second query
const two = [
  'Here are both queries.', '', 'ORACLE (l):',
  'SELECT TRUNC(send_ts) AS bucket,', '       COUNT(*) AS receipts,', '       SUM(amt) AS amount',
  'FROM (', '    SELECT receipt_no FROM t', ') x', 'GROUP BY 1', '',
  'CLICKHOUSE (c360):', 'SELECT toStartOfFiveMinutes(ts) AS b, count() AS n', 'FROM k', 'GROUP BY b', '', 'Run them without a ";".',
].join('\n')
const f = fenceBareSql(two)
const blocks = f.split('```sql').length - 1
arm('two pasted queries become two sql fences', blocks === 2, f)
arm('...the label lines and the closing note stay prose', f.includes('ORACLE (l):\n```sql') && f.includes('```\n\nRun them') && f.startsWith('Here are both'), f)
arm('...indentation inside is kept', f.includes('       COUNT(*) AS receipts,'), f)
arm('a blank line inside a statement, before a clause, keeps one fence',
  fenceBareSql('SELECT a\nFROM t\n\nWHERE a > 1\nORDER BY a').split('```').length === 3)
arm('prose that says "select … from" is never code', fenceBareSql('Select the rows from the table, then sum them.') === 'Select the rows from the table, then sum them.')
arm('a one-line keyword without FROM is left alone', fenceBareSql('SELECT is the verb here.\nAnd more text.') === 'SELECT is the verb here.\nAnd more text.')
const fenced = '```sql\nSELECT 1\nFROM t\n```'
arm('an already fenced block is untouched', fenceBareSql(fenced) === fenced)
arm('python in a fence is untouched too', fenceBareSql('```py\nSELECT = 1\nx FROM y\n```') === '```py\nSELECT = 1\nx FROM y\n```')
const html = codeBlock('SELECT a <b> & "c"\n', 'sql extra')
arm('codeBlock: language on the bar, a Copy button, the text escaped', html.includes('ws-cb-lang">sql<') && html.includes('data-copy="1"')
  && html.includes('SELECT a &lt;b&gt; &amp; &quot;c&quot;</code>') && !html.includes('<b>'), html)
arm('codeBlock: no language reads "code"; a hostile one is reduced', codeBlock('x', '').includes('>code<') && !codeBlock('x', '"><script>').includes('<script'), codeBlock('x', '"><script>'))

// ── a human's own words: any code, detected (owner 11-15: "queries and code can be detected programmatically")
const py = 'import pandas as pd\n\ndef load(path):\n    df = pd.read_csv(path)\n    return df[df.amount > 0]\n\nprint(load("x.csv"))'
arm('python is python', codeLang('def load(path):\n    df = pd.read_csv(path)\n    return df') === 'python')
arm('a JSON object is json', codeLang('{\n  "a": 1,\n  "b": [2, 3]\n}') === 'json')
arm('shell commands are bash', codeLang('cd /opt/astryx\ngit pull\nnpm run build') === 'bash')
arm('javascript is javascript', codeLang('const x = await fetch(url);\nconst j = await x.json();\nconsole.log(j);') === 'javascript')
arm('a list is words, never code', codeLang('- check the za space\n- drop the May tables\n- tell Faran') === null)
arm('sentences are words, never code', codeLang('Please check the dashboard.\nIt failed again today.\nThanks.') === null)
arm('one line is never code', codeLang('x = 1') === null)
const mixed = fenceBareCode(`can you check this?\n\n${py}\n\nthanks`)
arm('a pasted function in a message: one python fence across its blank lines, the words outside it',
  mixed.startsWith('can you check this?\n\n```python\nimport pandas') && mixed.split('```').length === 3 && mixed.endsWith('```\n\nthanks'), mixed)
arm('a human fence is left as written', fenceBareCode('```\nanything\n```') === '```\nanything\n```')
arm('a pasted query is fenced sql in a human message too', fenceBareCode('SELECT a\nFROM t\nWHERE b = 1').startsWith('```sql'))
arm('fencePaste: code goes fenced with its language', fencePaste('SELECT a\nFROM t') === '```sql\nSELECT a\nFROM t\n```')
arm('fencePaste: prose goes as pasted', fencePaste('a long note\nthat is just words.') === 'a long note\nthat is just words.')
const pastes = new Map([[1, 'SELECT a\nFROM t'], [2, 'just words here.\nmore words.']])
const out = expandPasteTokens(`look at ${pasteToken(1, 2)} and ${pasteToken(2, 2)} and ${pasteToken(9, 40)}`, pastes)
arm('expand: each token becomes its paste (code fenced), an unknown token stays as it reads',
  out.includes('\n```sql\nSELECT a\nFROM t\n```\n') && out.includes('\njust words here.\nmore words.\n') && out.includes('[Pasted text #9 +40 lines]'), out)

const asked = fenceBareCode('why are partner names missing here\n<div class="card" id="bnpl">\n  <div class="chead"><h3>BNPL</h3></div>\n  <span class="k"><b>Rs 1M</b></span>\n</div>')
arm('a question on the line above pasted code stays words, the code below it is the block',
  asked.startsWith('why are partner names missing here\n```') && asked.split('```').length === 3, asked)

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
