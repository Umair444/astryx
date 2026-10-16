import { useEffect, useState } from 'react'
import { post } from './api'
import { addMessage, loadThread, useStore } from './store'
import type { Msg } from './types'
import { Messages } from './Messages'
import { Composer } from './Composer'
import { Avatar, I } from './ui'

export function ChatView({ thread, onVoice }: { thread: string; onVoice: () => void }) {
  const msgs = useStore(s => s.messages[thread])
  const t = useStore(s => s.threads.find(x => x.thread === thread))
  const agentName = t?.agent ?? msgs?.find(m => !m.from.startsWith('cv-') && m.from !== 'owner')?.from ?? ''
  const agent = useStore(s => s.agents.find(a => a.name === agentName))
  const [err, setErr] = useState('')

  useEffect(() => { loadThread(thread).catch(e => setErr(e.message)) }, [thread])

  async function send(text: string, attachments: string[]) {
    setErr('')
    try {
      const m = await post<Msg>(`/threads/${encodeURIComponent(thread)}/messages`, { body: text, attachments })
      addMessage(m)
    } catch (e) { setErr(e instanceof Error ? e.message : 'not sent') }
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <header className="h-16 shrink-0 flex items-center gap-3 px-5 md:px-8 pl-16 md:pl-8 border-b border-line">
        {agentName && <Avatar name={agentName} size={34} alive={agent?.alive} />}
        <div className="min-w-0">
          <div className="font-medium leading-tight">{agentName || 'Conversation'}</div>
          <div className="text-[12px] text-fg-mute truncate">{agent?.blurb || (agent?.alive === false ? 'asleep — it will answer when it wakes' : '')}</div>
        </div>
        <button onClick={onVoice} title="Talk" className="ml-auto flex items-center gap-2 text-sm px-3 py-1.5 rounded-xl border border-line hover:border-violet/50 text-fg-dim hover:text-fg transition">
          {I.wave()} <span className="hidden sm:inline">Talk</span>
        </button>
      </header>
      {msgs === undefined ? (
        <div className="flex-1 grid place-items-center text-fg-mute">{err || 'Loading…'}</div>
      ) : msgs.length === 0 ? (
        <div className="flex-1 grid place-items-center px-6 text-center">
          <div>
            {agentName && <div className="mx-auto w-fit mb-4"><Avatar name={agentName} size={64} alive={agent?.alive} /></div>}
            <h2 className="font-serif text-4xl tracking-tight">{agentName ? `Say hello to ${agentName}` : 'Start the conversation'}</h2>
            <p className="text-fg-dim mt-2 max-w-md mx-auto">{agent?.blurb}</p>
          </div>
        </div>
      ) : (
        <Messages thread={thread} msgs={msgs} />
      )}
      <div className="shrink-0 px-4 md:px-8 pb-5 pt-2">
        <div className="max-w-3xl mx-auto">
          {err && <p className="text-bad text-sm mb-2">{err}</p>}
          <Composer onSend={send} onVoice={onVoice} placeholder={agentName ? `Message ${agentName}…` : 'Message…'} />
          <p className="text-[11px] text-fg-mute text-center mt-2">Agents act on the wire — every step is logged. Type <span className="font-mono">@name</span> to hand one message to another agent.</p>
        </div>
      </div>
    </div>
  )
}
