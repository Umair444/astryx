import { useMemo, useState } from 'react'
import { Select, Textarea } from '@mantine/core'
import { useStore } from '../store'

const field = { background: '#141c3a', border: '1px solid #1d2647' }

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
    return [...names].sort()
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
    <div className="border-t border-line bg-deck-2/60 px-3 py-2 shrink-0">
      <div className="flex items-end gap-2">
        <Select
          value={to}
          onChange={(v) => v && setTo(v)}
          data={options}
          size="xs"
          w={112}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
          styles={{ input: { ...field, fontFamily: 'var(--font-mono)' } }}
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
          placeholder={thread ? `reply in ${thread}…` : `message ${to}…`}
          autosize
          minRows={1}
          maxRows={5}
          size="xs"
          className="flex-1"
          styles={{ input: field }}
        />
        <button
          onClick={submit}
          disabled={busy || !body.trim()}
          className="px-3 py-1.5 rounded-md border border-cyan/40 bg-cyan/10 text-cyan-soft text-xs font-semibold hover:bg-cyan/20 disabled:opacity-40 transition-colors duration-75"
        >
          {busy ? '…' : 'send'}
        </button>
      </div>
      {err && <div className="text-[11px] text-red-400 mt-1">send failed — key rejected or wire down</div>}
    </div>
  )
}
