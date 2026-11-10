import { useSyncExternalStore } from 'react'
import { apiPost, obsKey } from '../api'

/* Dictation for /chat (plan-11884 C6): realtime speech-to-text INTO the composer, never sent by itself.
   A transcription-only session (no model reply, no tools) minted by /api/chat/dictate/session through voice_mint's
   daily cap and ledger; the browser does the WebRTC exchange, as the pilot's voice does (pilot/voice.ts).
   The provider is an outside service: the composer says so while the mic is live (R6). */

export type DictPhase = 'idle' | 'connecting' | 'live' | 'error'
export interface DictState { phase: DictPhase; partial: string; error: string; level: number }
let st: DictState = { phase: 'idle', partial: '', error: '', level: 0 }
const subs = new Set<() => void>()
const patch = (p: Partial<DictState>) => { st = { ...st, ...p }; subs.forEach((f) => f()) }
export const useDictation = () => useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f) } }, () => st)

let pc: RTCPeerConnection | null = null
let mic: MediaStream | null = null
let ctx: AudioContext | null = null
let an: AnalyserNode | null = null
let usageId = 0, startedAt = 0, beat: ReturnType<typeof setInterval> | null = null, meter = 0
let onFinal: ((text: string) => void) | null = null

interface Minted { value: string; usage_id: number; calls_url: string }

export async function startDictation(final: (text: string) => void): Promise<void> {
  if (st.phase === 'live' || st.phase === 'connecting') return
  onFinal = final
  patch({ phase: 'connecting', partial: '', error: '' })
  try {
    mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    let m: Minted
    try { m = await apiPost<Minted>('/chat/dictate/session', {}) } catch (e) {
      const code = String(e).match(/: (\d+)$/)?.[1]
      throw new Error(code === '429' ? "today's voice minutes are used up" : code === '403' ? 'dictation is owner-only' : 'the speech service did not start')
    }
    usageId = m.usage_id
    pc = new RTCPeerConnection()
    for (const t of mic.getTracks()) pc.addTrack(t, mic)
    ctx = new AudioContext()
    an = ctx.createAnalyser(); an.fftSize = 512
    ctx.createMediaStreamSource(mic).connect(an)
    const buf = new Uint8Array(512)
    const tick = () => {
      if (!an) return
      an.getByteTimeDomainData(buf)
      let s = 0
      for (const v of buf) s += ((v - 128) / 128) ** 2
      patch({ level: Math.min(1, Math.sqrt(s / buf.length) * 4) })
      meter = requestAnimationFrame(tick)
    }
    const dc = pc.createDataChannel('oai-events')
    dc.onopen = () => { startedAt = Date.now(); patch({ phase: 'live' }); tick(); beat = setInterval(report, 10_000) }
    dc.onmessage = (e) => {
      let ev: { type?: string; delta?: string; transcript?: string }
      try { ev = JSON.parse(e.data) } catch { return }
      if (ev.type === 'conversation.item.input_audio_transcription.delta' && ev.delta) patch({ partial: st.partial + ev.delta })
      if (ev.type === 'conversation.item.input_audio_transcription.completed') {
        const text = (ev.transcript ?? st.partial).trim()
        patch({ partial: '' })
        if (text) onFinal?.(text)
      }
    }
    pc.onconnectionstatechange = () => { if (pc && ['failed', 'closed'].includes(pc.connectionState)) stopDictation('the connection dropped') }
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    const r = await fetch(m.calls_url, { method: 'POST', body: offer.sdp, headers: { authorization: `Bearer ${m.value}`, 'content-type': 'application/sdp' } })
    if (!r.ok) throw new Error(`the speech service refused the call (${r.status})`)
    await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() })
  } catch (e) {
    cleanup()
    patch({ phase: 'error', error: e instanceof Error ? e.message : String(e) })
  }
}

async function report() {
  if (!usageId || !startedAt) return
  try {
    const u = await apiPost<{ over: boolean }>('/chat/dictate/usage', { id: usageId, seconds: (Date.now() - startedAt) / 1000 })
    if (u.over) stopDictation("today's voice minutes are used up")
  } catch { /* the next beat retries */ }
}

function cleanup() {
  if (beat) clearInterval(beat)
  if (meter) cancelAnimationFrame(meter)
  beat = null; meter = 0
  try { pc?.close() } catch { /* closing */ }
  mic?.getTracks().forEach((t) => t.stop())
  try { ctx?.close() } catch { /* closing */ }
  pc = null; mic = null; ctx = null; an = null
}

export function stopDictation(error = '') {
  if (usageId && startedAt) {
    const id = usageId, seconds = (Date.now() - startedAt) / 1000
    fetch('/api/chat/dictate/usage', { method: 'POST', keepalive: true, headers: { 'content-type': 'application/json', 'x-obs-key': obsKey() }, body: JSON.stringify({ id, seconds }) }).catch(() => {})
  }
  usageId = 0; startedAt = 0
  const pending = st.partial.trim()
  if (pending) onFinal?.(pending)
  cleanup()
  patch({ phase: error ? 'error' : 'idle', partial: '', error, level: 0 })
}
