// The realtime voice engine: one module-level session (OpenAI gpt-realtime over WebRTC) that
// survives navigation. The UI (VoiceDock) only renders this state; nothing here touches React.
//
//   mint     POST /api/voice/session → ephemeral client secret (the real key never reaches us)
//   connect  RTCPeerConnection: mic track up, model audio down, 'oai-events' data channel;
//            SDP offer → POST https://api.openai.com/v1/realtime/calls (Bearer ephemeral)
//   tools    the model calls functions; they run HERE against the canvas API, the result goes back
//            as a function_call_output item + response.create
//   spend    cumulative connected seconds → POST /api/voice/usage every 30s and on hangup; the
//            server says when the day's cap is spent and we hang up. 10 quiet minutes → hang up.
import { useSyncExternalStore } from 'react'
import { ApiError, BASE, get, post } from './api'
import { getState, onMessage, refreshLists } from './store'
import { go } from './nav'
import type { Msg } from './types'

export type Phase = 'idle' | 'connecting' | 'live' | 'error'
export interface Ask { id: string; agent: string; thread: string; label: string; since: number; late?: boolean }

export interface VoiceState {
  phase: Phase
  expanded: boolean
  muted: boolean
  you: string             // live caption of the owner's words (input transcription)
  ai: string              // live caption of the assistant's words (output transcript)
  speaking: 'you' | 'ai' | null
  asks: Ask[]             // tool activity in flight
  note: string            // a short status line ("opened Org pulse", errors…)
  minutes: number
  cap: number
  allow: string[]
  startedAt: number
  trace: string[]         // last event TYPES only (no content) — for debugging/tests
}

let st: VoiceState = {
  phase: 'idle', expanded: false, muted: false, you: '', ai: '', speaking: null, asks: [], note: '',
  minutes: 0, cap: 60, allow: [], startedAt: 0, trace: [],
}
const subs = new Set<() => void>()
function patch(p: Partial<VoiceState> | ((s: VoiceState) => Partial<VoiceState>)) {
  st = { ...st, ...(typeof p === 'function' ? p(st) : p) }
  subs.forEach(f => f())
}
export const voiceState = () => st
export function useVoice<T>(sel: (s: VoiceState) => T): T {
  return useSyncExternalStore(cb => { subs.add(cb); return () => { subs.delete(cb) } }, () => sel(st))
}
export function setExpanded(expanded: boolean) { patch({ expanded }) }

// ------------------------------------------------------------------ session
interface Minted { value: string; model: string; usage_id: number; allow: string[]; home: string; minutes_today: number; cap: number; calls_url: string }

let pc: RTCPeerConnection | null = null
let dc: RTCDataChannel | null = null
let mic: MediaStream | null = null
let audioEl: HTMLAudioElement | null = null
let ctx: AudioContext | null = null
let micAn: AnalyserNode | null = null
let outAn: AnalyserNode | null = null
let usageId = 0
let connectedAt = 0
let lastActive = 0
let timers: number[] = []
let responding = false
let wantResponse = false
let offLate: (() => void) | null = null
const seenCalls = new Set<string>()
const threadFor: Record<string, string> = {}          // agent → this session's thread with it
const lateWatch = new Map<string, { agent: string; thread: string }>()   // timed-out asks still listening

const IDLE_MS = 10 * 60_000
const ASK_TIMEOUT = 120_000

function trace(t: string) { if (!t.endsWith('.delta')) patch(s => ({ trace: [...s.trace.slice(-79), t] })) }
function send(ev: object) { if (dc?.readyState === 'open') dc.send(JSON.stringify(ev)) }
function touch() { lastActive = Date.now() }

/** response.create, but never on top of an active response (the API refuses that) */
function requestResponse() {
  if (responding) { wantResponse = true; return }
  responding = true
  send({ type: 'response.create' })
}

