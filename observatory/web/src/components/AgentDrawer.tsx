import { useEffect, useState } from 'react'
import { Drawer } from '@mantine/core'
import AgentFace from './AgentFace'
import { api, apiSend, agentColor, displayName, fmtAgo, fmtTime, fmtTokens, shortModel } from '../api'
import { useStore } from '../store'
import type { Profile, Step, Turn } from '../types'
import TurnPeek from './TurnPeek'
import RuntimeEditor from './RuntimeEditor'
import { Count, Empty, LiveDot, Panel, Skeleton, Spark, Tabs, useNow } from '../ui/kit'
import { moodOf, nowLine, surfaceLabel, type Mood } from '../ui/life'
import { canvasBase } from '../cog'

/* step/turn kinds as quiet tinted pills (theme tokens, so every palette carries them) */
const KIND_TONE: Record<string, string> = {
  tool: 'text-cyan-soft bg-cyan-soft/10 border-cyan-soft/25',
  response: 'text-cyan bg-cyan/10 border-cyan/25',
  milestone: 'text-good bg-good/10 border-good/25',
  error: 'text-bad bg-bad/10 border-bad/25',
  wire: 'text-cyan-soft bg-cyan-soft/10 border-cyan-soft/25',
  trigger: 'text-warn bg-warn/10 border-warn/25',
}
function Pill({ kind }: { kind: string }) {
  return (
    <span className={`text-[10px] font-mono px-1.5 py-px rounded-full border ${KIND_TONE[kind] ?? 'text-ink-mute bg-deck-3 border-line'}`}>
      {kind}
    </span>
  )
}

const RING: Record<Mood, string> = {
  working: '0 0 0 3px var(--t-accent), 0 0 42px -4px var(--t-accent)',
  awake: '0 0 0 3px color-mix(in srgb, var(--t-good) 70%, transparent), 0 0 30px -10px var(--t-good)',
  asleep: '0 0 0 1px var(--t-line2)',
}

type Tab = 'self' | 'turns' | 'steps' | 'history' | 'charter' | 'runtime'

/* The agent's social page (plan-2 §9.4): the charter md IS the self — bio from the
   italic one-liner, sections from ## headings, avatar from its own folder, identity
   history from the private git log, and its turns as a peekable timeline. Opens on the
   person: face, mood, what it is doing right now, its day as a heartbeat. */
