import { useCallback, useEffect, useRef, useState } from 'react'
import { Popover } from '@mantine/core'
import { motion } from 'motion/react'
import { obsKey } from '../api'
import { focusBase } from '../cog'
import { EnergyVad, wav } from '../ear/vad'
import { earLook, type Mic } from '../ear/look'
import AgentFace from './AgentFace'
import { Action } from '../ui/kit'
import { liveOn } from '../pilot/voice'

/* hearing S1 (plan-8674): the observatory holds the mic. This pill is ALWAYS in the header for the owner (rule (d):
   mic state is never hidden) and its one button is the one-tap MUTE. The room's state lives server-side (the
   `leases` row via bridges/ear.py); the pill shows what the server says, plus this tab's own capture.

   Only VAD-cut speech segments are uploaded. Nothing here can block the page (rule (e)): every failure degrades to
   "ear offline" and the rest of the observatory carries on.

   DESIGN (skills/astryx-design §8, owner #42106 "the org listening together"): the pill is QUIET at rest, a small
   orb and one word. The orb swells with the smoothed mic level only while speech is heard, then settles. Tap opens a
   sheet that shows the ROOM: who is attending (faces, the crew-strip way), one serif line for the state, one action.
   Muted is warn and calm. A caught name (S2) glows on that agent's face for a few seconds, the one glow on screen.
   `attending` and `caught` are S2's to fill; until then the sheet says so plainly.

   THE ROOM ANSWERS HERE (seed #46319): until S4 gives the room a voice, an agent's reply to the owner on the room's
   thread (ear-<room>) is shown in the sheet, with a dot on the pill until the sheet is opened. The ear marks it
   delivered as it serves it: this sheet is the surface that thread belongs to. */

interface Reply { id: number; from: string; body: string; ts: string; seen?: boolean }
interface Status {
  lease: { mic: Mic; holder: string | null }
  stt: { degraded: boolean; reasons: string[]; queue: number; backend: string; rtf_last: number | null; behind_s?: number }
  store: { ok: boolean }
  ttl_days?: number
  backup_days?: number                                   // backup.sh keeps the last N nightly dumps
  attending?: string[]                                   // S2: agents given hearing
  caught?: { agent: string; at: string } | null           // S2: the last name heard, never the words
  replies?: Reply[]                                      // agents' replies to the owner on ear-<room>, oldest first
}