function plain(md: string) {
  return md.replace(/\[\[(file|poll):[^\]]*\]\]/g, '').replace(/```[\s\S]*?```/g, ' (code omitted) ')
    .replace(/`([^`]*)`/g, '$1').replace(/\*\*|__|[*_#>]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\s+/g, ' ').trim().slice(0, 3000)
}

/** Unavailable realtime (no key, cap, guest, network) → the caller falls back to local VoiceMode. */
export type ConnectResult = { ok: true } | { ok: false; reason: string }

export async function connect(focusThread?: string): Promise<ConnectResult> {
  if (st.phase === 'live' || st.phase === 'connecting') { patch({ expanded: true }); return { ok: true } }
  // created inside the tap's gesture so the browser lets it run
  ctx = new AudioContext()
  patch({ phase: 'connecting', expanded: true, note: '', you: '', ai: '', asks: [], muted: false, trace: [] })
  let m: Minted
  try {
    m = await post<Minted>('/voice/session')
  } catch (e) {
    cleanup()
    const reason = e instanceof ApiError ? e.message : 'realtime voice unreachable'
    patch({ phase: 'idle', expanded: false, note: reason })
    return { ok: false, reason }
  }
  usageId = m.usage_id
  patch({ allow: m.allow, minutes: m.minutes_today, cap: m.cap })
  try {
    mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    pc = new RTCPeerConnection()
    audioEl = new Audio()
    audioEl.autoplay = true
    pc.ontrack = e => {
      const stream = e.streams[0] ?? new MediaStream([e.track])
      audioEl!.srcObject = stream
      audioEl!.play().catch(() => {})
      try {
        outAn = ctx!.createAnalyser(); outAn.fftSize = 512
        ctx!.createMediaStreamSource(stream).connect(outAn)      // analyse only; the <audio> plays it
      } catch { /* levels are decoration */ }
    }
    pc.onconnectionstatechange = () => {
      trace('pc.' + pc?.connectionState)
      if (pc?.connectionState === 'failed') hangup('the connection dropped')
    }
    mic.getTracks().forEach(t => pc!.addTrack(t, mic!))
    micAn = ctx.createAnalyser(); micAn.fftSize = 512
    ctx.createMediaStreamSource(mic).connect(micAn)
    ctx.resume().catch(() => {})

    dc = pc.createDataChannel('oai-events')
    dc.onopen = () => {
      trace('dc.open')
      connectedAt = Date.now(); touch()
      patch({ phase: 'live', startedAt: connectedAt })
      const agent = focusThread ? getState().threads.find(t => t.thread === focusThread)?.agent : undefined
      if (agent && m.allow.includes(agent)) {
        threadFor[agent] = focusThread!
        send({ type: 'conversation.item.create', item: { type: 'message', role: 'system',
          content: [{ type: 'input_text', text: `The owner opened voice from his conversation with ${agent}; unless he says otherwise, ask ${agent}.` }] } })
      }
    }
    dc.onmessage = e => { try { onEvent(JSON.parse(e.data)) } catch { /* not json */ } }
    dc.onclose = () => { trace('dc.close'); if (st.phase === 'live') hangup('the session ended') }

    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    const r = await fetch(m.calls_url, {
      method: 'POST', body: offer.sdp,
      headers: { authorization: `Bearer ${m.value}`, 'content-type': 'application/sdp' },
    })
    if (!r.ok) throw new Error(`OpenAI answered ${r.status}`)
    await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() })
  } catch (e) {
    const reason = e instanceof DOMException && e.name === 'NotAllowedError'
      ? 'microphone permission denied' : e instanceof Error ? e.message : 'connection failed'
    cleanup()
    reportUsage(true)
    patch({ phase: 'idle', expanded: false, note: reason })
    return { ok: false, reason }
  }
  timers.push(window.setInterval(() => reportUsage(false), 30_000))
  timers.push(window.setInterval(() => {
    if (Date.now() - lastActive > IDLE_MS) hangup('hung up after ten quiet minutes')
  }, 5_000))
  offLate = onMessage(lateReply)
  window.addEventListener('pagehide', onPageHide)
  return { ok: true }
}

function onPageHide() { reportUsage(true) }

function seconds() { return connectedAt ? (Date.now() - connectedAt) / 1000 : 0 }

async function reportUsage(final: boolean) {
  if (!usageId) return
  const body = JSON.stringify({ id: usageId, seconds: seconds() })
  try {
    const r = await fetch(BASE + 'api/voice/usage', {
      method: 'POST', body, keepalive: final, credentials: 'same-origin',
      headers: { 'x-astryx': '1', 'content-type': 'application/json' },
    })
    if (!r.ok) return
    const u = await r.json() as { minutes_today: number; cap: number; over: boolean }
    patch({ minutes: u.minutes_today, cap: u.cap })
    if (u.over && !final && st.phase === 'live') hangup(`today's voice cap is spent (${Math.round(u.cap)} minutes)`)
  } catch { /* the next heartbeat retries */ }
}

function cleanup() {
  timers.forEach(clearInterval); timers = []
  offLate?.(); offLate = null
  window.removeEventListener('pagehide', onPageHide)
  try { dc?.close() } catch { /* already closed */ }
  try { pc?.getSenders().forEach(s => s.track?.stop()); pc?.close() } catch { /* already closed */ }
  mic?.getTracks().forEach(t => t.stop())
  if (audioEl) { audioEl.srcObject = null; audioEl = null }
  ctx?.close().catch(() => {})
  pc = null; dc = null; mic = null; ctx = null; micAn = null; outAn = null
  responding = false; wantResponse = false
  seenCalls.clear(); lateWatch.clear()
  for (const k of Object.keys(threadFor)) delete threadFor[k]
}

