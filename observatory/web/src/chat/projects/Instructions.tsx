import { useEffect, useRef, useState } from 'react'

/* THE INSTRUCTIONS card: the brief the project's team works under, a calm plain-text field that saves itself
   (900ms after the last keystroke, and on blur), with an honest state: Unsaved (amber), Saving…, Saved. A version
   that arrives from elsewhere replaces the text only while the owner has nothing unsaved in it. */

type S = 'idle' | 'dirty' | 'saving' | 'saved'
const WORD: Record<S, string> = { idle: '', dirty: 'Unsaved', saving: 'Saving…', saved: 'Saved' }

export default function Instructions({ value, onSave }: { value: string; onSave: (v: string) => Promise<boolean> }) {
  const [v, setV] = useState(value)
  const [s, setS] = useState<S>('idle')
  const timer = useRef<number>(0)
  const latest = useRef(v)
  latest.current = v
  useEffect(() => { if (s === 'idle' || s === 'saved') setV(value) }, [value]) // eslint-disable-line react-hooks/exhaustive-deps

  const flush = async () => {
    clearTimeout(timer.current)
    const text = latest.current
    if (text === value) { setS((x) => (x === 'dirty' ? 'idle' : x)); return }
    setS('saving')
    const ok = await onSave(text)
    setS(ok ? (latest.current === text ? 'saved' : 'dirty') : 'dirty')
  }
  const change = (t: string) => {
    setV(t); setS('dirty')
    clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void flush(), 900)
  }
  useEffect(() => () => clearTimeout(timer.current), [])
  useEffect(() => {                                   // never lose words to a closed tab
    if (s !== 'dirty' && s !== 'saving') return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault() }
    addEventListener('beforeunload', warn)
    return () => removeEventListener('beforeunload', warn)
  }, [s])

  return (
    <section className="ws-kcard p-4" aria-label="instructions">
      <div className="flex items-center gap-2 mb-2">
        <h2 className="text-[13px] font-medium text-ink">Instructions</h2>
        <span className="ws-saved ml-auto" data-s={s} role="status" aria-live="polite">{WORD[s]}</span>
      </div>
      <textarea value={v} onChange={(e) => change(e.target.value)} onBlur={() => void flush()} maxLength={20000} aria-label="project instructions"
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); void flush() } }}
        placeholder={'What the team should know before every chat here: the goal, the data to trust, how answers should look.\n\ne.g. Lending book only; za is the source of truth; lead with the number, millions not lakh.'}
        className="ws-instructions" />
      <p className="mt-2 text-[11.5px] text-ink-mute leading-snug">Every new chat in this project starts with these, and with its files.</p>
    </section>
  )
}
