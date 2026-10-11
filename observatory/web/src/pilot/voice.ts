/* plan-9000 S2: the observatory pilot's realtime voice session (OpenAI gpt-realtime over WebRTC).

   mint    POST /api/pilot/voice/session (owner-only) → an EPHEMERAL client secret; the SDP exchange happens here
           against the provider's calls URL with that secret. The real key never reaches the browser.
   tools   every function call the model makes runs through pilot.room, the ROOM principal's entry point:
           views run, reads go through the egress projection (egress.ts), writes and actuates wait for the
           owner's tap on <PilotConfirm/>. Each output goes back as a function_call_output via toProvider(),
           the ONE send path to the provider (C1).
   spend   cumulative connected seconds → /api/pilot/voice/usage every 30s and on hangup (shared cap, C3/C4);
           the session closes itself after IDLE_MS with no speech and no response (the token-eating guard), and
           when the server says today's cap is spent.
   It opens only from the owner's tap (a trusted click starts connect(): C3's transient activation). */
import { useSyncExternalStore } from 'react'
import { apiPost } from '../api'
import { pilot } from '.'
import { functionOutput } from './egress'
import type { Json } from './core'

export type Phase = 'idle' | 'connecting' | 'live' | 'error'
export type Mood = 'idle' | 'listening' | 'thinking' | 'speaking' | 'working'
export interface VoiceState { phase: Phase; mood: Mood; error: string; minutes: number; cap: number; heard: string; said: string; acting: string }

const IDLE_MS = 60_000
let st: VoiceState = { phase: 'idle', mood: 'idle', error: '', minutes: 0, cap: 60, heard: '', said: '', acting: '' }
const subs = new Set<() => void>()
const patch = (p: Partial<VoiceState>) => { st = { ...st, ...p }; subs.forEach((f) => f()) }
/** The live voice owns the room while it's on: the ear holds its uploads (components/EarControl.tsx), so one
 *  sentence isn't heard twice and forwarded to an agent behind the live conversation's back (owner, 10-11). */
export function liveOn(): boolean { return st.phase === 'live' || st.phase === 'connecting' }
export function useVoice(): VoiceState { return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f) } }, () => st) }

let pc: RTCPeerConnection | null = null
let dc: RTCDataChannel | null = null
let mic: MediaStream | null = null
let audio: HTMLAudioElement | null = null
let ctx: AudioContext | null = null
let micAn: AnalyserNode | null = null
let outAn: AnalyserNode | null = null
let usageId = 0
let connectedAt = 0
let lastActive = 0
let beat: ReturnType<typeof setInterval> | null = null
let responding = false
const done = new Set<string>()

/** The ONE path from this page to the provider. */
function toProvider(ev: object) { if (dc?.readyState === 'open') dc.send(JSON.stringify(ev)) }
const touch = () => { lastActive = Date.now() }

function rms(an: AnalyserNode | null) {
  if (!an) return 0
  const b = new Uint8Array(an.fftSize)
  an.getByteTimeDomainData(b)
  let s = 0
  for (const v of b) { const x = (v - 128) / 128; s += x * x }
  return Math.min(1, Math.sqrt(s / b.length) * 3.2)
}
export const levels = { mic: () => rms(micAn), out: () => rms(outAn) }

interface Minted { value: string; model: string; usage_id: number; minutes_today: number; cap: number; calls_url: string }

export async function connect(brief?: string): Promise<void> {
  if (st.phase === 'connecting' || st.phase === 'live') return
  patch({ phase: 'connecting', mood: 'thinking', error: '', heard: '', said: '', acting: '' })
  try {
    // the mic first: if the owner refuses it, nothing is minted (no spend for a session that can't hear)
    mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    let m: Minted
    try { m = await apiPost<Minted>('/pilot/voice/session', {}) } catch (e) {
      const code = String(e).match(/: (\d+)$/)?.[1]
      throw new Error(code === '429' ? "today's voice minutes are used up" : code === '403' ? 'voice is owner-only' : 'the voice service refused to start')
    }
    usageId = m.usage_id
    patch({ minutes: m.minutes_today, cap: m.cap })
    pc = new RTCPeerConnection()
    audio = new Audio()
    audio.autoplay = true
    ctx = new AudioContext()
    micAn = ctx.createAnalyser(); micAn.fftSize = 512
    ctx.createMediaStreamSource(mic).connect(micAn)
    pc.ontrack = (e) => {
      audio!.srcObject = e.streams[0]
      outAn = ctx!.createAnalyser(); outAn.fftSize = 512
      ctx!.createMediaStreamSource(e.streams[0]).connect(outAn)
    }
    for (const t of mic.getTracks()) pc.addTrack(t, mic)
    dc = pc.createDataChannel('oai-events')
    dc.onmessage = (e) => { try { onEvent(JSON.parse(e.data)) } catch { /* a malformed frame is dropped */ } }
    dc.onopen = () => {
      connectedAt = Date.now(); touch()
      patch({ phase: 'live', mood: 'listening' })
      if (brief) {                                    // a room agent handed over: open the live voice already briefed
        toProvider({ type: 'conversation.item.create', item: { type: 'message', role: 'system',
          content: [{ type: 'input_text', text: `An agent in the room handed you this conversation. Their brief: ${brief}` }] } })
        toProvider({ type: 'response.create' })
      }
      beat = setInterval(() => {
        reportUsage()
        if (Date.now() - lastActive > IDLE_MS && !responding) hangup('closed after a minute of quiet')
      }, 10_000)
    }
    pc.onconnectionstatechange = () => { if (pc && ['failed', 'closed'].includes(pc.connectionState)) hangup('the connection dropped') }
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    const r = await fetch(m.calls_url, { method: 'POST', body: offer.sdp, headers: { authorization: `Bearer ${m.value}`, 'content-type': 'application/sdp' } })
    if (!r.ok) throw new Error(`the voice provider refused the call (${r.status})`)
    await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() })
    addEventListener('pagehide', onPageHide)
  } catch (e) {
    cleanup()
    patch({ phase: 'error', mood: 'idle', error: e instanceof Error ? e.message : String(e) })
  }
}

