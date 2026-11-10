import { useState } from 'react'
import { agentColor, displayName, fmtAgo } from '../../api'
import { useThreadTitles, type BriefAgent, type BriefFile, type BriefSaid, type Briefing as Brief, type Status } from '../data'
import { Presence } from '../shell/AgentRail'
import { KindIcon } from '../artifacts/kinds'
import { kindOfName } from '../artifacts/api'
import { I } from '../icons'
import { useBriefing } from './visit'
import './briefing.css'

/* "WHILE YOU WERE AWAY" (iteration 15): the home's first answer at 07:00 — what the team did since the owner last
   looked. One summary line, then one row per agent in the order that needs the owner first (waiting on you → wrote
   to you → only worked): its face, its newest words to you, and chips that go somewhere (the conversation AT that
   message, a file in the artifact panel). Agents that only worked share a quieter grid. Org news folds away.
   Everything here is a headline the server already cut and masked (GET /api/ws/briefing); no body reaches the page. */

export interface BriefingActions {
  onJump: (thread: string, id: number) => void
  onFile: (agent: string, f: BriefFile) => void
  onAgent: (agent: string) => void
  onSeen: () => void
}

const ROWS = 6                             // agents that need a look, shown before "Show n more"
const OPENS = new Set(['chat', 'floor', 'canvas'])
const opens = (s: string) => OPENS.has(s)
const n = (k: number, one: string, many = `${one}s`) => `${k} ${k === 1 ? one : many}`

/* the window in words: "through the night" when it spans one, else since a clock time (today) or a day */
export function windowWords(since: string, until: string, clamped: boolean): string {
  if (clamped) return 'in the last two days'
  const a = new Date(since), b = new Date(until)
  const hrs = (+b - +a) / 3.6e6
  const overnight = b.getHours() >= 4 && b.getHours() < 12 && hrs >= 5 && (a.getHours() >= 18 || a.getHours() < 4 || a.getDate() !== b.getDate())
  if (overnight) return 'through the night'
  const hm = a.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (a.toDateString() === b.toDateString()) return `since ${hm}`
  return hrs < 36 ? `since ${hm} yesterday` : `since ${a.toLocaleDateString([], { weekday: 'long' })}`
}

export default function Briefing({ since, status, acts }: { since: string | null; status: Record<string, Status>; acts: BriefingActions }) {
  const { data, failed, retry } = useBriefing(since)
  const ids = (data?.agents ?? []).flatMap((a) => [...a.said.map((m) => m.thread), a.waiting?.thread]).filter((t): t is string => !!t && /^(chat|obs|cv):/.test(t))
  const titles = useThreadTitles([...new Set(ids)])
  if (!data) {
    return (
      <section className="ws-brief" aria-label="while you were away" aria-busy={!failed}>
        <Head />
        {failed
          ? <p className="text-[13px] text-ink-dim mt-2">Couldn’t load what happened while you were away. <button className="underline underline-offset-2 hover:text-ink" onClick={retry}>Try again</button></p>
          : <div className="mt-3 space-y-2.5" aria-hidden><div className="ws-brief-skel w-[62%]" /><div className="ws-brief-skel w-[48%]" /><div className="ws-brief-skel w-[55%]" /></div>}
      </section>
    )
  }
  return <Body data={data} status={status} titles={titles} acts={acts} />
}

function Head({ right }: { right?: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-3 flex-wrap">
      <h2 className="ws-display text-[30px] leading-none text-ink">While you were away</h2>
      {right}
    </div>
  )
}

