// The draft, drawn (owner 11-16): the composer's markdown read while it is typed. Run: node tests/chat_draft_test.ts
import { blocks, drawn, spans } from '../observatory/web/src/chat/thread/draft.ts'

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        ${JSON.stringify(got)}`}`); if (!ok) fails++ }
const J = (x: unknown) => JSON.stringify(x)

const texts = ['', 'a', 'a\n', '```', '```sql\nselect 1\n```', 'hi\n```sql\nselect *\nfrom t\n```\nbye', 'x\n\n```\na\n```\n\n```\nb\n```\n', '```py\nprint(1)\n', 'a ```b``` c', '````\n```\n````']
arm('blocks are whole lines: joined by \\n they are the text again, for every shape', texts.every((t) => blocks(t).map((b) => b.text).join('\n') === t), texts.map((t) => blocks(t)))
arm('a closed fence is its own block, the prose around it another',
  J(blocks('hi\n```sql\nselect *\n```\nbye')) === J([{ fence: false, text: 'hi' }, { fence: true, text: '```sql\nselect *\n```' }, { fence: false, text: 'bye' }]), blocks('hi\n```sql\nselect *\n```\nbye'))
arm('a fence still being typed runs to the end (the box appears at ```, not at Enter)',
  J(blocks('see\n```sql\nselect')) === J([{ fence: false, text: 'see' }, { fence: true, text: '```sql\nselect' }]) && blocks('```')[0].fence, blocks('see\n```sql\nselect'))
arm('a shorter run of backticks inside a longer fence does not close it', blocks('````\n```\n````').length === 1)
arm('``` mid-line is not a fence', !blocks('a ```b``` c')[0].fence)
const sp = spans('# Head\nsum ⟦2+2 = 4⟧ and `x` is **big**')
arm('spans: heading, calc box, code, strong, text in between', J(sp.map((s) => s.kind)) === J(['head', 'text', 'calc', 'text', 'code', 'text', 'strong']), sp)
arm('spans cover the text exactly', sp.map((s) => s.text).join('') === '# Head\nsum ⟦2+2 = 4⟧ and `x` is **big**')
arm('2 * 3 * 4 and a lone ` are text', spans('2 * 3 * 4 `').every((s) => s.kind === 'text'))
arm('drawn: only when something shows', !drawn('plain words') && drawn('`x`') && drawn('```') && drawn('⟦1+1⟧') && !drawn('#hashtag'))
console.log(fails ? `${fails} FAIL` : "ALL PASS")
process.exit(fails ? 1 : 0)
