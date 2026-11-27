import { A } from './icons'
import type { ParsedAsk } from './ask'

/* An ask, as the chat shows it (DESIGN.md principle 2, "selection is scope"): the quoted passage as a chip, serif and
   barred like a margin quote, naming the file, version and page; a click opens the file at that highlight. The
   question follows as ordinary text, and the [[ann:]] marker never shows. */
export default function AskChip({ ask, onOpen }: { ask: ParsedAsk; onOpen?: (a: ParsedAsk) => void }) {
  return <QuoteChip quote={ask.quote} source={ask.source} title={`Show this passage in ${ask.name}`} onOpen={onOpen && (() => onOpen(ask))} />
}

/* the ONE quote chip: a passage a message answers (an ask's highlight, a reply's message), with where it is from */
export function QuoteChip({ quote, source, title, onOpen }: { quote: string; source: string; title: string; onOpen?: () => void }) {
  return (
    <button type="button" onClick={onOpen} disabled={!onOpen}
      className="ax-askchip group block w-full text-left rounded-[10px] pl-3 pr-2.5 py-2 mb-2" title={onOpen ? title : undefined}>
      <span className="block ax-askchip-q line-clamp-3">“{quote}”</span>
      <span className="mt-1 flex items-center gap-1.5 text-[11.5px] text-ink-mute group-hover:text-ink-dim">
        <span className="truncate">{source}</span>
        {onOpen && <span className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">{A.link()}</span>}
      </span>
    </button>
  )
}
