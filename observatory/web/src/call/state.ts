/* THE CALL (iteration 17, owner 11-11: "the realtime call from canvas, everywhere: the observatory and the chat"). One
   realtime voice session for the whole page (pilot/voice.ts), started from ONE entry point: the call button on every
   observatory page and in the chat workspace, or ⌘/Ctrl+Shift+L. Who you call: the agent of the open chat; on an
   observatory page the agent whose panel is open; else seed. This module holds that choice, the server's word on
   whether a call can start (and why not), and the dock's expanded flag. */
import { useEffect, useSyncExternalStore } from 'react'
import { api } from '../api'
import { chatCtl } from '../pilot/chatctl'
import { connect, hangup, voiceState } from '../pilot/voice'

export interface CallStatus { checked: boolean; available: boolean; reason: string; minutes: number; cap: number }

let status: CallStatus = { checked: false, available: false, reason: '', minutes: 0, cap: 60 }
let expanded = true
let selected: string | null = null
const subs = new Set<() => void>()
const tell = () => subs.forEach((f) => f())
const sub = (f: () => void) => { subs.add(f); return () => { subs.delete(f) } }

/** The observatory's selected agent (the open profile or chat sheet); the chat's own agent wins over it. */
export function setSelectedAgent(a: string | null) { selected = a }
export function callAgent(): string { return chatCtl()?.agent() ?? selected ?? 'seed' }

export async function refreshStatus(): Promise<CallStatus> {
  try {
    const s = await api<{ available: boolean; reason: string; minutes_today: number; cap: number }>('/pilot/voice/status')
    status = { checked: true, available: s.available, reason: s.reason, minutes: s.minutes_today, cap: s.cap }
  } catch (e) {
    const code = String(e).match(/: (\d+)$/)?.[1]
    status = { checked: true, available: false, reason: code === '403' ? 'the Call is not on for you' : 'the observatory is not answering', minutes: 0, cap: status.cap }
  }
  tell()
  return status
}
export function useCallStatus(): CallStatus {
  useEffect(() => {
    if (!status.checked) void refreshStatus()
    const i = setInterval(() => void refreshStatus(), 120_000)
    return () => clearInterval(i)
  }, [])
  return useSyncExternalStore(sub, () => status)
}

/* The blob's resting spot (CallBlob.tsx publishes it, viewport px): the call's figure rises from it and rests there
   between acts (CallAvatar.tsx), and the Room's idle seed yields to it (ui/room.tsx). null = no blob on screen. */
export interface Spot { x: number; y: number; size: number }
let blobSpot: Spot | null = null
export function setBlobSpot(s: Spot | null) {
  if (s === blobSpot || (s && blobSpot && s.x === blobSpot.x && s.y === blobSpot.y && s.size === blobSpot.size)) return
  blobSpot = s; tell()
}
export function useBlobSpot(): Spot | null { return useSyncExternalStore(sub, () => blobSpot) }

export function useExpanded(): boolean { return useSyncExternalStore(sub, () => expanded) }
export function setExpanded(v: boolean) { expanded = v; tell() }

/** Start a call (with the agent on screen), or, while one is live, show its dock. The click IS the activation. */
export function startCall(agent?: string) {
  const v = voiceState()
  if (v.phase === 'live' || v.phase === 'connecting') { setExpanded(true); return }
  setExpanded(true)
  void connect({ agent: agent ?? callAgent() }).then(() => void refreshStatus())
}
export function endCall() { hangup(); void refreshStatus() }
export function toggleCall() {
  const v = voiceState()
  if (v.phase === 'live' || v.phase === 'connecting') endCall(); else startCall()
}
