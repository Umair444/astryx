import { onDictation, setDictationMuted, startDictation, stopDictation } from '../dictate'

/* THE EAR of Talk: turns the owner's speech into finished turns. The workspace already holds one owner-approved,
   capped speech-to-text session (chat/dictate.ts: a transcription-only realtime session minted by the observatory,
   /api/chat/dictate/session, on the shared voice ledger), and its server-side voice detection already cuts speech
   into utterances: each completed transcription IS a turn. Talk adds nothing on the server.

   An engine is an interface so the overlay never knows where words come from: the browser tests hand in a fake
   (window.__astryxTalkEngine, honoured only in a dev build) and never open a microphone or a session. */

export type EarPhase = 'connecting' | 'live' | 'error' | 'idle'
export interface EarHooks {
  phase: (p: EarPhase, error?: string) => void
  partial: (text: string) => void                  // words so far in the current utterance
  turn: (text: string) => void                     // a finished utterance
  level: (n: number) => void                       // the mic, 0..1
}
export interface Ear { start: (h: EarHooks) => void; mute: (on: boolean) => void; stop: () => void }

export function dictationEar(): Ear {
  let off: (() => void) | null = null
  let on = false                                   // a word flushed after stop() is never a turn
  return {
    start(h) {
      let last = ''
      stopDictation()                                // a dictation already running in the box ends (its words stay there)
      on = true
      off = onDictation((s) => {
        h.level(s.level)
        if (s.partial !== last) { last = s.partial; h.partial(s.partial) }
        h.phase(s.phase, s.error)
      })
      void startDictation((text) => { if (on) h.turn(text) })
    },
    mute: (m) => setDictationMuted(m),
    stop() { on = false; off?.(); off = null; stopDictation() },
  }
}

/* the ear to use: the real one, or (dev builds only) a test's fake */
export function makeEar(): Ear {
  const fake = import.meta.env.DEV ? (window as unknown as { __astryxTalkEngine?: () => Ear }).__astryxTalkEngine : undefined
  return fake ? fake() : dictationEar()
}
