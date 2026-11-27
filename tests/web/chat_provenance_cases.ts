// The chat's provenance-footer detector (observatory/web/src/chat/thread/provenance.ts), run by
// tests/test_chat_provenance.py (esbuild + node). Real endings from the wire, and the near-misses it must leave alone.
import { splitProvenance } from '../../observatory/web/src/chat/thread/provenance'

let fails = 0
const arm = (name: string, got: unknown, want: unknown) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) fails++
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`)
}
const src = (t: string) => splitProvenance(t).source
const body = (t: string) => splitProvenance(t).body

console.log('footers it takes')
arm('a blank-line Source paragraph', src('Margin fell 3%.\n\nSource: o.product_pl.vw_product_pl, live submissions 9 and 10.'),
  'Source: o.product_pl.vw_product_pl, live submissions 9 and 10.')
arm('... and the body loses it', body('Margin fell 3%.\n\nSource: o.product_pl, x.'), 'Margin fell 3%.')
arm('a last line with no blank line before it', src("Customer counts are a copy of Jul's.\nSource: o.product_pl.vw_product_pl, loaded 2026-10-13."),
  'Source: o.product_pl.vw_product_pl, loaded 2026-10-13.')
arm('Sources:', src('Down by Rs 214M.\n\nSources: za d_dfs.financial_product_fact (figures), Aug–Sep 2026.'), 'Sources: za d_dfs.financial_product_fact (figures), Aug–Sep 2026.')
arm('Data:', src('276.8K were in both (43%).\n\nData: Postgres intermediate.iar_ledger (Completed).'), 'Data: Postgres intermediate.iar_ledger (Completed).')
arm('Data used:', src('alerts me.\n\nData used: ClickHouse raw.loan_advances; Postgres glp_summary.'), 'Data used: ClickHouse raw.loan_advances; Postgres glp_summary.')
arm('Provenance:', src('Done.\n\nProvenance: steps 4410–4418, wiki db_o_citus_topology.'), 'Provenance: steps 4410–4418, wiki db_o_citus_topology.')
arm('an italic line, unwrapped, snake_case kept', src('Want a 14-day window?\n_Source: ClickHouse raw.loan_advances / loan_repayments, data to 29 Oct._'),
  'Source: ClickHouse raw.loan_advances / loan_repayments, data to 29 Oct.')
arm('italic with no colon', src('Up 4%.\n\n*Source ClickHouse raw.loan_advances, to 15 Oct*'), 'Source ClickHouse raw.loan_advances, to 15 Oct')
arm('bold key', src('Up 4%.\n\n**Source:** o.product_pl'), '**Source:** o.product_pl')
arm('a signed line: — lending · source:', src('Draft it for you to approve.\n\n— lending · source: WhatsApp contact search, 5 Nov 2026'),
  '— lending · source: WhatsApp contact search, 5 Nov 2026')
arm('trailing whitespace tolerated', src('x\n\nSource: a.b\n\n  '), 'Source: a.b')

console.log('what it leaves alone')
arm('a source named mid-paragraph', src('I left his details out. Source: wiki user_x (08-12).'), null)
arm('the whole answer is the source line', src('Source: o.product_pl'), null)
arm('no source line', src('Revenue rose 4%.\n\nWant the breakdown?'), null)
arm('a word that starts like the key', src('Total up.\n\nDatabase: o is healthy.'), null)
arm('"Sourced" is not "Source:"', src('Total up.\n\nSourced from the team: thanks.'), null)
arm('a table row', src('Here:\n\n| Source: | x |'), null)
arm('a list item', src('Steps:\n\n- Source: rerun the job'), null)
arm('a heading', src('Intro\n\n## Sources: below'), null)
arm('a long last paragraph', src('x\n\nSource: ' + 'y'.repeat(700)), null)
arm('a "Sources:" heading over a list', src('x\n\nSources:\n- a\n- b'), null)
arm('a key with nothing after the colon', src('x\n\nSource:'), null)
arm('inside an unclosed code fence', src('```\ncode\nSource: x'), null)
arm('a bare "data:" sentence mid-answer stays (only the LAST paragraph)', src('Data: 3 rows.\n\nAll good.'), null)

console.log(fails ? `FAIL: ${fails} failing` : 'ALL PASS')
if (fails) (globalThis as { process?: { exitCode: number } }).process!.exitCode = 1
