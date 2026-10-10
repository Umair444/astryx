import { useCallback, useEffect, useRef, useState } from 'react'
import { Tooltip } from '@mantine/core'
import { obsKey } from '../api'
import { EnergyVad, wav } from '../ear/vad'

/* hearing S1 (plan-8674): the observatory holds the mic. This pill is ALWAYS in the header for the owner (rule (d):
   mic state is never hidden) and its one button is the one-tap MUTE. The room's state lives server-side (the
   `leases` row via bridges/ear.py); the pill shows what the server says, plus this tab's own capture.

   Only VAD-cut speech segments are uploaded. Nothing here can block the page (rule (e)): every failure degrades to
   "ear offline" and the rest of the observatory carries on. */

type Mic = 'off' | 'listening' | 'stale' | 'muted' | 'focal' | 'reverting' | 'unknown'
interface Status {
  lease: { mic: Mic; holder: string | null }
  stt: { degraded: boolean; reasons: string[]; queue: number; backend: string; rtf_last: number | null }
  store: { ok: boolean }
}

const HOLDER = 'tab-' + Math.random().toString(36).slice(2, 10)
const PREF = 'ear_on'

async function ear(path: string, body?: unknown, raw?: Blob, q = ''): Promise<Response> {
  const key = obsKey()
  return fetch(`/ear/api/${path}${q}`, {
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
      return setProblem(c.status === 423 ? 'muted' : 'another tab holds the ear')
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
      node.onaudioprocess = (e) => vad.push(e.inputBuffer.getChannelData(0))
      src.connect(node)
      node.connect(ctx.destination)                      // a processor only runs when connected; it outputs silence
      media.current = { stream, ctx, node, vad }
      setCapturing(true)
      try { localStorage.setItem(PREF, '1') } catch { /* private mode: no memory, still works */ }
    } catch {
      setProblem('microphone permission denied')
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
        fetch('/ear/api/release', {
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

  const mic: Mic = status?.lease.mic ?? 'unknown'
  const mine = capturing && status?.lease.holder === HOLDER
  const degraded = !!status && (status.stt.degraded || !status.store.ok)
  let label: string, tone: string, dot: string, action: 'listen' | 'mute' | 'unmute' | null
  if (offline) {
    ;[label, tone, dot, action] = ['ear offline', 'text-ink-mute border-line', 'bg-ink-mute/40', null]
  } else if (mic === 'muted') {
    ;[label, tone, dot, action] = ['muted', 'text-bad border-bad/40 bg-bad/10', 'bg-bad', 'unmute']
  } else if (capturing) {
    ;[label, tone, dot, action] = [hearing ? 'hearing' : 'listening', 'text-cyan-soft border-cyan/40 bg-cyan/10',
      hearing ? 'bg-cyan animate-pulse' : 'bg-cyan', 'mute']
  } else if (mic === 'listening' && !mine) {
    ;[label, tone, dot, action] = ['listening (other tab)', 'text-cyan-soft border-cyan/30', 'bg-cyan/70', 'mute']
  } else if (mic === 'stale' || mic === 'reverting') {
    ;[label, tone, dot, action] = ['ear lost', 'text-warn border-warn/40', 'bg-warn', 'listen']
  } else {
    ;[label, tone, dot, action] = ['mic off', 'text-ink-mute border-line hover:text-ink-dim', 'bg-ink-mute/40', 'listen']
  }
  if (degraded && !offline && mic !== 'muted') {
    tone = 'text-warn border-warn/40 bg-warn/10'
    label += ' · degraded'
  }
  const tip = offline
    ? 'The ear service is not reachable. Nothing is being heard; the page works as normal.'
    : [
        mic === 'muted' ? 'Muted: nothing is captured or uploaded until you unmute.' :
        capturing ? 'This tab holds the mic. Only speech segments are sent, transcribed on this host, kept a few days.' :
        mic === 'listening' ? 'Another tab holds the room\'s mic.' : 'The mic is off.',
        problem ? `(${problem})` : '',
        degraded ? `Degraded: ${[...(status?.stt.reasons ?? []), ...(status?.store.ok ? [] : ['store offline'])].join('; ')}` : '',
        status ? `STT ${status.stt.backend}${status.stt.rtf_last != null ? `, last RTF ${status.stt.rtf_last}` : ''}` : '',
      ].filter(Boolean).join(' ')
  const act = action === 'mute' ? mute : action === 'unmute' ? unmute : action === 'listen' ? start : undefined

  return (
    <Tooltip label={tip} multiline w={260} openDelay={300}>
      <button
        onClick={act}
        disabled={!act}
        aria-label={`microphone: ${label}${action ? ` (tap to ${action})` : ''}`}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] transition-colors ${tone}`}
      >
        <span aria-hidden className={`w-2 h-2 rounded-full ${dot}`} />
        <span className="hidden sm:inline">{label}</span>
        {action && <span className="font-semibold">{action === 'listen' ? 'listen' : action}</span>}
      </button>
    </Tooltip>
  )
}
