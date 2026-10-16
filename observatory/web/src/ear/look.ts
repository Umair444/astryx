/* hearing S1 (plan-8674): the ear pill's ONE state, read four ways (the word on the pill, the orb's tone, the sheet's
   serif line and sub line, the one action). Pure, so tests/test_ear_look.py runs this exact module under node.

   LAG IS SHOWN (seed #46317): the owner said a name and the room answered nothing, because transcription was minutes
   behind and the pill said "listening". When the ear's queue is BEHIND_S or more behind, the pill says so. */

export type Mic = 'off' | 'listening' | 'stale' | 'muted' | 'focal' | 'reverting' | 'unknown'

export interface LookIn {
  offline: boolean
  mic: Mic
  capturing: boolean                                   // this tab holds the mic and is capturing
  mine: boolean                                        // ...and the server agrees it is the holder
  hearing: boolean                                     // speech is being heard right now
  behind_s?: number | null                             // the ear's estimated transcription lag (older ears: absent)
}

export interface Look {
  word: string
  line: string
  sub: string
  tone: 'accent' | 'warn' | 'mute'
  live: boolean
  action: 'listen' | 'mute' | 'unmute' | null
}

export const BEHIND_S = 8                            // one spoken sentence at RTF ~1 is a few s: not a backlog

export function earLook(s: LookIn): Look {
  const listening = s.capturing || s.mic === 'listening'
  if (s.offline) return { word: 'ear offline', line: 'The ear is offline', tone: 'mute', live: false, action: null,
    sub: 'Nothing is being heard. The page works as normal.' }
  if (s.mic === 'muted') return { word: 'Muted', line: 'The room is muted', tone: 'warn', live: false, action: 'unmute',
    sub: 'Nothing is captured until you unmute.' }
  const held = s.mine ? 'This tab holds the mic.' : 'Muting here stops it everywhere.'
  if (listening && (s.behind_s ?? 0) >= BEHIND_S) return { word: 'catching up', line: 'Catching up…', tone: 'accent',
    live: true, action: 'mute', sub: `About ${Math.round(s.behind_s as number)} s behind the room. ${held}` }
  if (s.capturing) return { word: s.hearing ? 'hearing' : 'listening', line: s.hearing ? 'Catching that…' : 'The room is listening',
    tone: 'accent', live: true, action: 'mute', sub: held }
  if (s.mic === 'listening') return { word: 'listening', line: 'Another tab is listening', tone: 'accent', live: true,
    action: 'mute', sub: held }
  if (s.mic === 'stale' || s.mic === 'reverting') return { word: 'ear lost', line: 'The ear lost its tab', tone: 'warn',
    live: false, action: 'listen', sub: 'Nothing is being heard.' }
  return { word: 'mic off', line: 'The room is quiet', tone: 'mute', live: false, action: 'listen', sub: 'Nothing is being heard.' }
}
