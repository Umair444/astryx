import { useState } from 'react'
import { motion } from 'motion/react'
import { get, post } from './api'
import type { Me } from './types'

export function Login({ onIn }: { onIn: (m: Me) => void }) {
  const [key, setKey] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!key.trim()) return
    setBusy(true); setErr('')
    try {
      await post('/login', { key: key.trim() })
      onIn(await get<Me>('/me'))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'could not sign in')
    } finally { setBusy(false) }
  }

  return (
    <div className="h-full grid place-items-center relative overflow-hidden px-4">
      <div className="aurora" />
      <motion.form
        onSubmit={submit}
        initial={{ opacity: 0, y: 14, filter: 'blur(6px)' }} animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.6, ease: [0.2, 0.8, 0.2, 1] }}
        className="relative z-10 w-full max-w-sm text-center"
      >
        <motion.div
          className="mx-auto w-16 h-16 rounded-[22px] sig ring-sig mb-7"
          animate={{ rotate: [0, 6, -4, 0], scale: [1, 1.04, 1] }} transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
        />
        <h1 className="font-serif text-5xl tracking-tight leading-none">astryx <span className="italic sig-text">canvas</span></h1>
        <p className="text-fg-dim mt-3 mb-8">The front door to your org. Talk to your agents. Watch them paint.</p>
        <input
          type="password" autoFocus value={key} onChange={e => setKey(e.target.value)}
          placeholder="Owner key or invite code"
          className="w-full glass rounded-2xl px-4 py-3.5 outline-none focus:border-violet/60 transition placeholder:text-fg-mute"
        />
        {err && <p className="text-bad text-sm mt-3">{err}</p>}
        <button disabled={busy} className="w-full mt-4 sig rounded-2xl py-3.5 font-medium disabled:opacity-60 hover:brightness-110 transition">
          {busy ? 'Opening…' : 'Enter'}
        </button>
      </motion.form>
    </div>
  )
}
