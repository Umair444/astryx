// The chat's calculator (owner 11-15): boxes in the composer's text, LaTeX for Qalculate, only the answer is sent.
// Called by tests/test_chat_calc.py:  node tests/chat_calc_test.ts
import { calcAt, latexToQalc, openCalc, sendText, setResult, splitCalc } from '../observatory/web/src/chat/thread/calc.ts'

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        ${JSON.stringify(got)}`}`); if (!ok) fails++ }

const o1 = openCalc('= ', 2)
arm('"= " at the start opens a box, the caret inside it', !!o1 && o1.text === '⟦⟧' && o1.caret === 1, o1)
const o2 = openCalc('price is = ', 11)
arm('"= " after a space opens one mid-line', !!o2 && o2.text === 'price is ⟦⟧' && o2.caret === 10, o2)
arm('"a = " inside a word stays text ("x= " never opens)', openCalc('x= ', 3) === null)
arm('"==" or "=" alone never opens', openCalc('a == b', 4) === null && openCalc('=', 1) === null)
arm('"= " typed INSIDE a box is the box\'s text', openCalc('⟦x = ⟧', 5) === null)
const t = 'total ⟦10 usd to pkr⟧ please'
const b = calcAt(t, 10)
arm('the caret inside a box finds it', !!b && b.inner === '10 usd to pkr', b)
arm('outside a box finds nothing', calcAt(t, 3) === null && calcAt(t, t.length) === null)
const r = setResult(t, b!, 'PKR 2815.44')
arm('Enter writes "expression = answer" in the box, the caret after it',
  r.text === 'total ⟦10 usd to pkr = PKR 2815.44⟧ please' && r.caret === 'total ⟦10 usd to pkr = PKR 2815.44⟧'.length, r)
const again = setResult(r.text, calcAt(r.text, 9)!, 'PKR 2900')
arm('editing and pressing Enter again replaces the answer, never stacks it', again.text === 'total ⟦10 usd to pkr = PKR 2900⟧ please', again)
arm('splitCalc reads expression and answer', JSON.stringify(splitCalc('2+3 = 5')) === JSON.stringify({ expr: '2+3', result: '5' }))
const s1 = sendText('cost ⟦10 usd to pkr = PKR 2815.44⟧ and ⟦2+2 = 4⟧.')
arm('ONLY the answer is sent (owner: "only the answer goes to the agent")', s1.text === 'cost PKR 2815.44 and 4.' && !s1.pending.length, s1)
const s2 = sendText('then ⟦5*5⟧')
arm('a box with no answer yet is listed for the composer to evaluate first', s2.pending.length === 1 && s2.pending[0] === '5*5', s2)
arm('no box: the text goes as typed', sendText('a = b').text === 'a = b')
arm('LaTeX: fractions, roots, powers, operators, constants',
  latexToQalc('\\frac{1}{2} + \\sqrt{16} \\cdot 2^{3} - \\pi') === '((1)/(2)) + sqrt(16) * 2^(3) - pi', latexToQalc('\\frac{1}{2} + \\sqrt{16} \\cdot 2^{3} - \\pi'))
arm('LaTeX: nested fractions and an nth root', latexToQalc('\\frac{\\frac{1}{2}}{3}') === '((((1)/(2)))/(3))' && latexToQalc('\\sqrt[3]{27}') === 'root(27, 3)', [latexToQalc('\\frac{\\frac{1}{2}}{3}'), latexToQalc('\\sqrt[3]{27}')])
arm('plain Qalculate passes through untouched', latexToQalc('10 usd to pkr') === '10 usd to pkr')

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
