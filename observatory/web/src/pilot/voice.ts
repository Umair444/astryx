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
   It opens only from the owner's tap (a trusted click starts connect(): C3's transient activation).

   THE CALL (iteration 17): one call, from every page and the chat. connect({agent}) mints the session in that agent's
   persona and voice (the server reads its charter's one-line role). While live, the screen is told to the model as a
   short system item, on connect and whenever the page changes (debounced, deduped): collectScreen() → the egress
   projection (masked, capped to SCREEN_BUDGET) → screenLine(); nothing else about the page leaves. A write the model
   asks for parks for the owner's tap; when the tap (or "Not now") settles it, the model is told which, so it never
   claims a send that didn't happen. */
import { useSyncExternalStore } from 'react'
import { apiPost } from '../api'
import { onPilotPending, pilot } from '.'
import { functionOutput, project, screenLine } from './egress'
import type { Json } from './core'
import { collectScreen } from './screenDom'
import { onChatChange } from './chatctl'
import { avatar } from './avatarBus'

export type Phase = 'idle' | 'connecting' | 'live' | 'error'
export type Mood = 'idle' | 'listening' | 'thinking' | 'speaking' | 'working'
export interface VoiceState { phase: Phase; mood: Mood; error: string; minutes: number; cap: number; heard: string; said: string; acting: string; agent: string; since: number; muted: boolean }

const IDLE_MS = 60_000
let st: VoiceState = { phase: 'idle', mood: 'idle', error: '', minutes: 0, cap: 60, heard: '', said: '', acting: '', agent: 'seed', since: 0, muted: false }
export const voiceState = () => st
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
function toProvider(ev: object) {
  if (stubLine) { stubLine.send(ev); return }
  if (dc?.readyState === 'open') dc.send(JSON.stringify(ev))
}

/* ---- the screen, told to the model (iteration 17) */
let lastScreen = ''
let screenTimer: ReturnType<typeof setTimeout> | null = null
let offScreen: (() => void) | null = null
const viewName = () => (location.hash.replace(/^#\/?/, '').split(/[/?]/)[0] || 'floor')
function pushScreen() {
  screenTimer = null
  if (st.phase !== 'live') return
  const line = screenLine(project('read_screen', collectScreen(viewName()) as unknown as Json))   // masked + capped (egress)
  if (!line || line === lastScreen) return
  lastScreen = line
  toProvider({ type: 'conversation.item.create', item: { type: 'message', role: 'system',
    content: [{ type: 'input_text', text: `The owner's screen now (personal numbers masked): ${line}` }] } })
}
/** Something on the page changed: tell the model, once things settle. */
export function screenChanged(now = false) {
  if (st.phase !== 'live') return
  if (screenTimer) clearTimeout(screenTimer)
  screenTimer = setTimeout(pushScreen, now ? 50 : 1200)
}
function watchScreen(on: boolean) {
  offScreen?.(); offScreen = null
  if (screenTimer) clearTimeout(screenTimer)
  screenTimer = null
  lastScreen = ''
  if (!on) return
  const f = () => screenChanged()
  addEventListener('hashchange', f)
  const off = onChatChange(f)
  offScreen = () => { removeEventListener('hashchange', f); off() }
  screenChanged(true)
}
const touch = () => { lastActive = Date.now() }

function rms(an: AnalyserNode | null) {
  if (!an) return 0
  const b = new Uint8Array(an.fftSize)
  an.getByteTimeDomainData(b)
  let s = 0
  for (const v of b) { const x = (v - 128) / 128; s += x * x }
  return Math.min(1, Math.sqrt(s / b.length) * 3.2)
}
export const levels = {
  mic: () => (stubLine?.levels ? stubLine.levels.mic() : st.muted ? 0 : rms(micAn)),
  out: () => (stubLine?.levels ? stubLine.levels.out() : rms(outAn)),
}
/** Mute the mic for this call (the session stays; the model hears silence). */
export function setMuted(on: boolean) {
  mic?.getTracks().forEach((t) => { t.enabled = !on })
  patch({ muted: on })
}

interface Minted { value: string; model: string; usage_id: number; minutes_today: number; cap: number; calls_url: string; agent?: string }
export interface ConnectOpts { agent?: string; brief?: string }

/** The WebRTC layer, swappable in a DEV build only (the call's screenshots and browser tests stub it: no mic, no
 *  mint, no spend). A production build never reads the hook. */
type Stub = { connect: (o: ConnectOpts) => { onEvent: (f: (ev: any) => void) => void; send: (ev: object) => void; close: () => void; levels?: { mic: () => number; out: () => number } } }
const stubbed = (): Stub | undefined =>
  ((import.meta as unknown as { env: { DEV: boolean } }).env.DEV ? (window as unknown as { __callStub?: Stub }).__callStub : undefined)
let stubLine: ReturnType<Stub['connect']> | null = null

export async function connect(arg?: string | ConnectOpts): Promise<void> {
  if (st.phase === 'connecting' || st.phase === 'live') return
  const o: ConnectOpts = typeof arg === 'string' ? { brief: arg } : arg ?? {}
  const agent = o.agent || 'seed'
  patch({ phase: 'connecting', mood: 'thinking', error: '', heard: '', said: '', acting: '', agent, muted: false })
  const stub = stubbed()
  if (stub) {                                         // a DEV build's stub: the same events, no mic, no mint
    stubLine = stub.connect({ ...o, agent })
    stubLine.onEvent((ev) => onEvent(ev))
    connectedAt = Date.now(); touch()
    patch({ phase: 'live', mood: 'listening', since: connectedAt })
    watchScreen(true)
    return
  }
  try {
    // the mic first: if the owner refuses it, nothing is minted (no spend for a session that can't hear)
    try {
      mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    } catch (e) {
      throw new Error(e instanceof DOMException && e.name === 'NotAllowedError' ? 'the microphone is blocked for this page' : 'no microphone could be opened')
    }
    let m: Minted
    try { m = await apiPost<Minted>('/pilot/voice/session', { agent }) } catch (e) {
      const code = String(e).match(/: (\d+)$/)?.[1]
      throw new Error(code === '429' ? "today's voice minutes are used up" : code === '403' ? 'voice is owner-only' : code === '503' ? 'no OpenAI key is configured' : code === '400' ? `no agent named ${agent}` : 'the voice service refused to start')
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
      patch({ phase: 'live', mood: 'listening', since: connectedAt })
      watchScreen(true)
      const brief = o.brief
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
  watchScreen(false)
  try { stubLine?.close() } catch { /* closing */ }
  stubLine = null
  offPending?.(); offPending = null
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
  patch({ phase: note && had ? 'idle' : st.phase === 'error' ? 'error' : 'idle', mood: 'idle', error: note && had ? note : st.error, since: 0, muted: false })
  avatar.home()
}

/* a write the model asked for is parked for the owner's tap: when the tap (or "Not now") settles it, say which */
let offPending: (() => void) | null = null
function watchConfirm(action: string, t0: number) {
  offPending?.()
  const settle = () => {
    if (pilot.pending()) return                     // still waiting (or replaced: the newer one is watched instead)
    offPending?.(); offPending = null
    const ran = pilot.ran().some((r) => r.action === action && r.at >= t0)
    toProvider({ type: 'conversation.item.create', item: { type: 'message', role: 'system', content: [{ type: 'input_text',
      text: ran ? `The owner tapped Allow: ${action.replace(/_/g, ' ')} ran.` : `The owner did not allow ${action.replace(/_/g, ' ')}; nothing was done.` }] } })
    if (!responding) toProvider({ type: 'response.create' })
  }
  offPending = onPilotPending(() => setTimeout(settle, 0))
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
    if (!a.agent) a.agent = st.agent
    try { await apiPost('/room/ask', { agent: a.agent, message: a.message }) } catch { ok = false }
    toProvider({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId,
      output: JSON.stringify(ok ? { ok: true, note: `asked ${a.agent}; their answer will be spoken in the room in their own voice` } : { ok: false, error: 'could not reach the room' }) } })
    patch({ acting: '' })
    return
  }
  const out = args === null
    ? ({ status: 'refused', action: name, reason: 'arguments were not valid JSON' } as const)
    : await pilot.room.run(name, args)
  if (out.status === 'pending_owner_confirm') {
    watchConfirm(name, Date.now() - 1000)
    // the figure steps back home and says what it waits for: parked ON the prompt it would hide the words to be sent
    avatar.point(null, 'waiting for your tap on Confirm')
  }
  else if (out.status === 'done' && !['read_screen', 'get_view_state', 'get_usage', 'list_goals', 'point_at', 'dance'].includes(name)) avatar.cheer()
  if (out.status === 'done' && name !== 'read_screen') screenChanged()
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
      responding = true; touch(); patch({ said: '' }); break
    case 'output_audio_buffer.started':
      touch(); patch({ mood: 'speaking' }); break
    case 'output_audio_buffer.stopped':
      touch(); patch({ mood: 'listening' }); break
    case 'response.output_audio_transcript.delta':
      patch({ said: (st.said + String(ev.delta ?? '')).slice(-300) }); break
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
  event: (ev: { type: string }) => onEvent(ev),
}