export function hangup(note = '') {
  if (st.phase === 'idle') return
  reportUsage(true)                                    // builds its body synchronously, before cleanup
  usageId = 0
  cleanup()
  connectedAt = 0
  patch({ phase: 'idle', speaking: null, asks: [], note, expanded: note ? st.expanded : false })
}

export function setMuted(muted: boolean) {
  mic?.getAudioTracks().forEach(t => { t.enabled = !muted })
  patch({ muted })
}

// ---------------------------------------------------------------- levels
const buf = new Uint8Array(512)
function rms(an: AnalyserNode | null) {
  if (!an) return 0
  an.getByteTimeDomainData(buf)
  let s = 0
  for (let i = 0; i < an.fftSize; i++) { const v = (buf[i] - 128) / 128; s += v * v }
  return Math.min(1, Math.sqrt(s / an.fftSize) * 4)
}
/** Read by the orb each animation frame — never through React state. */
export function levels() { return { mic: st.muted ? 0 : rms(micAn), out: rms(outAn) } }

// ---------------------------------------------------------------- events
function onEvent(ev: { type: string; [k: string]: any }) {
  trace(ev.type)
  switch (ev.type) {
    case 'input_audio_buffer.speech_started':
      touch(); patch({ speaking: 'you', you: '' })
      break
    case 'input_audio_buffer.speech_stopped':
      touch(); patch({ speaking: null })
      break
    case 'conversation.item.input_audio_transcription.delta':
      patch(s => ({ you: (s.you + (ev.delta ?? '')).slice(-400) }))
      break
    case 'conversation.item.input_audio_transcription.completed':
      patch({ you: (ev.transcript ?? '').trim() })
      break
    case 'response.created':
      responding = true
      patch({ ai: '' })
      break
    case 'response.output_audio_transcript.delta':
    case 'response.output_text.delta':
      touch(); patch(s => ({ ai: (s.ai + (ev.delta ?? '')).slice(-600) }))
      break
    case 'output_audio_buffer.started':                 // WebRTC: playback, not generation
      touch(); patch({ speaking: 'ai' })
      break
    case 'output_audio_buffer.stopped':
    case 'output_audio_buffer.cleared':
      touch(); patch({ speaking: null })
      break
    case 'response.function_call_arguments.done':
      runTool(ev.call_id, ev.name, ev.arguments)
      break
    case 'response.done': {
      responding = false
      // belt and braces: a function call we somehow didn't see stream
      for (const it of ev.response?.output ?? []) if (it.type === 'function_call') runTool(it.call_id, it.name, it.arguments)
      if (ev.response?.status === 'failed') patch({ note: ev.response?.status_details?.error?.message ?? 'the model failed a turn' })
      if (wantResponse) { wantResponse = false; requestResponse() }
      break
    }
    case 'error':
      patch({ note: ev.error?.message ?? 'realtime error' })
      if (/active response/i.test(ev.error?.message ?? '')) { wantResponse = true }
      break
  }
}

function toolResult(callId: string, output: unknown) {
  send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId, output: JSON.stringify(output) } })
  requestResponse()
}

function addAsk(a: Ask) { patch(s => ({ asks: [...s.asks.filter(x => x.id !== a.id), a] })) }
function dropAsk(id: string) { patch(s => ({ asks: s.asks.filter(x => x.id !== id) })) }

async function runTool(callId: string, name: string, raw: string) {
  if (!callId || seenCalls.has(callId)) return
  seenCalls.add(callId)
  touch()
  let args: Record<string, any> = {}
  try { args = JSON.parse(raw || '{}') } catch { /* empty args */ }
  try {
    toolResult(callId, await TOOLS[name]?.(args, callId) ?? { error: `no tool ${name}` })
  } catch (e) {
    const spoken = e instanceof ApiError ? (e as ApiError & { spoken?: string }).spoken ?? e.message : 'that failed'
    toolResult(callId, { error: spoken })
  }
}

/** POST that keeps the server's `spoken` refusal (the tier fence explains itself out loud) */
async function vpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + 'api' + path, {
    method: 'POST', credentials: 'same-origin', body: JSON.stringify(body),
    headers: { 'x-astryx': '1', 'content-type': 'application/json' },
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) { const e = new ApiError(r.status, j.error ?? `${r.status}`) as ApiError & { spoken?: string }; e.spoken = j.spoken; throw e }
  return j as T
}

