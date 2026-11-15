// Code in an answer (owner 11-15): fenced blocks draw as code; SQL pasted without a fence is fenced first.
// Called by tests/test_chat_code.py:  node tests/chat_code_test.ts
import { codeBlock, fenceBareSql } from '../observatory/web/src/chat/thread/code.ts'

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
arm('codeBlock: language on the bar, a Copy button, the text escaped', html.includes('ws-code-lang">sql<') && html.includes('data-copy="1"')
  && html.includes('SELECT a &lt;b&gt; &amp; &quot;c&quot;</code>') && !html.includes('<b>'), html)
arm('codeBlock: no language reads "code"; a hostile one is reduced', codeBlock('x', '').includes('>code<') && !codeBlock('x', '"><script>').includes('<script'), codeBlock('x', '"><script>'))

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
