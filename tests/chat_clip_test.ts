// Rich copy (owner 11-15: an email copied out of a reply landed in Outlook as asterisks and pipes). Called by
// tests/test_chat_clip.py:  node tests/chat_clip_test.ts
import { clipMarkup, clipPlain, styled } from '../observatory/web/src/chat/thread/clip.ts'
import { cardData, deliverableBlock, deliverableName, kindOf, parseDeliverable } from '../observatory/web/src/chat/thread/deliverable.ts'

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

// medic 12241: P1–P4, the plain form from marked's own parse: code and identifiers byte-exact
arm('P1 a fence keeps its code byte-exact (x**2, __init__, **kw)', clipPlain('```python\ny = x**2 + z**2\ndef __init__(self, **kw):\n```').includes('y = x**2 + z**2\ndef __init__(self, **kw):'), clipPlain('```python\ny = x**2 + z**2\ndef __init__(self, **kw):\n```'))
arm('P2 a code span keeps its text', clipPlain('`a**b**c` and `__main__`') === 'a**b**c and __main__', clipPlain('`a**b**c` and `__main__`'))
arm('P3 an identifier with __ inside it is not emphasis', clipPlain('my_db__stage__x and snake__case__name') === 'my_db__stage__x and snake__case__name', clipPlain('my_db__stage__x and snake__case__name'))
arm('P4 a "# comment" inside a fence stays a comment', clipPlain('```sql\n# not a heading\nSELECT 1\n```').startsWith('# not a heading'), clipPlain('```sql\n# not a heading\nSELECT 1\n```'))
arm('a table is tab-separated rows, a list "- " lines', clipPlain('| a | b |\n|---|---|\n| 1 | 2 |\n\n- x\n- y') === 'a\tb\n1\t2\n\n- x\n- y', clipPlain('| a | b |\n|---|---|\n| 1 | 2 |\n\n- x\n- y'))
arm('the html form fences bare SQL as the page does, no stray emphasis (medic 12241 b)', !clipMarkup('SELECT a*b,\n       c*d\nFROM t').includes('<em>'), clipMarkup('SELECT a*b,\n       c*d\nFROM t'))

// DELIVERABLES (owner 11-15: "it should be general"): a fence named for its kind is a card, any other fence is code
arm('a deliverable kind is known by its fence; code languages are not', kindOf('email') === 'email' && kindOf('HTML') === 'html' && kindOf('python') === null && kindOf('') === null)
const em = parseDeliverable('**Subject:** Kafka gap – 15 Nov\n\nDear team,\n\nCounts below.', 'email')
arm("an email's subject is its title and leaves the body", em.subject === 'Kafka gap – 15 Nov' && em.body.startsWith('Dear team,'), em)
arm("a document's first heading is its title", parseDeliverable('# Q4 review\n\ntext', 'doc').title === 'Q4 review')
arm('the file name is the title, safe, with the kind\'s extension', deliverableName('Kafka gap – 15 Nov', 'email') === 'kafka-gap-15-nov.md' && deliverableName('<x>', 'html') === 'x.html')
const card = deliverableBlock('Subject: <img src=x onerror=1>\n\nHi <b>there</b>', 'email', (m) => `<p>${m}</p>`, 'id-1')
arm("the card escapes the agent's subject in its title", !card.includes('<img src=x') && card.includes('&lt;img src=x'), card)
arm('the card carries only its render id, never its source (medic 12245 F1: raw HTML could forge a card)',
  card.includes('data-dl-id="id-1"') && !/data-(src|subject|name)=/.test(card), card)
const cd = cardData('Subject: Gap\n\nDear team,', 'email')
arm("what a card's buttons act on comes from cardData, kept out of the page", cd.src === 'Dear team,' && cd.subject === 'Gap' && cd.name === 'gap.md' && cd.kind === 'email', cd)
arm('a short email gets a Mail link with its subject; a long one does not (mail clients cut the body)',
  card.includes('href="mailto:?subject=') && !deliverableBlock('Subject: s\n\n' + 'x'.repeat(2000), 'email', (m) => m, 'i').includes('mailto:'))
arm('HTML shows as its source (code), never rendered on this page', deliverableBlock('<h1>Hi</h1>', 'html', (m) => m, 'i').includes('class="ws-cb"'))

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
