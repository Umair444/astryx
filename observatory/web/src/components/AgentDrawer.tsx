import { useEffect, useState } from 'react'
import { Badge, Drawer, ScrollArea, Tabs } from '@mantine/core'
import { api, agentColor, avatarInitial, displayName, fmtAgo, fmtTime, fmtTokens, obsKey, shortModel } from '../api'
import { useStore } from '../store'
import type { Profile, Step, Turn } from '../types'
import TurnPeek from './TurnPeek'

const KIND_COLOR: Record<string, string> = {
  tool: 'cyan',
  response: 'violet',
  milestone: 'teal',
  error: 'red',
  heartbeat: 'gray',
}

/* The agent's social page (plan-2 §9.4): the charter md IS the self — bio from the
   italic one-liner, sections from ## headings, avatar from its own folder, identity
   history from the private git log, and its turns as a peekable timeline. */
export default function AgentDrawer({ name, onClose }: { name: string; onClose: () => void }) {
  const [steps, setSteps] = useState<Step[] | null>(null)
  const [charter, setCharter] = useState<string | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [turns, setTurns] = useState<Turn[] | null>(null)
  const [peek, setPeek] = useState<number | null>(null)
  const { agents } = useStore()
  const row = agents.find((a) => a.agent === name)
  const col = agentColor(name)

  useEffect(() => {
    setSteps(null)
    setCharter(null)
    setProfile(null)
    setTurns(null)
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

  const key = obsKey()
  return (
    <Drawer
      opened
      onClose={onClose}
      position="right"
      size="lg"
      title={
        <div className="flex items-center gap-3">
          {profile?.avatar ? (
            <img
              src={`/api/agents/${encodeURIComponent(name)}/avatar${key ? `?key=${encodeURIComponent(key)}` : ''}`}
              className="w-10 h-10 rounded-xl object-cover border border-line"
              alt=""
            />
          ) : (
            <span
              className="w-10 h-10 rounded-xl grid place-items-center text-base font-bold text-deck"
              style={{ background: col }}
            >
              {avatarInitial(name)}
            </span>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold" style={{ color: col }}>
                {displayName(name)}
              </span>
              <Badge size="xs" color={row?.alive ? 'teal' : 'gray'} variant="light">
                {row?.alive ? 'live' : `last seen ${fmtAgo(row?.last_seen ?? null)}`}
              </Badge>
              {row?.model && (
                <span className="text-[10px] font-mono text-ink-mute">{shortModel(row.model)}</span>
              )}
            </div>
            {profile?.bio && <div className="text-[11px] text-ink-mute italic truncate">{profile.bio}</div>}
            {(profile?.group_path?.length ?? 0) > 0 && (
              <div className="text-[10px] font-mono text-ink-mute/70">
                {profile!.group_path.map(displayName).join(' · ')}
                {profile!.rank != null ? ` · rank ${profile!.rank}` : ''}
              </div>
            )}
          </div>
        </div>
      }
      styles={{ content: { background: '#0f1630' }, header: { background: '#0f1630' } }}
    >
      {profile && (
        <div className="grid grid-cols-4 gap-2 mb-3">
          {(
            [
              ['turns', profile.stats.turns],
              ['msgs sent', profile.stats.messages_sent],
              ['steps', profile.stats.steps],
              ['tok out', profile.stats.tokens_out],
            ] as [string, number][]
          ).map(([k, v]) => (
            <div key={k} className="bg-deck border border-line rounded-lg p-2 text-center">
              <div className="text-[10px] uppercase tracking-wider text-ink-mute">{k}</div>
              <div className="text-sm font-bold font-mono text-ink mt-0.5">{fmtTokens(v)}</div>
            </div>
          ))}
        </div>
      )}
      <Tabs defaultValue="self" color="cyan" keepMounted={false}>
        <Tabs.List mb="xs">
          <Tabs.Tab value="self" className="text-xs">self</Tabs.Tab>
          <Tabs.Tab value="turns" className="text-xs">turns</Tabs.Tab>
          <Tabs.Tab value="steps" className="text-xs">steps</Tabs.Tab>
          <Tabs.Tab value="history" className="text-xs">identity</Tabs.Tab>
          {charter ? <Tabs.Tab value="charter" className="text-xs">charter</Tabs.Tab> : null}
        </Tabs.List>

        {/* the self: parsed ## sections of the charter */}
        <Tabs.Panel value="self">
          <ScrollArea h="calc(100dvh - 280px)">
            {!profile && <div className="text-xs text-ink-mute py-4">reading the self…</div>}
            {profile?.sections.map((s) => (
              <div key={s.heading} className="mb-4">
                <div className="text-[11px] uppercase tracking-[0.15em] text-ink-mute mb-1">{s.heading}</div>
                <div className="text-[13px] text-ink-dim whitespace-pre-wrap leading-relaxed border-l-2 pl-3"
                     style={{ borderColor: `${col}44` }}>
                  {s.body}
                </div>
              </div>
            ))}
          </ScrollArea>
        </Tabs.Panel>

        {/* turns timeline — each entry peels open */}
        <Tabs.Panel value="turns">
          <ScrollArea h="calc(100dvh - 280px)">
            {turns === null && <div className="text-xs text-ink-mute py-4">loading…</div>}
            {turns?.map((t) => (
              <button
                key={t.id}
                onClick={() => setPeek(t.id)}
                className="w-full text-left py-2 border-b border-line/50 hover:bg-deck-3/40 rounded px-1"
              >
                <div className="flex items-center gap-2 text-[11px] text-ink-mute">
                  <span className="font-mono">#{t.id}</span>
                  <span>{fmtTime(t.ended_at)}</span>
                  <Badge size="xs" variant="light" color={t.source === 'wire' ? 'cyan' : t.source === 'trigger' ? 'yellow' : 'gray'}>
                    {t.source ?? '?'}
                  </Badge>
                  <span className="ml-auto font-mono">
                    {t.num_tools}⚙ · {fmtTokens(t.tokens_out)}↑
                  </span>
                </div>
                <div className="text-[12.5px] text-ink-dim line-clamp-2 mt-0.5">
                  {t.response_text ?? '(tools only)'}
                </div>
              </button>
            ))}
            {turns?.length === 0 && <div className="text-xs text-ink-mute py-4">no turns recorded yet</div>}
          </ScrollArea>
        </Tabs.Panel>

        <Tabs.Panel value="steps">
          <ScrollArea h="calc(100dvh - 280px)">
            {steps === null && <div className="text-xs text-ink-mute py-4">loading…</div>}
            {steps?.map((s) => (
              <div key={s.id} className="py-1.5 border-b border-line/50">
                <div className="flex items-center gap-2 text-[11px] text-ink-mute">
                  <Badge size="xs" variant="light" color={KIND_COLOR[s.kind] ?? 'gray'}>
                    {s.kind}
                  </Badge>
                  <span>{fmtTime(s.ts)}</span>
                  {s.goal_id != null && <span className="font-mono">goal #{s.goal_id}</span>}
                  {(s.tokens_in || s.tokens_out) ? (
                    <span className="ml-auto font-mono">
                      ↓{fmtTokens(s.tokens_in)} ↑{fmtTokens(s.tokens_out)}
                    </span>
                  ) : null}
                </div>
                {s.content && <div className="text-[13px] text-ink-dim line-clamp-3 mt-0.5">{s.content}</div>}
              </div>
            ))}
            {steps?.length === 0 && <div className="text-xs text-ink-mute py-4">no steps recorded</div>}
          </ScrollArea>
        </Tabs.Panel>

        {/* identity history — the private git log: how this self has changed */}
        <Tabs.Panel value="history">
          <ScrollArea h="calc(100dvh - 280px)">
            {!profile && <div className="text-xs text-ink-mute py-4">loading…</div>}
            {profile && profile.history.length === 0 && (
              <div className="text-xs text-ink-mute py-4">
                no self-edits yet — this self is exactly as it was born
              </div>
            )}
            {profile?.history.map((h) => (
              <div key={h.hash} className="py-2 border-b border-line/50 flex items-baseline gap-2">
                <span className="font-mono text-[10px] text-ink-mute">{h.hash}</span>
                <div className="min-w-0">
                  <div className="text-[12.5px] text-ink-dim truncate">{h.subject}</div>
                  <div className="text-[10px] text-ink-mute">
                    {h.author === name ? 'self-authored' : `by ${h.author}`} · {h.date}
                  </div>
                </div>
              </div>
            ))}
          </ScrollArea>
        </Tabs.Panel>

        <Tabs.Panel value="charter">
          <ScrollArea h="calc(100dvh - 280px)">
            <pre className="text-[12px] leading-relaxed text-ink-dim whitespace-pre-wrap font-mono bg-deck border border-line rounded-lg p-3">
              {charter}
            </pre>
          </ScrollArea>
        </Tabs.Panel>
      </Tabs>
      <TurnPeek turnId={peek} onClose={() => setPeek(null)} />
    </Drawer>
  )
}