const CAUGHT_MS = 4000
const still = () => {
  try { return matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

const HOLDER = 'tab-' + Math.random().toString(36).slice(2, 10)
const PREF = 'ear_on'

async function ear(path: string, body?: unknown, raw?: Blob, q = ''): Promise<Response> {
  const key = obsKey()
  // the FOCUSED org's ear (its /o/<org>/ base in a cog: the front routes no bare /ear/, which read as "offline", 10-19)
  return fetch(`${focusBase()}ear/api/${path}${q}`, {
    method: body !== undefined || raw ? 'POST' : 'GET',
    headers: {
      ...(key ? { 'x-obs-key': key } : {}),
      ...(raw ? { 'content-type': 'audio/wav' } : body !== undefined ? { 'content-type': 'application/json' } : {}),
    },
    body: raw ?? (body !== undefined ? JSON.stringify(body) : undefined),
  })
}

export default function EarControl({ view }: { view: string }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [offline, setOffline] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [hearing, setHearing] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [seen, setSeen] = useState(0)                   // the newest reply id the owner has had the sheet open for
  const level = useRef(0)                                // smoothed mic level 0..1, read by the orbs each frame
  const orbs = useRef(new Set<HTMLElement>())
  const media = useRef<{ stream: MediaStream; ctx: AudioContext; node: ScriptProcessorNode; vad: EnergyVad } | null>(null)
  const viewRef = useRef(view)
  viewRef.current = view

  const refresh = useCallback(async () => {
    try {
      const r = await ear('status')
      if (!r.ok) throw new Error(String(r.status))
      setStatus(await r.json())
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  const stop = useCallback((release: boolean) => {
    const m = media.current
    media.current = null
    if (m) {
      m.vad.reset()
      m.node.disconnect()
      m.stream.getTracks().forEach((t) => t.stop())      // the browser's own mic indicator goes out too
      m.ctx.close().catch(() => {})
    }
    setCapturing(false)
    setHearing(false)
    if (release) ear('release', { holder: HOLDER }).catch(() => {})
  }, [])

  const upload = useCallback(async (pcm: Int16Array) => {
    if (liveOn()) return                                 // the live voice is hearing the room; the ear steps aside
    try {
      const r = await ear('utterance', undefined, wav(pcm),
        `?holder=${HOLDER}&view=${encodeURIComponent(viewRef.current)}`)
      if (r.status === 423 || r.status === 409) {      // muted elsewhere, or this tab lost the ear
        stop(false)
        refresh()
      }
    } catch {
      setOffline(true)
    }
  }, [stop, refresh])

  const start = useCallback(async () => {
    setProblem(null)
    const c = await ear('claim', { holder: HOLDER }).catch(() => null)
    if (!c) return setOffline(true)
    if (!c.ok) {
      refresh()
      return setProblem(c.status === 423 ? 'The room is muted. Unmute to listen.' :
        'Another tab is listening. Close it, or mute there first.')
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      })
      const ctx = new AudioContext()
      if (ctx.state === 'suspended') await ctx.resume()
      const src = ctx.createMediaStreamSource(stream)
      const node = ctx.createScriptProcessor(4096, 1, 1)
      const vad = new EnergyVad({ sampleRate: ctx.sampleRate, onSegment: upload, onSpeech: setHearing })
      node.onaudioprocess = (e) => {
        const x = e.inputBuffer.getChannelData(0)
        vad.push(x)
        let sq = 0
        for (let i = 0; i < x.length; i += 4) sq += x[i] * x[i]
        const rms = Math.min(1, Math.sqrt(sq / (x.length / 4)) * 8)
        level.current = level.current * 0.7 + rms * 0.3   // smoothed: jitter reads as noise
      }
      src.connect(node)
      node.connect(ctx.destination)                      // a processor only runs when connected; it outputs silence
      media.current = { stream, ctx, node, vad }
      setCapturing(true)
      try { localStorage.setItem(PREF, '1') } catch { /* private mode: no memory, still works */ }
    } catch {
      setProblem('Microphone unavailable. Allow mic access for this page; it needs https or localhost.')
      ear('release', { holder: HOLDER }).catch(() => {})
    }
    refresh()
  }, [upload, refresh])

  const mute = useCallback(async () => {
    stop(false)
    try { localStorage.setItem(PREF, '0') } catch { /* ignore */ }
    await ear('mute', {}).catch(() => setOffline(true))
    refresh()
  }, [stop, refresh])

  const unmute = useCallback(async () => {
    await ear('unmute', {}).catch(() => setOffline(true))
    await start()
  }, [start])

  // status every 5 s; while capturing, the heartbeat keeps the lease (TTL 30 s) and notices a mute from elsewhere
  useEffect(() => {
    refresh()
    const t = setInterval(async () => {
      if (media.current) {
        const r = await ear('heartbeat', { holder: HOLDER }).catch(() => null)
        if (r && !r.ok) stop(false)
      }
      refresh()
    }, 5000)
    const bye = () => {
      if (media.current) {
        const key = obsKey()
        fetch(`${focusBase()}ear/api/release`, {
          method: 'POST', keepalive: true, body: JSON.stringify({ holder: HOLDER }),
          headers: { 'content-type': 'application/json', ...(key ? { 'x-obs-key': key } : {}) },
        }).catch(() => {})
      }
    }
    addEventListener('pagehide', bye)
    return () => {
      clearInterval(t)
      removeEventListener('pagehide', bye)
      stop(true)
    }
  }, [refresh, stop])

  // always-on: once the owner has chosen to listen, a reload resumes (unless the room is muted)
  const resumed = useRef(false)
  useEffect(() => {
    if (resumed.current || !status || offline) return
    resumed.current = true
    let want = false
    try { want = localStorage.getItem(PREF) === '1' } catch { /* ignore */ }
    if (want && status.lease.mic !== 'muted') start()
  }, [status, offline, start])

  // the orbs swell with the level only while speech is heard; otherwise (and under reduced motion) they are still
  useEffect(() => {
    if (!hearing || still()) {
      orbs.current.forEach((el) => { el.style.transform = '' })
      return
    }
    let raf = 0
    const tick = () => {
      const s = 1 + Math.min(0.35, level.current * 0.6)
      orbs.current.forEach((el) => { el.style.transform = `scale(${s.toFixed(3)})` })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [hearing])
  const orbRef = useCallback((el: HTMLElement | null) => {
    if (!el) return
    orbs.current.add(el)
    return () => { orbs.current.delete(el) }
  }, [])

  const mic: Mic = status?.lease.mic ?? 'unknown'
  const mine = capturing && status?.lease.holder === HOLDER
  const degraded = !!status && (status.stt.degraded || !status.store.ok)
  const attending = status?.attending ?? []
  const caught = status?.caught && Date.now() - Date.parse(status.caught.at) < CAUGHT_MS ? status.caught.agent : null

  // one state, read four ways: the word on the pill, the orb's tone, the sheet's serif line, the one action
  const look = earLook({ offline, mic, capturing, mine, hearing, behind_s: status?.stt.behind_s })
  const replies = status?.replies ?? []
  const shown = replies.slice(-3)
  // OPENING the sheet with a reply showing is its delivery (a4 #46445): the poll only reads, this marks
  const unseen = shown.filter((r) => !r.seen && r.id > seen).map((r) => r.id)
  useEffect(() => {
    if (!open || !unseen.length) return
    const top = Math.max(...unseen)                        // a failed mark leaves it pending (honest) and unread here
    ear('replies/seen', { ids: unseen }).then((r) => { if (r.ok) setSeen((s) => Math.max(s, top)) }).catch(() => {})
  }, [open, unseen.join(',')])                             // eslint-disable-line react-hooks/exhaustive-deps
  const unread = !open && replies.some((r) => !r.seen && r.id > seen)
  const act = look.action === 'mute' ? mute : look.action === 'unmute' ? unmute : look.action === 'listen' ? start : undefined
  const orbTone = look.tone === 'accent' ? 'var(--t-accent)' : look.tone === 'warn' ? 'var(--t-warn)' : 'var(--t-mute)'
  const reasons = [...(status?.stt.reasons ?? []), ...(status && !status.store.ok ? ['store offline'] : [])]
  const pill = look.tone === 'warn' ? 'bg-warn/15 text-warn border-warn/30'
    : look.live ? 'text-ink border-[color-mix(in_srgb,var(--t-accent)_35%,var(--t-line))] bg-[color-mix(in_srgb,var(--t-accent)_10%,transparent)]'
    : 'text-ink-mute border-line hover:text-ink-dim hover:bg-ink/[.06]'

  return (
    <Popover opened={open} onChange={setOpen} position="bottom-end" offset={10} withinPortal
      transitionProps={{ transition: 'pop-top-right', duration: 160 }}>
      <Popover.Target>
        <button onClick={() => setOpen((o) => !o)}
          title={`Microphone: ${look.word}`} aria-label={`Microphone: ${look.word}. Open the ear.`}
          aria-expanded={open}
          className={`flex items-center gap-1.5 h-7 pl-1.5 pr-2.5 rounded-full border text-[11px] transition-colors ${pill}`}>
          <span className="relative grid place-items-center w-4 h-4" aria-hidden>
            <span ref={orbRef} className="w-2.5 h-2.5 rounded-full transition-[background,box-shadow] duration-300"
              style={{
                background: `radial-gradient(circle at 35% 30%, color-mix(in srgb, #fff 45%, ${orbTone}) 0%, ${orbTone} 60%)`,
                boxShadow: look.live ? `0 0 ${hearing ? 10 : 5}px -1px ${orbTone}` : 'none',
              }} />
          </span>
          <span className={look.tone === 'warn' || offline ? '' : 'hidden sm:inline'}>{look.word}</span>
          {degraded && !offline && look.tone !== 'warn' && <span className="w-1.5 h-1.5 rounded-full bg-warn" title="degraded" />}
          {unread && <span className="w-1.5 h-1.5 rounded-full bg-accent" title="a reply from the room" />}
          {attending.length > 0 && (
            <span className="hidden sm:flex items-center ml-0.5">
              {attending.slice(0, 3).map((n, i) => (
                <span key={n} className="rounded-full ring-2 ring-[var(--t-bg)]" style={{ marginLeft: i ? -5 : 0 }}>
                  <AgentFace name={n} size={16} />
                </span>
              ))}
            </span>
          )}
        </button>
      </Popover.Target>

      <Popover.Dropdown className="ax-panel !bg-transparent !border-line !p-0 !rounded-[22px] !shadow-2xl overflow-hidden"
        style={{ width: 'min(320px, calc(100vw - 2rem))' }}>
        <div className="px-5 pt-5 pb-4">
          <div className="flex items-center gap-4">
            <span className="grid place-items-center w-14 h-14 shrink-0" aria-hidden>
              <span ref={orbRef} className={`rounded-full transition-[background,box-shadow] duration-500 ${look.live && !hearing ? 'ax-orb' : ''}`}
                style={{
                  width: 40, height: 40, ['--orb' as string]: orbTone,
                  background: `radial-gradient(circle at 34% 30%, color-mix(in srgb, #fff 50%, ${orbTone}) 0%, transparent 34%),
                    radial-gradient(circle at 50% 55%, ${orbTone} 0%, color-mix(in srgb, ${orbTone} 40%, transparent) 58%, transparent 74%)`,
                  boxShadow: look.live ? `0 0 ${hearing ? 34 : 22}px -6px ${orbTone}` : 'none',
                  opacity: look.tone === 'mute' ? 0.55 : 1,
                }} />
            </span>
            <div className="min-w-0">
              <div className="lib-display text-[26px] leading-[1.1] text-ink">{look.line}</div>
              <div className="text-[12px] text-ink-mute mt-0.5" aria-live="polite">{look.sub}</div>
            </div>
          </div>

          <div className="mt-5">
            <div className="text-[11px] uppercase tracking-[.08em] text-ink-mute mb-2">Attending</div>
            {attending.length ? (
              <div className="flex flex-wrap gap-2">
                {attending.map((n) => (
                  <motion.span key={n} layout className="flex items-center gap-1.5 pl-0.5 pr-2.5 py-0.5 rounded-full bg-ink/[.04] text-[12px] text-ink-dim">
                    <motion.span className="rounded-full"
                      animate={{ boxShadow: n === caught ? '0 0 0 2px var(--t-accent), 0 0 14px 2px color-mix(in srgb, var(--t-accent) 45%, transparent)' : '0 0 0 0px transparent' }}
                      transition={{ duration: 0.45, ease: 'easeOut' }}>
                      <AgentFace name={n} size={22} />
                    </motion.span>
                    <span className={n === caught ? 'text-ink' : ''}>{n}</span>
                  </motion.span>
                ))}
              </div>
            ) : (
              <div className="text-[12px] text-ink-dim leading-snug">
                No agent is attending yet. When an agent is given hearing its face sits here, and it glows when you
                say its name.
              </div>
            )}
          </div>

          {replies.length > 0 && (
            <div className="mt-5">
              <div className="text-[11px] uppercase tracking-[.08em] text-ink-mute mb-2">The room answered</div>
              <div className="flex flex-col gap-2" aria-live="polite">
                {shown.map((r) => (
                  <motion.div key={r.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3, ease: 'easeOut' }} className="flex items-start gap-2">
                    <span className="shrink-0 mt-0.5"><AgentFace name={r.from} size={20} /></span>
                    <div className="min-w-0 text-[12px] leading-snug">
                      <span className="text-ink">{r.from}</span>
                      <span className="text-ink-mute"> · {new Date(r.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      <div className="text-ink-dim whitespace-pre-wrap break-words">{r.body}</div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </div>
          )}

          {(problem || (degraded && !offline)) && (
            <div className="mt-4 rounded-xl bg-warn/10 text-warn text-[12px] px-3 py-2 leading-snug">
              {problem ?? `Transcription is degraded: ${reasons.join('; ')}.`}
            </div>
          )}

          <div className="mt-5 flex items-center gap-2">
            {look.action === 'listen' && <Action onClick={act} className="flex-1 justify-center h-11 sm:h-9">Listen</Action>}
            {look.action === 'unmute' && <Action onClick={act} className="flex-1 justify-center h-11 sm:h-9">Unmute and listen</Action>}
            {look.action === 'mute' && (
              <button onClick={act}
                className="flex-1 h-11 sm:h-9 rounded-xl border border-line text-[13px] font-medium text-ink-dim hover:text-warn hover:border-warn/40 hover:bg-warn/10 transition-colors">
                Mute the room
              </button>
            )}
            {!look.action && <div className="flex-1 h-9 grid place-items-center text-[12px] text-ink-mute">Retrying every few seconds…</div>}
          </div>
        </div>
        <div className="px-5 py-2.5 border-t border-line text-[11px] text-ink-mute leading-snug">
          Speech only, transcribed on this host.
          {status?.ttl_days ? ` Kept ${status.ttl_days} days live` : ''}{status?.ttl_days && status.backup_days ? `; the last ${status.backup_days} nightly backups hold it longer.` : status?.ttl_days ? '.' : ''}
          {status && <span className="font-mono"> · {status.stt.backend}{status.stt.rtf_last != null ? ` · rtf ${status.stt.rtf_last}` : ''}</span>}
        </div>
      </Popover.Dropdown>
    </Popover>
  )
}
