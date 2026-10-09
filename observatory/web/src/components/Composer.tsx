import { useMemo, useState } from 'react'
import { Select, Textarea } from '@mantine/core'
import { displayName } from '../api'
import { useStore } from '../store'
import AgentFace from './AgentFace'

const field = { background: 'transparent', border: 'none' }

/* Owner composer — only rendered when whoami says owner. Sends onto the wire
   as 'owner'; when a thread pane is open the message lands in that thread. */
export default function Composer({ thread }: { thread?: string }) {
  const { agents, send } = useStore()
  const [to, setTo] = useState('seed')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(false)

  const options = useMemo(() => {
    const names = new Set(agents.map((a) => a.agent))
    names.add('seed')
    names.delete('owner')
    return [...names].sort().map((n) => ({ value: n, label: displayName(n) }))
  }, [agents])

  async function submit() {
    const text = body.trim()
    if (!text || busy) return
    setBusy(true)
    setErr(false)
    try {
      await send(to, text, thread)
      setBody('')
    } catch {
      setErr(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="shrink-0 px-3 sm:px-4 pb-3 pt-2">
      <div className="ax-panel rounded-2xl flex items-end gap-1.5 p-1.5 focus-within:border-cyan/50 transition-colors">
        <Select
          value={to}
          onChange={(v) => v && setTo(v)}
          data={options}
          size="sm"
          w={140}
          allowDeselect={false}
          searchable
          aria-label="send to"
          comboboxProps={{ withinPortal: true }}
          leftSection={<AgentFace name={to} size={22} />}
          renderOption={({ option }) => (
            <span className="flex items-center gap-2"><AgentFace name={option.value} size={20} />{option.label}</span>
          )}
          styles={{ input: { ...field, background: 'var(--t-panel2)', borderRadius: 12, fontSize: 13 } }}
        />
        <Textarea
          value={body}
          onChange={(e) => setBody(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={thread ? 'Reply in this thread…' : `Message ${displayName(to)}…`}
          aria-label="message"
          autosize
          minRows={1}
          maxRows={6}
          size="sm"
          className="flex-1 min-w-0"
          styles={{ input: { ...field, fontSize: 14, paddingTop: 7 } }}
        />
        <button
          onClick={submit}
          disabled={busy || !body.trim()}
          aria-label="send"
          className="ax-action shrink-0 w-9 h-9 !p-0 grid place-items-center !rounded-xl text-[16px] leading-none"
        >
          {busy ? <span className="w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" /> : '↑'}
        </button>
      </div>
      <div className="flex items-center gap-2 mt-1 px-2 text-[10.5px] text-ink-mute">
        {err ? <span className="text-bad">send failed — key rejected or wire down</span>
          : <span>you write as <b className="text-ink-dim font-medium">owner</b> · Enter to send, Shift+Enter for a new line</span>}
      </div>
    </div>
  )
}
