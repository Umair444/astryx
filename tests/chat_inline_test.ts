// The chat's inline files (owner 11-11): a body read as text runs with its [[file:]] embeds in place, and which of
// them are drawn in place. Called by tests/test_chat_inline.py:  node tests/chat_inline_test.ts
import { parts, stripEmbeds } from '../observatory/web/src/chat/model.ts'
import { inlineParts } from '../observatory/web/src/chat/thread/flow.ts'

let fails = 0
const arm = (name: string, ok: boolean) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`); if (!ok) fails++ }
const shape = (b: string) => inlineParts(parts(b)).map((p) => ('embed' in p ? `[${p.embed.path}${p.embed.label ? `|${p.embed.label}` : ''}]` : p.text)).join(' / ')

arm('no embed: the one text run is stripEmbeds(body)', JSON.stringify(parts('[chat with @db — x]\nhello\n\n')) === JSON.stringify([{ text: stripEmbeds('[chat with @db — x]\nhello\n\n') }]))
arm('an image sits where it was embedded', shape('Here:\n[[file:/m/a.png]]\nSource: o.x') === 'Here: / [/m/a.png] / Source: o.x')
arm("an upload's display name rides with it", shape('see [[file:/m/u/0123.jpg]] (photo.jpg)') === 'see / [/m/u/0123.jpg|photo.jpg]')
arm('a trailing csv is left to the chip row', shape('the sheet\n[[file:/h/a.csv]]') === 'the sheet')
arm('a csv mid-text is drawn in place', shape('[[file:/h/a.csv]]\nthen more') === '[/h/a.csv] / then more')
arm('a trailing pdf / audio / video stays inline', shape('x [[file:/a.pdf]] [[file:/b.mp3]] [[file:/c.mp4]]') === 'x / [/a.pdf] / [/b.mp3] / [/c.mp4]')
arm('the same path twice draws once, at its first spot', shape('[[file:/a.png]] one [[file:/a.png]] two') === '[/a.png] / one / two')
arm("a project block's pinned files are not the owner's", shape('[project: P]\nctx [[file:/pin.png]]\n[/project]\nhi') === 'hi')
arm('an annotation marker is never text', shape('q [[ann:abc]] [[file:/a.png]]') === 'q / [/a.png]')

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
