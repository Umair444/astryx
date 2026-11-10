// The chat's table → chart logic (observatory/web/src/chat/tables), run by tests/test_chat_tables.py (esbuild + node).
// Pure functions only: the caption/scale parser, number reading, the form picker, the formatting rule.
import { parseNum, scaleOf } from '../../observatory/web/src/chat/tables/infer'
import { analyse, build } from '../../observatory/web/src/chat/tables/pick'
import { exact, fmtValue } from '../../observatory/web/src/chat/tables/format'
import { tableName, tablesOf } from '../../observatory/web/src/chat/tables/mdtable'
import { toCsv } from '../../observatory/web/src/chat/tables/files'

let fails = 0
const arm = (name: string, got: unknown, want: unknown) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) fails++
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`)
}

console.log('caption scale')
const FIN = 'Finance summary, Aug vs Jul 2026 (PKR mn, provisional: both months are still open):'
arm('the finance caption names PKR mn', scaleOf(FIN), 'PKR mn')
arm('Rs M', scaleOf('FPF revenue (za d_dfs.financial_product_fact), Rs M:'), 'Rs M')
arm('USD bn', scaleOf('Volume in USD bn'), 'USD bn')
arm('a header (k)', scaleOf('Revenue (k)'), 'k')
arm('millions', scaleOf('GMV, millions'), 'millions')
arm("'000", scaleOf("Users ('000)"), "'000")
arm('a sheet title', scaleOf('product_margin_rank_2026-08 · Ranking (PKR mn)'), 'PKR mn')
arm('5k users is not a scale', scaleOf('about 5k users joined'), '')
arm('a word with mn inside is not a scale', scaleOf('Column mnemonic'), '')
arm('no scale', scaleOf('Revenue by region'), '')

console.log('table names from a turn')
const md = (cap: string) => tablesOf(`${cap}\n\n| | Jul | Aug |\n|---|---|---|\n| Revenue | 11,521.2 | 11,289.5 |\n| Cost | 5,821.4 | 6,005.5 |\n`)[0]
const fin = md(FIN)
arm('the finance table keeps its scale as a clean suffix', tableName(fin, '', 1, 1), 'Finance summary Aug vs Jul 2026 (PKR mn).csv')
arm('a long caption still keeps the scale', scaleOf(tableName(md('Monthly revenue by every single product line we track across the whole estate this year (PKR mn):'), '', 1, 1)), 'PKR mn')
arm('Rs M caption', tableName(md('FPF revenue (za d_dfs.financial_product_fact), Rs M:'), '', 1, 1), 'FPF revenue (Rs M).csv')
arm('no scale, no suffix', tableName(md('Orders by region:'), '', 1, 1), 'Orders by region.csv')

console.log('the chart of the finance table')
const rows = fin.rows
const a = analyse(rows[0], rows.slice(1))
arm('grouped bars of Jul and Aug', a.spec, { kind: 'bar', x: 0, series: [1, 2], split: null })
const p = build(a.spec!, a.cols, rows.slice(1))
arm('under 100,000 with no scale named: written out, never K', [fmtValue(12000, p.fmt), fmtValue(2000, p.fmt), exact(11521.2, p.fmt)], ['12,000', '2,000', '11,521.2'])
arm('a scaled column is written as is', fmtValue(11521.2, { scaled: true }), '11,521')
arm('genuinely large raw numbers still compact', fmtValue(12_400_000, { full: false }), '12.4M')
const big = [['Region', 'Amount'], ['North', '12400000'], ['South', '9800000']]
const ab = analyse(big[0], big.slice(1)); const pb = build(ab.spec!, ab.cols, big.slice(1))
arm('large table: not full', pb.fmt.full, false)
arm('small table: full', p.fmt.full, true)

console.log('numbers')
arm('true minus, footnote star', [parseNum('−31.5% *'), parseNum('+8.7%')], [-31.5, 8.7])
arm('a figure with an aside', parseNum('5,699.8 (49.5%)'), 5699.8)
arm('codes are not numbers', [parseNum('A1'), parseNum('W4')], [null, null])
arm('csv guards formulas, keeps negatives', toCsv([['=1+1', '-5']]), "'=1+1,-5\r\n")

console.log(fails ? `FAIL: ${fails} failing` : 'ALL PASS')
if (fails) (globalThis as { process?: { exitCode: number } }).process!.exitCode = 1