function Body({ data, status, titles, acts }: { data: Brief; status: Record<string, Status>; titles: Record<string, string>; acts: BriefingActions }) {
  const { totals: t, agents } = data
  const [all, setAll] = useState(false)
  const when = windowWords(data.since, data.until, data.clamped)
  const spoke = agents.filter((a) => a.said.length || a.files.length || a.waiting)
  const worked = agents.filter((a) => !(a.said.length || a.files.length || a.waiting))
  const seen = <button className="ws-brief-seen ml-auto" onClick={acts.onSeen} title="Start the next briefing from now">Mark all seen</button>
  if (!agents.length && !data.news.length) {
    return (
      <section className="ws-brief" aria-label="while you were away">
        <Head />
        <p className="mt-2.5 text-[14px] text-ink-dim">{when === 'through the night' ? 'Quiet night' : 'All quiet'} — nothing new since you left.</p>
      </section>
    )
  }
  const parts = [
    agents.length ? `${n(agents.length, 'agent')} worked ${when}` : `Nothing from the team ${when}`,
    t.to_owner ? n(t.to_owner, 'message') + ' to you' : '',
    t.files ? n(t.files, 'file') : '',
  ].filter(Boolean)
  return (
    <section className="ws-brief" aria-label="while you were away">
      <Head right={seen} />
      <p className="mt-2 text-[13.5px] text-ink-dim">
        {parts.join(' · ')}
        {t.waiting > 0 && <> · <span className="ws-brief-waitword">{t.waiting} waiting on you</span></>}
      </p>
      {spoke.length > 0 && (
        <ul className="mt-4 flex flex-col" role="list">
          {(all ? spoke : spoke.slice(0, ROWS)).map((a) => <Row key={a.agent} a={a} s={status[a.agent]} titles={titles} acts={acts} />)}
        </ul>
      )}
      {spoke.length > ROWS && (
        <button className="ws-brief-seen -ml-2 mt-1" aria-expanded={all} onClick={() => setAll((x) => !x)}>
          {all ? 'Show fewer' : `Show ${spoke.length - ROWS} more`}
        </button>
      )}
      {worked.length > 0 && (
        <div className={spoke.length ? 'mt-4' : 'mt-4'}>
          {spoke.length > 0 && <h3 className="ws-label mb-1.5">Also at work</h3>}
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 -mx-2" role="list">
            {worked.map((a) => <Quiet key={a.agent} a={a} s={status[a.agent]} onAgent={acts.onAgent} />)}
          </ul>
        </div>
      )}
      {data.news.length > 0 && <News items={data.news} />}
    </section>
  )
}