const seconds = () => (connectedAt ? (Date.now() - connectedAt) / 1000 : 0)
let lastReport = 0
async function reportUsage() {
  if (!usageId) return
  const s = seconds()
  if (s - lastReport < 5 && st.phase === 'live') return
  lastReport = s
  try {
    const u = await apiPost<{ minutes_today: number; cap: number; over: boolean }>('/pilot/voice/usage', { id: usageId, seconds: s })
    patch({ minutes: u.minutes_today, cap: u.cap })
    if (u.over && st.phase === 'live') hangup("today's voice minutes are used up")
  } catch { /* the next beat retries */ }
}
function onPageHide() {
  if (!usageId) return
  const key = localStorage.getItem('obs_key') ?? ''
  fetch('/api/pilot/voice/usage', { method: 'POST', keepalive: true, headers: { 'content-type': 'application/json', 'x-obs-key': key }, body: JSON.stringify({ id: usageId, seconds: seconds() }) })
}

function cleanup() {
  if (beat) clearInterval(beat)
  beat = null
  removeEventListener('pagehide', onPageHide)
  try { dc?.close() } catch { /* closing */ }
  try { pc?.close() } catch { /* closing */ }
  mic?.getTracks().forEach((t) => t.stop())
  try { ctx?.close() } catch { /* closing */ }
  if (audio) audio.srcObject = null
  pc = null; dc = null; mic = null; ctx = null; micAn = null; outAn = null; audio = null
  responding = false
  done.clear()
}

export function hangup(note = '') {
  const had = st.phase === 'live' || st.phase === 'connecting'
  if (had) { lastReport = -1e9; reportUsage().finally(() => { usageId = 0; connectedAt = 0 }) }
  cleanup()
  patch({ phase: note && had ? 'idle' : st.phase === 'error' ? 'error' : 'idle', mood: 'idle', error: note && had ? note : st.error })
}

async function runTool(callId: string, name: string, raw: string) {
  if (done.has(callId)) return
  done.add(callId)
  touch()
  let args: unknown = {}
  try { args = raw ? JSON.parse(raw) : {} } catch { args = null }
  patch({ mood: 'working', acting: name })
  if (name === 'ask_agent' && args && typeof args === 'object') {   // the room: a request to an agent, on the wire
    const a = args as { agent?: string; message?: string }
    let ok = true
    try { await apiPost('/room/ask', { agent: a.agent, message: a.message }) } catch { ok = false }
    toProvider({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId,
      output: JSON.stringify(ok ? { ok: true, note: `asked ${a.agent}; their answer will be spoken in the room in their own voice` } : { ok: false, error: 'could not reach the room' }) } })
    patch({ acting: '' })
    return
  }
  const out = args === null
    ? ({ status: 'refused', action: name, reason: 'arguments were not valid JSON' } as const)
    : await pilot.room.run(name, args)
  toProvider({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId, output: JSON.stringify(functionOutput(out) as Json) } })
}

function onEvent(ev: { type: string; [k: string]: any }) {
  switch (ev.type) {
    case 'input_audio_buffer.speech_started':
      touch(); patch({ mood: 'listening' }); break
    case 'input_audio_buffer.speech_stopped':
      touch(); patch({ mood: 'thinking' }); break
    case 'conversation.item.input_audio_transcription.completed':
      patch({ heard: String(ev.transcript ?? '').slice(0, 300) }); break
    case 'response.created':
      responding = true; touch(); break
    case 'output_audio_buffer.started':
      touch(); patch({ mood: 'speaking' }); break
    case 'output_audio_buffer.stopped':
      touch(); patch({ mood: 'listening' }); break
    case 'response.output_audio_transcript.done':
      patch({ said: String(ev.transcript ?? '').slice(0, 300) }); break
    case 'response.done': {
      responding = false
      touch()
      const calls = (ev.response?.output ?? []).filter((it: any) => it.type === 'function_call')
      if (calls.length) {
        Promise.all(calls.map((c: any) => runTool(c.call_id, c.name, c.arguments))).then(() => {
          patch({ acting: '' })
          toProvider({ type: 'response.create' })
        })
      } else if (st.mood !== 'speaking') patch({ mood: 'listening' })
      break
    }
    case 'error':
      patch({ error: String(ev.error?.message ?? 'voice error').slice(0, 200) }); break
  }
}

// the live harness (tests/pilot_voice_live.mjs) speaks to the model in TEXT, the way a transcript would arrive; a dev
// server only: a production build drops this block
if ((import.meta as unknown as { env: { DEV: boolean } }).env.DEV) (window as unknown as Record<string, unknown>).__pilotVoice = {
  state: () => st,
  say: (text: string) => {
    touch()
    toProvider({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } })
    toProvider({ type: 'response.create' })
  },
  hangup: () => hangup(),
}
