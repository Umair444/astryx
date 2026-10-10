// The voice orb on its own, for screenshots and the confirm's trusted-input arms (tests/test_voice_orb.py).
// Dev-server only: vite build's one input is index.html, so this page never ships.
// window.orb.set({...props}) drives it; window.orb.log holds every onConfirm / onDismiss as "confirm:<nonce>".
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '../src/index.css'
import { ThemeProvider } from '../src/theme'
import VoiceOrb, { type OrbAgent, type OrbConfirm, type OrbReply, type OrbState } from '../src/components/VoiceOrb'

type Props = { open: boolean; state: OrbState; inLevel: number; outLevel: number; agents: OrbAgent[]; reply: OrbReply | null; confirm: OrbConfirm | null }
const start: Props = { open: true, state: 'idle', inLevel: 0, outLevel: 0, agents: [], reply: null, confirm: null }
const log: string[] = []
let push: (p: Partial<Props>) => void = () => {}
;(window as unknown as { orb: object }).orb = { set: (p: Partial<Props>) => push(p), log }

function Harness() {
  const [p, setP] = useState(start)
  push = (q) => setP((cur) => ({ ...cur, ...q }))
  return (
    <VoiceOrb {...p} inLevel={() => p.inLevel} outLevel={() => p.outLevel}
      onConfirm={(n) => { log.push(`confirm:${n}`); setP((c) => ({ ...c, confirm: null })) }}
      onDismiss={(n) => { log.push(`dismiss:${n}`); setP((c) => ({ ...c, confirm: null })) }}
      onClose={() => setP((c) => ({ ...c, open: false }))} />
  )
}
createRoot(document.getElementById('root')!).render(<ThemeProvider><Harness /></ThemeProvider>)
