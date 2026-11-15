import { useEffect, useRef, useState } from 'react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { terminalScreen, terminalType } from '../live'

/* THE AGENT'S TERMINAL, IN THE CHAT (owner 11-15: "/ command in chat should also have tmux send-key feature to send to
   terminal, like it is the front of claude code"). What the agent's own Claude Code screen shows, kept current, with
   the two things a person does there: type a "/" command, and answer what it asks (arrows, Enter, Escape, a number).
   Prose never goes this way: a message is sent in the box below, over the wire, as always. `run` is the line the chat
   just issued (a "/" command picked in the composer); one that wipes or ends the session is asked about first.
   Owner only (the server refuses anyone else). */

export interface TermRun { id: number; text?: string; confirm?: string }
const KEYS: { k: string; label: string; say: string }[] = [
  { k: 'Up', label: '↑', say: 'Up' }, { k: 'Down', label: '↓', say: 'Down' }, { k: 'Enter', label: 'Enter', say: 'Enter' },
  { k: 'Escape', label: 'Esc', say: 'Escape: closes what it is asking, or interrupts its turn' },
  { k: '1', label: '1', say: 'Answer 1' }, { k: '2', label: '2', say: 'Answer 2' }, { k: '3', label: '3', say: 'Answer 3' },
]

export default function TerminalPeek({ agent, run, onClose }: { agent: string; run: TermRun | null; onClose: () => void }) {
  const [screen, setScreen] = useState<string | null>(null)
  const [said, setSaid] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [ask, setAsk] = useState<string | null>(null)
  const [line, setLine] = useState('')
  const pre = useRef<HTMLPreElement>(null)
  const who = displayName(agent)

  async function send(what: { text: string } | { keys: string[] }) {
    setBusy(true); setErr('')
    try {
      const r = await terminalType(agent, what)
      setScreen(r.screen); setSaid(`Typed ${'text' in what ? what.text : what.keys.join(' ')}`)
    } catch (e) { setErr(String((e as Error).message || e)) }
    setBusy(false)
  }
  // the line the chat issued: asked about first when it wipes or ends the session
  useEffect(() => {
    if (!run) return
    if (run.confirm && run.text) setAsk(run.text)
    else if (run.text) { setAsk(null); void send({ text: run.text }) }
  }, [run?.id])   // eslint-disable-line react-hooks/exhaustive-deps
  // keep the screen current while it is open and the page is looked at
  useEffect(() => {
    let dead = false
    const f = () => { if (document.visibilityState === 'visible') terminalScreen(agent).then((r) => { if (!dead) setScreen(r.screen) }).catch((e) => { if (!dead) setErr(String((e as Error).message || e)) }) }
    f()
    const t = setInterval(f, 2500)
    return () => { dead = true; clearInterval(t) }
  }, [agent])
  useEffect(() => { const el = pre.current; if (el) el.scrollTop = el.scrollHeight }, [screen])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const t = line.trim()
    if (!t) return
    if (!t.startsWith('/')) { setErr('A terminal line starts with /. To talk to it, use the message box below.'); return }
    setLine(''); void send({ text: t })
  }
  return (
    <section className="ws-term mx-auto w-full max-w-[760px] px-3 sm:px-4 md:px-6" aria-label={`${who}'s terminal`}>
      <div className="ws-term-box">
        <header className="flex items-center gap-2 px-3 h-10 border-b border-line">
          <AgentFace name={agent} size={20} />
          <span className="text-[13px] font-medium text-ink">{who}’s terminal</span>
          <span className={`flex-1 min-w-0 truncate text-[12px] ${err ? 'text-bad' : 'text-ink-mute'}`} role="status">{err || (busy ? 'Typing…' : said)}</span>
          <button type="button" onClick={onClose} className="rounded-lg px-2 py-1 text-[12px] text-ink-mute hover:text-ink hover:bg-[color-mix(in_srgb,var(--t-fg)_7%,transparent)]">Close</button>
        </header>
        <pre ref={pre} className="ws-term-screen" tabIndex={0} aria-label="what its terminal shows">{screen === null ? (err ? 'Its screen can’t be read right now.' : 'Reading its screen…') : screen || 'Its screen is empty.'}</pre>
        {ask && (
          <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-t border-line text-[12.5px] text-ink" role="alert">
            <span className="flex-1 min-w-[200px]"><b className="font-medium">{ask}</b> {ask.startsWith('/clear') ? `wipes ${who}’s conversation; it starts with no memory of this chat.` : `ends ${who}’s session.`}</span>
            <button type="button" disabled={busy} onClick={() => { const t = ask; setAsk(null); void send({ text: t }) }}
              className="rounded-lg px-2.5 py-1 text-[12.5px] font-medium text-ink border border-line hover:border-line-2">Type it</button>
            <button type="button" onClick={() => setAsk(null)} className="text-[12px] text-ink-mute hover:text-ink underline underline-offset-2">Cancel</button>
          </div>
        )}
        <form onSubmit={submit} className="flex flex-wrap items-center gap-1.5 px-2 py-2 border-t border-line">
          <input value={line} onChange={(e) => { setLine(e.currentTarget.value); setErr('') }} spellCheck={false} autoCapitalize="off" autoCorrect="off"
            onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }}
            placeholder="Type a / command, such as /context" aria-label={`a command for ${who}'s terminal`}
            className="ws-term-line flex-1 min-w-[160px] rounded-lg bg-transparent border border-line px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-mute outline-none focus:border-[color-mix(in_srgb,var(--t-accent)_55%,var(--t-line))]" />
          <div className="flex items-center gap-1" role="group" aria-label="keys to press in its terminal">
            {KEYS.map((x) => (
              <button key={x.k} type="button" disabled={busy} title={x.say} aria-label={x.say} onClick={() => void send({ keys: [x.k] })}
                className="ws-key">{x.label}</button>
            ))}
          </div>
        </form>
      </div>
    </section>
  )
}
