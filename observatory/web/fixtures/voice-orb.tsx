// The voice orb on its own, for screenshots and the confirm's trusted-input arms (tests/test_voice_orb.py).
// Dev-server only: vite build's one input is index.html, so this page never ships.
// The confirm runs through a REAL executor (pilot/core) with a two-action catalog, bound by the app's own
// confirmBinder, so the arms test the gate the app uses. window.orb.set({...props}) drives the view;
// set({confirm: {action, args}}) asks the executor as the room, which mints the nonce; window.orb.log holds
// "ran:<action>" for every run and "dismiss:<nonce>"; window.orb.forge() hands confirm() a plain object.
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '../src/index.css'
import { ThemeProvider } from '../src/theme'
import { confirmBinder, createExecutor, type Catalog, type Pending } from '../src/pilot/core'
import VoiceOrb, { type OrbAgent, type OrbBind, type OrbReply, type OrbState } from '../src/components/VoiceOrb'

const catalog: Catalog = {
  classes: ['write'], matrix: { room: { write: 'confirm' } },
  actions: [
    { name: 'open_desktop', class: 'write', description: 'open a desktop', parameters: { type: 'object', additionalProperties: false,
      properties: { display: { type: 'integer' }, focus: { type: 'string' } } } },
    { name: 'navigate', class: 'write', description: 'go to a view', parameters: { type: 'object', additionalProperties: false,
      properties: { route: { type: 'string' } } } },
  ],
}
const log: string[] = []
let pend: (p: Pending | null) => void = () => {}
const ex = createExecutor(catalog, { open_desktop: () => { log.push('ran:open_desktop') }, navigate: () => { log.push('ran:navigate') } },
  { onPending: (p) => pend(p) })

const bind: OrbBind = confirmBinder(ex)                        // the app's binder, on this executor

type Ask = { action: string; args?: Record<string, unknown> }
type Props = { open: boolean; state: OrbState; inLevel: number; outLevel: number; agents: OrbAgent[]; reply: OrbReply | null }
const start: Props = { open: true, state: 'idle', inLevel: 0, outLevel: 0, agents: [], reply: null }
let push: (p: Partial<Props>) => void = () => {}
;(window as unknown as { orb: object }).orb = {
  set: ({ confirm, ...p }: Partial<Props> & { confirm?: Ask | null }) => {
    push(p)
    if (confirm) void ex.room.run(confirm.action, confirm.args ?? {})
    else if (confirm === null) ex.dismiss(ex.pending()?.nonce ?? '')
  },
  log,
  pending: () => ex.pending()?.nonce ?? null,
  forge: async () => (await ex.confirm(ex.pending()?.nonce ?? '', { isTrusted: true, pointerType: 'mouse',
    currentTarget: document.querySelector('[data-pilot-allow]'), timeStamp: 1e9 })).status,
}

function Harness() {
  const [p, setP] = useState(start)
  const [c, setC] = useState<Pending | null>(null)
  push = (q) => setP((cur) => ({ ...cur, ...q }))
  pend = setC
  return (
    <VoiceOrb {...p} inLevel={() => p.inLevel} outLevel={() => p.outLevel} confirm={c} bind={bind}
      onDismiss={(n) => { log.push(`dismiss:${n}`); ex.dismiss(n) }}
      onClose={() => setP((cur) => ({ ...cur, open: false }))} />
  )
}
createRoot(document.getElementById('root')!).render(<ThemeProvider><Harness /></ThemeProvider>)