/* one agent that wrote to you or made something: the newest words first, the rest one click away */
function Row({ a, s, titles, acts }: { a: BriefAgent; s?: Status; titles: Record<string, string>; acts: BriefingActions }) {
  const [more, setMore] = useState(false)
  const lead = a.said[0]
  const rest = a.said.slice(1)
  const meta = [
    a.to_owner > 1 ? `${a.to_owner} messages to you` : '',
    a.turns ? n(a.turns, 'turn') : '',
    a.peers.length ? `worked with ${a.peers.map((p) => displayName(p.agent)).join(', ')}` : '',
  ].filter(Boolean)
  const threadChip = (m: BriefSaid | null) => {
    if (!m?.thread) return null
    if (!opens(m.surface)) return <span className="ws-brief-chip is-static" title="Read and answer it on WhatsApp">{I.chat('w-3.5 h-3.5')}On WhatsApp</span>
    return (
      <button className="ws-brief-chip" onClick={() => acts.onJump(m.thread!, m.id)} title="Open the conversation at this message">
        {I.chat('w-3.5 h-3.5')}<span className="truncate">{titles[m.thread] ?? 'The conversation'}</span>{I.arrow('w-3 h-3 opacity-60')}
      </button>
    )
  }
  return (
    <li className="ws-brief-row" style={{ ['--ws-agent' as string]: agentColor(a.agent), ['--ws-pip-bg' as string]: 'var(--t-bg)' }}>
      <button className="shrink-0 self-start mt-0.5 rounded-full" onClick={() => acts.onAgent(a.agent)} aria-label={`open ${displayName(a.agent)}'s desk`}>
        <Presence agent={a.agent} status={s} size={32} />
      </button>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 min-w-0">
          <button className="text-[14px] font-medium text-ink hover:underline underline-offset-2" onClick={() => acts.onAgent(a.agent)}>{displayName(a.agent)}</button>
          {a.waiting && <span className="ws-brief-wait">waiting on you</span>}
          <span className="ml-auto text-[12px] text-ink-mute shrink-0" title={a.last_ts ?? ''}>{fmtAgo(lead?.ts ?? a.last_ts)}</span>
        </div>
        {lead
          ? <Said m={lead} onJump={acts.onJump} className="text-[14.5px] text-ink leading-snug mt-0.5" />
          : a.did && <p className="text-[14px] text-ink-dim leading-snug mt-0.5 line-clamp-2">{a.did}</p>}
        {meta.length > 0 && <p className="text-[12px] text-ink-mute mt-1">{meta.join(' · ')}</p>}
        {(lead?.thread || a.files.length > 0) && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {threadChip(a.waiting ? a.said.find((m) => m.id === a.waiting!.id) ?? lead : lead)}
            {a.files.slice(0, 4).map((f) => (
              <button key={`${f.thread}/${f.name}`} className="ws-brief-chip" onClick={() => acts.onFile(a.agent, f)} title={`Open ${f.name}`}>
                <KindIcon kind={kindOfName(f.name)} className="w-3.5 h-3.5" /><span className="truncate">{f.name}</span>
                {f.versions > 1 && <span className="text-ink-mute">v{f.versions}</span>}
              </button>
            ))}
            {a.files.length > 4 && <span className="ws-brief-chip is-static">+{a.files.length - 4} more</span>}
          </div>
        )}
        {rest.length > 0 && (
          <div className="mt-1.5">
            <button className="text-[12px] text-ink-mute hover:text-ink inline-flex items-center gap-1" aria-expanded={more} onClick={() => setMore((m) => !m)}>
              <span className={`transition-transform ${more ? 'rotate-90' : ''}`}>{I.chevron('w-3 h-3')}</span>
              {more ? 'Fewer' : `${rest.length} earlier ${rest.length === 1 ? 'message' : 'messages'}`}
            </button>
            {more && (
              <ul className="mt-1 ml-4 flex flex-col gap-0.5" role="list">
                {rest.map((m) => <li key={m.id} className="flex items-baseline gap-2 min-w-0"><Said m={m} onJump={acts.onJump} className="text-[13px] text-ink-dim min-w-0 flex-1" /><span className="text-[11.5px] text-ink-mute shrink-0">{fmtAgo(m.ts)}</span></li>)}
              </ul>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

/* one message to you as a line: in a conversation the workspace opens, it opens there at that message */
function Said({ m, onJump, className }: { m: BriefSaid; onJump: BriefingActions['onJump']; className: string }) {
  const text = m.headline
  if (m.thread && opens(m.surface)) return <button className={`${className} block text-left truncate w-full hover:underline decoration-[color-mix(in_srgb,var(--t-fg)_30%,transparent)] underline-offset-2`} onClick={() => onJump(m.thread!, m.id)} title={text}>{text}</button>
  return <p className={`${className} truncate`} title={text}>{text}</p>
}

/* an agent that only worked: face, name, how much, and its last words as a muted line */
function Quiet({ a, s, onAgent }: { a: BriefAgent; s?: Status; onAgent: (x: string) => void }) {
  const bits = [a.turns ? n(a.turns, 'turn') : '', a.to_agents ? `${a.to_agents} to ${a.peers[0] ? displayName(a.peers[0].agent) : 'the team'}${a.peers.length > 1 ? ' +' : ''}` : ''].filter(Boolean)
  return (
    <li>
      <button className="ws-row w-full flex items-start gap-2.5 rounded-[12px] px-2 py-2 text-left" onClick={() => onAgent(a.agent)}
        style={{ ['--ws-pip-bg' as string]: 'var(--t-bg)' }}>
        <Presence agent={a.agent} status={s} size={24} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2"><span className="text-[13px] font-medium text-ink">{displayName(a.agent)}</span><span className="text-[11.5px] text-ink-mute truncate">{bits.join(' · ')}</span></span>
          {a.did && <span className="block text-[12.5px] text-ink-mute truncate" title={a.did}>{a.did}</span>}
        </span>
      </button>
    </li>
  )
}

function News({ items }: { items: Brief['news'] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-4 border-t border-line pt-3">
      <button className="text-[12.5px] text-ink-dim hover:text-ink inline-flex items-center gap-1.5" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className={`transition-transform ${open ? 'rotate-90' : ''}`}>{I.chevron('w-3 h-3')}</span>
        Org news<span className="text-ink-mute">· {items.length}</span>
      </button>
      {open && (
        <ul className="mt-2 flex flex-col gap-1.5" role="list">
          {items.map((x) => (
            <li key={x.id} className="flex items-baseline gap-2 text-[13px] min-w-0">
              <span className="text-ink-mute shrink-0 w-[4.5rem] truncate">{displayName(x.from)}</span>
              <span className="text-ink-dim truncate flex-1" title={x.headline}>{x.headline}</span>
              <span className="text-[11.5px] text-ink-mute shrink-0">{fmtAgo(x.ts)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
