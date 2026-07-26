import { Fragment } from 'react'

/* markdown-lite renderer — the Claude-terminal reading experience: headings,
   bullets, numbered lists, bold, inline code, fenced code, links, quotes.
   Deliberately small; agents write plain markdown and this covers it. */

function inline(text: string, keyBase: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/\S+)/g)
  return parts.map((p, i) => {
    const k = `${keyBase}-${i}`
    if (p.startsWith('**') && p.endsWith('**'))
      return <b key={k} className="text-ink font-semibold">{p.slice(2, -2)}</b>
    if (p.startsWith('`') && p.endsWith('`'))
      return (
        <code key={k} className="font-mono text-[0.92em] bg-deck-3 border border-line rounded px-1 py-px text-cyan-soft">
          {p.slice(1, -1)}
        </code>
      )
    if (p.startsWith('http'))
      return (
        <a key={k} href={p} target="_blank" rel="noreferrer" className="text-cyan hover:underline break-all">
          {p}
        </a>
      )
    return <Fragment key={k}>{p}</Fragment>
  })
}

export default function Md({ text }: { text: string }) {
  const blocks: React.ReactNode[] = []
  const lines = text.split('\n')
  let i = 0
  let key = 0
  while (i < lines.length) {
    const l = lines[i]
    // fenced code
    if (l.trimStart().startsWith('```')) {
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) buf.push(lines[i++])
      i++
      blocks.push(
        <pre key={key++} className="my-1.5 text-[12px] font-mono bg-deck border border-line rounded-md px-3 py-2 overflow-x-auto text-ink-dim whitespace-pre-wrap">
          {buf.join('\n')}
        </pre>,
      )
      continue
    }
    // headings
    const h = /^(#{1,4})\s+(.*)$/.exec(l)
    if (h) {
      blocks.push(
        <div key={key++} className={`mt-2 mb-1 font-semibold text-ink ${h[1].length <= 2 ? 'text-[14px]' : 'text-[13px]'}`}>
          {inline(h[2], `h${key}`)}
        </div>,
      )
      i++
      continue
    }
    // bullets / numbered — group consecutive items
    if (/^\s*([-*•]|\d+[.)])\s+/.test(l)) {
      const items: string[] = []
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i]))
        items.push(lines[i++].replace(/^\s*([-*•]|\d+[.)])\s+/, ''))
      blocks.push(
        <ul key={key++} className="my-1 space-y-0.5">
          {items.map((it, j) => (
            <li key={j} className="flex gap-2">
              <span className="text-cyan-soft/60 shrink-0 leading-relaxed">▪</span>
              <span>{inline(it, `li${key}-${j}`)}</span>
            </li>
          ))}
        </ul>,
      )
      continue
    }
    // quote
    if (l.trimStart().startsWith('>')) {
      blocks.push(
        <div key={key++} className="my-1 border-l-2 border-line pl-3 text-ink-mute italic">
          {inline(l.replace(/^\s*>\s?/, ''), `q${key}`)}
        </div>,
      )
      i++
      continue
    }
    // blank
    if (!l.trim()) {
      blocks.push(<div key={key++} className="h-1.5" />)
      i++
      continue
    }
    // paragraph line
    blocks.push(
      <div key={key++} className="leading-relaxed">
        {inline(l, `p${key}`)}
      </div>,
    )
    i++
  }
  return <div className="text-[13.5px] text-ink-dim break-words">{blocks}</div>
}