const currentCanvas = () => { const m = location.hash.match(/#\/?canvas\/(\d+)/); return m ? Number(m[1]) : undefined }

const TOOLS: Record<string, (a: Record<string, any>, callId: string) => Promise<unknown>> = {
  async ask_agent({ agent, message }, callId) {
    const name = String(agent ?? '').trim().toLowerCase().replace(/^@/, '')
    if (!st.allow.includes(name)) {
      return { refused: true, say: `${name || 'That agent'} is outside what the voice may reach — personal matters stay in chat.` }
    }
    // listen BEFORE posting, so a fast reply can't slip past
    const got: Msg[] = []
    let wake: (() => void) | null = null
    const off = onMessage(m => { got.push(m); wake?.() })
    try {
      const r = await vpost<{ thread: string; agent: string }>('/voice/ask', { agent: name, message: String(message ?? ''), thread: threadFor[name] })
      threadFor[name] = r.thread
      addAsk({ id: callId, agent: name, thread: r.thread, label: `asking ${name}`, since: Date.now() })
      const deadline = Date.now() + ASK_TIMEOUT
      for (;;) {
        const hit = got.find(m => m.thread === r.thread && m.from === name)
        if (hit) { dropAsk(callId); touch(); return { agent: name, reply: plain(hit.body) } }
        const left = deadline - Date.now()
        if (left <= 0 || st.phase !== 'live') break
        await new Promise<void>(res => { wake = res; setTimeout(res, Math.min(left, 5000)) })
      }
      lateWatch.set(r.thread, { agent: name, thread: r.thread })
      patch(s => ({ asks: s.asks.map(x => x.id === callId ? { ...x, late: true, label: `${name} is still working` } : x) }))
      return { status: 'still working', agent: name, thread: r.thread, say: `${name} is still on it; the reply will be announced when it lands.` }
    } finally { off() }
  },

  async change_canvas({ request, canvas_id, element }, callId) {
    const id = Number(canvas_id) || currentCanvas()
    if (!id) return { error: 'no canvas is on screen — ask which canvas, or open one first' }
    const r = await vpost<{ agent: string; title: string; thread: string }>(`/voice/canvas/${id}/ask`, { text: String(request ?? ''), element })
    addAsk({ id: callId, agent: r.agent, thread: r.thread, label: `${r.agent} is repainting`, since: Date.now() })
    setTimeout(() => dropAsk(callId), 90_000)
    return { status: 'asked', agent: r.agent, canvas: r.title, say: `${r.agent} is on it; the change paints live on screen.` }
  },

  async create_canvas({ title, brief }) {
    const c = await vpost<{ id: number; agent: string; title: string }>('/canvases', { title: String(title ?? 'Untitled'), brief: String(brief ?? '') })
    refreshLists().catch(() => {})
    go(`/canvas/${c.id}`)
    patch({ note: `opened “${c.title}”` })
    return { status: 'created and opened', id: c.id, painter: c.agent, say: `${c.agent} is painting it now.` }
  },

  async open_view({ view, id }) {
    const s = getState()
    if (view === 'home') { go('/'); return { ok: true, view: 'home' } }
    if (view === 'canvas') {
      const q = String(id ?? '').toLowerCase()
      const c = /^\d+$/.test(q) ? s.canvases.find(x => x.id === Number(q)) : s.canvases.find(x => x.title.toLowerCase().includes(q))
      if (!c) return { error: 'no such canvas', canvases: s.canvases.filter(x => x.tier !== 'personal').slice(0, 8).map(x => x.title) }
      go(`/canvas/${c.id}`); return { ok: true, opened: c.title }
    }
    const q = String(id ?? '').toLowerCase()
    const t = s.threads.find(x => x.thread === id) ?? (threadFor[q] ? { thread: threadFor[q] } : null)
    if (t) { go(`/chat/${encodeURIComponent(t.thread)}`); return { ok: true, opened: 'chat' } }
    if (q && s.agents.some(a => a.name === q)) { go(`/new/${encodeURIComponent(q)}`); return { ok: true, opened: `a new chat with ${q}` } }
    go('/'); return { ok: true, opened: 'home' }
  },

  org_status: () => get('/voice/org'),
  list_agents: () => get('/voice/agents'),
}

/** a reply to an ask that timed out: say it the moment it lands */
function lateReply(m: Msg) {
  const w = m.thread ? lateWatch.get(m.thread) : undefined
  if (!w || m.from !== w.agent || st.phase !== 'live') return
  lateWatch.delete(m.thread!)
  patch(s => ({ asks: s.asks.filter(x => x.thread !== w.thread) }))
  touch()
  send({ type: 'conversation.item.create', item: { type: 'message', role: 'system',
    content: [{ type: 'input_text', text: `Late reply from ${w.agent} (tell the owner now, briefly): ${plain(m.body)}` }] } })
  requestResponse()
}

/** A typed turn over the data channel (the same path the mic takes after transcription). */
export function sendText(text: string) {
  touch()
  send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } })
  requestResponse()
}

// a narrow handle for tests and the console: state snapshot + a typed turn. No credentials here.
;(window as unknown as { astryxVoice: object }).astryxVoice = {
  state: () => ({ ...st, pc: pc?.connectionState ?? null, dc: dc?.readyState ?? null }),
  sendText,
}
