// Rich copy (owner 11-15: an email copied out of a reply landed in Outlook as asterisks and pipes). Called by
// tests/test_chat_clip.py:  node tests/chat_clip_test.ts
import { clipPlain, styled } from '../observatory/web/src/chat/thread/clip.ts'

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        ${JSON.stringify(got)}`}`); if (!ok) fails++ }

const mail = '**Subject:** Kafka topic gap\n\nDear team,\n\nWe found *two* gaps in `cps2`; see [the report](https://example.invalid/r).\n\n## Counts\n\n```sql\nSELECT 1\n```'
const p = clipPlain(mail)
arm('the plain form has no emphasis, heading or inline-code marks', !/\*\*|^##|`cps2`/m.test(p) && p.startsWith('Subject: Kafka topic gap'), p)
arm('...a link reads "text (url)", a fence keeps its code without the backticks', p.includes('the report (https://example.invalid/r)') && p.includes('SELECT 1') && !p.includes('```'), p)
arm('...words with asterisks inside them stay (2*3*4)', clipPlain('2*3*4 is 24') === '2*3*4 is 24', clipPlain('2*3*4 is 24'))
const h = styled('<table><thead><tr><th>Type</th></tr></thead><tbody><tr><td align="right">5,420</td></tr></tbody></table><pre><code>x</code></pre>')
arm('the html form carries inline table borders (a mail client drops stylesheets)', /<table style="border-collapse:collapse/.test(h) && /<th style="[^"]*border:1px[^"]*font-weight:600/.test(h), h)
arm('...a cell keeps its own attributes', /<td align="right" style="border:1px/.test(h), h)
arm('...and code is a shaded pre', /<pre style="background/.test(h), h)

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
