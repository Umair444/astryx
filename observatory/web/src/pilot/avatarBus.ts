/* The call's on-screen figure, as a tiny pub/sub (the call, iteration 17). Pure: handlers.ts (which node imports)
   tells the figure where to go and what to do; call/Avatar.tsx draws it. A target is an element (the figure glides
   to it and it lights up) or null (the figure goes home). Nothing here touches the DOM. */

export type AvatarAct = 'idle' | 'point' | 'work' | 'dance' | 'cheer'
export interface AvatarCue { at: number; act: AvatarAct; target: unknown | null; label: string }

let cue: AvatarCue = { at: 0, act: 'idle', target: null, label: '' }
const subs = new Set<() => void>()
const tell = (c: Omit<AvatarCue, 'at'>) => { cue = { ...c, at: Date.now() }; subs.forEach((f) => f()) }

export const avatar = {
  /** glide to `el` and light it up; `label` is the few words the figure says ("opening Goals") */
  point: (el: unknown | null, label = '') => tell({ act: 'point', target: el, label }),
  work: (el: unknown | null, label = '') => tell({ act: 'work', target: el, label }),
  dance: () => tell({ act: 'dance', target: null, label: '' }),
  cheer: (label = '') => tell({ act: 'cheer', target: cue.target, label }),
  home: () => tell({ act: 'idle', target: null, label: '' }),
  cue: () => cue,
  subscribe: (f: () => void) => { subs.add(f); return () => { subs.delete(f) } },
}