export default function AgentDrawer({ name, onClose, onTalk }: { name: string; onClose: () => void; onTalk?: () => void }) {
  const [steps, setSteps] = useState<Step[] | null>(null)
  const [charter, setCharter] = useState<string | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [turns, setTurns] = useState<Turn[] | null>(null)
  const [beat, setBeat] = useState<number[] | null>(null)
  const [peek, setPeek] = useState<number | null>(null)
  const [tab, setTab] = useState<Tab>('self')
  const { agents, who, presence } = useStore()
  const now = useNow(5000)
  const row = agents.find((a) => a.agent === name)
  const col = agentColor(name)
  const mood: Mood = row ? moodOf(row, presence[name], now) : 'asleep'
  const nl = row ? nowLine(row, presence[name], mood, now) : null

  useEffect(() => {
    setSteps(null)
    setCharter(null)
    setProfile(null)
    setTurns(null)
    setBeat(null)
    setTab('self')
    api<Profile>(`/agents/${encodeURIComponent(name)}/profile`).then(setProfile).catch(() => {})
    api<Step[]>(`/steps?agent=${encodeURIComponent(name)}&limit=50`)
      .then((s) => setSteps([...s].reverse()))
      .catch(() => setSteps([]))
    api<{ charter: string }>(`/agents/${encodeURIComponent(name)}/charter`)
      .then((c) => setCharter(c.charter))
      .catch(() => setCharter(''))
    api<Turn[]>(`/turns?agent=${encodeURIComponent(name)}&limit=30`)
      .then((t) => setTurns([...t].reverse()))
      .catch(() => setTurns([]))
  }, [name])
  // the day as a heartbeat — an activity rate, so owner-only (GET /api/pulse)
  useEffect(() => {
    if (!who.owner) return
    api<Record<string, number[]>>('/pulse').then((p) => setBeat(p[name] ?? Array(24).fill(0))).catch(() => {})
  }, [name, who.owner])

  const tabs = [
    { id: 'self' as const, label: 'Self' },
    { id: 'turns' as const, label: 'Turns' },
    { id: 'steps' as const, label: 'Steps' },
    { id: 'history' as const, label: 'Identity' },
    ...(charter ? [{ id: 'charter' as const, label: 'Charter' }] : []),
    ...(who.owner ? [{ id: 'runtime' as const, label: 'Runtime' }] : []),
  ]
  const presenceNow = profile?.presence ?? null
  const beatTotal = beat ? beat.reduce((x, y) => x + y, 0) : null

  return (
    <Drawer
      opened
      onClose={onClose}
      position="right"
      size="lg"
      withCloseButton={false}
      styles={{
        content: { background: 'color-mix(in srgb, var(--t-bg) 92%, transparent)', backdropFilter: 'blur(18px)' },
        body: { padding: 0 },
      }}
      overlayProps={{ backgroundOpacity: 0.45, blur: 3 }}
    >
      {/* hero: the person */}
      <div className="relative overflow-hidden px-6 pt-6 pb-5 border-b border-line">
        <div aria-hidden className="absolute -top-24 -right-16 w-72 h-72 rounded-full blur-3xl opacity-25" style={{ background: col }} />
        <button onClick={onClose} aria-label="close"
          className="absolute top-4 right-4 w-8 h-8 grid place-items-center rounded-full ax-panel text-ink-dim hover:text-ink text-lg leading-none z-10">
          ×
        </button>
        <div className="relative flex items-center gap-5">
          <span className={`rounded-full shrink-0 ${mood === 'working' ? 'ax-drawer-bob' : ''}`} style={{ boxShadow: RING[mood] }}>
            {/* the agent's own face (public route — no key ever rides an image URL) */}
            <AgentFace name={name} size={84} dim={mood === 'asleep'} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] uppercase tracking-[0.18em] text-ink-mute mb-1 truncate">
              {(profile?.group_path?.length ?? 0) > 0
                ? `${profile!.group_path.map(displayName).join(' · ')}${profile!.rank != null ? ` · rank ${profile!.rank}` : ''}`
                : 'independent'}
            </div>
            <div className="text-[26px] font-semibold tracking-[-0.02em] leading-none ax-title truncate">{displayName(name)}</div>
            <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12px] text-ink-dim">
              <span className="flex items-center gap-1.5"><LiveDot state={mood} />{mood === 'asleep' ? `asleep · seen ${fmtAgo(row?.last_seen ?? null)}` : mood}</span>
              {row?.model && <span className="font-mono text-[11px] text-ink-mute">· {shortModel(row.model)}</span>}
              {row?.type && row.type !== 'resident' && <span className="font-mono text-[10px] uppercase text-warn/90">· {row.type}</span>}
            </div>
          </div>
        </div>
        {profile?.bio && <div className="relative mt-4 text-[13.5px] text-ink-dim italic leading-relaxed">{profile.bio}</div>}
        {!profile && <Skeleton className="relative mt-4 h-4 w-3/4" />}
        <div className="relative mt-4 flex gap-2">
          {onTalk && (
            <button onClick={onTalk} className="ax-action inline-flex items-center gap-2 px-4 py-2 rounded-xl text-[13px] font-medium">
              Talk to {displayName(name)}
            </button>
          )}
          <a href={`#/chat/${encodeURIComponent(`obs:${name}`)}`}
            className="inline-flex items-center px-3 py-2 rounded-xl text-[13px] text-ink-dim hover:text-ink border border-line no-underline">
            Open in Chat
          </a>
          <a href={`${canvasBase()}#/new/${encodeURIComponent(name)}`} target="_blank" rel="noreferrer"
            className={onTalk ? 'inline-flex items-center px-3 py-2 rounded-xl text-[13px] text-ink-dim hover:text-ink border border-line no-underline'
              : 'ax-action inline-flex items-center gap-2 px-4 py-2 rounded-xl text-[13px] font-medium no-underline'}>
            Build on a canvas
          </a>
        </div>
      </div>

      <div className="px-6 py-5 flex flex-col gap-4">
        {/* NOW — where its attention is, in its own words, then its last few moves */}
        <Panel live={mood === 'working'} className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[10.5px] uppercase tracking-[0.16em] text-ink-mute">Now</span>
            {(presenceNow?.surface || nl?.where) && (
              <span className="text-[11.5px] text-cyan truncate">
                {presenceNow?.surface ? `${presenceNow.state} · ${surfaceLabel(presenceNow.surface)}` : nl?.where}
              </span>
            )}
          </div>
          {presenceNow?.say
            ? <div className="text-[14px] text-ink mb-2 leading-snug">“{presenceNow.say}”</div>
            : nl && mood === 'working' && <div className="text-[12.5px] text-ink-dim font-mono mb-2 leading-snug">{nl.line}</div>}
          {!profile && <div className="flex flex-col gap-1.5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-3.5 w-full" />)}</div>}
          <div className="flex flex-col gap-1">
            {(profile?.recent ?? []).slice(0, 5).map((r, i) => (
              <div key={i} className="flex gap-3 text-[12px]">
                <span className="text-ink-mute w-14 shrink-0 tabular-nums">{fmtAgo(r.ts)}</span>
                <span className={`truncate ${r.kind === 'error' ? 'text-bad' : r.kind === 'milestone' ? 'text-good' : 'text-ink-dim font-mono text-[11.5px]'}`}>{r.content}</span>
              </div>
            ))}
            {profile && !(profile.recent ?? []).length && <div className="text-[12px] text-ink-mute">quiet lately</div>}
          </div>
        </Panel>

        {/* the day as a heartbeat */}
        {who.owner && (
          <Panel className="p-4 overflow-hidden">
            <div className="flex items-baseline gap-2">
              <span className="text-[10.5px] uppercase tracking-[0.16em] text-ink-mute">Last 24 hours</span>
              <span className="ml-auto text-[13px] font-semibold text-ink tabular-nums"><Count value={beatTotal} /></span>
              <span className="text-[10.5px] uppercase tracking-[0.12em] text-ink-mute">steps</span>
            </div>
            <div className="h-16 mt-2 relative">
              {beat ? <Spark data={beat} tone={mood === 'asleep' ? 'accent2' : mood === 'working' ? 'accent' : 'good'} className="absolute inset-0 w-full h-full" />
                : <Skeleton className="absolute inset-x-0 bottom-0 h-2" />}
            </div>
            <div className="flex justify-between text-[10px] text-ink-mute font-mono mt-1"><span>24h ago</span><span>now</span></div>
          </Panel>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          {(
            [
              ['Turns', profile?.stats.turns],
              ['Messages', profile?.stats.messages_sent],
              ['Steps', profile?.stats.steps],
              ['Tokens out', profile?.stats.tokens_out],
            ] as [string, number | undefined][]
          ).map(([k, v]) => (
            <Panel key={k} className="px-3 py-2.5">
              <div className="text-[10px] uppercase tracking-[0.14em] text-ink-mute">{k}</div>
              <div className="text-[18px] font-semibold text-ink mt-1 leading-none"><Count value={v} format={(n) => fmtTokens(Math.round(n))} /></div>
            </Panel>
          ))}
        </div>

        <div className="overflow-x-auto -mx-1 px-1 [scrollbar-width:none]">
          <Tabs id={`drawer-${name}`} items={tabs} value={tab} onChange={setTab} />
        </div>

        {/* the self: parsed ## sections of the charter */}
        {tab === 'self' && (
          <div>
            {!profile && <div className="flex flex-col gap-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-4 w-full" />)}</div>}
            {profile?.sections.map((s) => (
              <div key={s.heading} className="mb-5">
                <div className="text-[11px] uppercase tracking-[0.15em] text-ink-mute mb-1.5">{s.heading}</div>
                <div className="text-[13.5px] text-ink-dim whitespace-pre-wrap leading-relaxed border-l-2 pl-3.5"
                     style={{ borderColor: `color-mix(in srgb, ${col} 35%, transparent)` }}>
                  {s.body}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* turns timeline — each entry peels open */}
        {tab === 'turns' && (
          <div className="flex flex-col gap-2">
            {turns === null && [0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full rounded-xl" />)}
            {turns?.map((t) => (
              <Panel key={t.id} as="button" interactive onClick={() => setPeek(t.id)} className="w-full px-3.5 py-2.5">
                <div className="flex items-center gap-2 text-[11px] text-ink-mute">
                  <span className="font-mono">#{t.id}</span>
                  <span>{fmtTime(t.ended_at)}</span>
                  <Pill kind={t.source ?? '?'} />
                  <span className="ml-auto font-mono">
                    {t.num_tools}⚙ · {fmtTokens(t.tokens_out)}↑
                  </span>
                </div>
                <div className="text-[12.5px] text-ink-dim line-clamp-2 mt-1 text-left">
                  {t.response_text ?? '(tools only)'}
                </div>
              </Panel>
            ))}
            {turns?.length === 0 && <Empty title="No turns recorded yet" />}
          </div>
        )}

        {tab === 'steps' && (
          <div className="flex flex-col">
            {steps === null && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full mb-2" />)}
            {steps?.map((s) => (
              <div key={s.id} className="py-2 border-b border-line/50">
                <div className="flex items-center gap-2 text-[11px] text-ink-mute">
                  <Pill kind={s.kind} />
                  <span>{fmtTime(s.ts)}</span>
                  {s.goal_id != null && <span className="font-mono">goal #{s.goal_id}</span>}
                  {(s.tokens_in || s.tokens_out) ? (
                    <span className="ml-auto font-mono">
                      ↓{fmtTokens(s.tokens_in)} ↑{fmtTokens(s.tokens_out)}
                    </span>
                  ) : null}
                </div>
                {s.content && <div className="text-[13px] text-ink-dim line-clamp-3 mt-1">{s.content}</div>}
              </div>
            ))}
            {steps?.length === 0 && <Empty title="No steps recorded" />}
          </div>
        )}

        {/* identity history — the private git log: how this self has changed */}
        {tab === 'history' && (
          <div className="flex flex-col">
            {!profile && <Skeleton className="h-10 w-full" />}
            {profile && profile.history.length === 0 && (
              <Empty title="No self-edits yet" hint="This self is exactly as it was born." />
            )}
            {profile?.history.map((h) => (
              <div key={h.hash} className="py-2.5 border-b border-line/50 flex items-baseline gap-3">
                <span className="font-mono text-[10px] text-ink-mute">{h.hash}</span>
                <div className="min-w-0">
                  <div className="text-[13px] text-ink-dim truncate">{h.subject}</div>
                  <div className="text-[10.5px] text-ink-mute">
                    {h.author === name ? 'self-authored' : `by ${h.author}`} · {h.date}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'charter' && (
          who.owner ? (
            <CharterEditor name={name} initial={charter ?? ''} live={!!row?.alive} />
          ) : (
            <pre className="text-[12px] leading-relaxed text-ink-dim whitespace-pre-wrap font-mono ax-panel rounded-xl p-3.5">
              {charter}
            </pre>
          )
        )}

        {who.owner && tab === 'runtime' && <RuntimeEditor name={name} live={!!row?.alive} />}
      </div>
      <style>{`.ax-drawer-bob { animation: ax-drawer-bob 2.4s ease-in-out infinite } @keyframes ax-drawer-bob { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-3px) } } @media (prefers-reduced-motion: reduce) { .ax-drawer-bob { animation: none } }`}</style>
      <TurnPeek turnId={peek} onClose={() => setPeek(null)} />
    </Drawer>
  )
}

/* Owner-only charter editor. The charter IS the agent's identity and law; edits
   write the file, but a running body only inherits them at respawn (spawn.sh
   rebuilds its CLAUDE.md from charter + law), so the save note says so plainly. */
function CharterEditor({ name, initial, live }: { name: string; initial: string; live: boolean }) {
  const [text, setText] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  useEffect(() => {
    setText(initial)
    setNote(null)
  }, [initial, name])
  const dirty = text !== initial

  async function save() {
    setSaving(true)
    setNote(null)
    try {
      const r = await apiSend<{ note: string }>('PUT', `/agents/${encodeURIComponent(name)}/charter`, { content: text })
      setNote(r.note)
    } catch (e) {
      setNote('save failed — ' + (e as Error).message)
    }
    setSaving(false)
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11px] text-ink-mute leading-relaxed">
        {displayName(name)}'s charter — its identity and law. Edits write the file; a running body
        inherits them only when it respawns{live ? ' (it is live now).' : '.'}
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.currentTarget.value)}
        spellCheck={false}
        className="w-full h-[60dvh] min-h-[240px] text-[12px] font-mono leading-relaxed text-ink-dim ax-panel rounded-xl p-3.5 resize-none focus:outline-none focus:border-cyan/40"
      />
      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={!dirty || saving}
          className="ax-action px-3.5 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40"
        >
          {saving ? 'saving…' : 'save charter'}
        </button>
        {dirty && <span className="text-[11px] text-warn">unsaved changes</span>}
        {note && !dirty && <span className="text-[11px] text-ink-mute">{note}</span>}
      </div>
    </div>
  )
}
