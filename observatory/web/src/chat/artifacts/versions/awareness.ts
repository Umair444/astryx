import { createContext, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Msg } from '../../../types'
import { embeds } from '../../model'
import { nameOf, openArtifact, threadArtifacts, type Artifact, type MsgRef, type Version } from '../api'
import type { OpenRequest } from '../FileChip'

/* NEW-VERSION AWARENESS (iteration 7, "agents keep track of differentials"). An agent that re-sends a file by the same
   name is sending a NEW VERSION of it, and the chat says so on the chip: "v3 · updated", with "What changed" opening
   the panel straight into the diff (previous → this version). An OLD message's chip opens the version THAT message
   carried, not whatever is newest.

   Nothing is imported to draw a chip. Two cheap sources answer it: the thread's rows (an earlier message embedding the
   same name = this one is an update) and ONE GET /api/ws/artifacts?thread= (what the store already holds, with each
   version's provenance: the message that carried it). A file re-sent under the same name that the store does not hold
   yet is imported quietly in the background (iteration 10), exactly as opening its newest chip would (earlier paths
   first, so the store's order is the thread's), so the chip reads "v3 · updated" before anyone opens it. */

/* the version a message carried. Exact when the store recorded the message (provenance); else the newest agent
   version a message at or before it carried (an unchanged re-send keeps the version); else, for versions stored before
   provenance, the one imported closest after the message was sent. Versions are newest first. */
export function versionFor(versions: Version[], m: MsgRef): Version | null {
  if (!versions.length) return null
  const exact = versions.find((v) => v.msg === m.id)
  if (exact) return exact
  const t = Date.parse(m.ts)
  const agents = versions.filter((v) => v.author !== 'owner')
  const before = agents.find((v) => v.msg_ts && Date.parse(v.msg_ts) <= t)
  if (before) return before
  const after = (vs: Version[]) => [...vs].reverse().find((v) => !v.msg && Date.parse(v.ts) >= t)
  return after(agents) ?? after(versions) ?? versions[0]
}

/* where a version opens: its rev (null = the head), and the diff from the version before it when asked */
export interface Focus { rev: string | null; diff: { from: string; to: string } | null; n: number; alone?: boolean }
export function focusOf(a: { head: string; versions: Version[]; store: boolean }, req: OpenRequest): Focus | null {
  if (!a.store || (!req.msg && !req.diff)) return null
  const v = (req.msg && versionFor(a.versions, req.msg)) || a.versions[0]
  if (!v) return null
  const prev = a.versions[a.versions.indexOf(v) + 1]
  return {
    rev: v.rev === a.head ? null : v.rev, n: Date.now(),
    diff: req.diff && prev ? { from: prev.rev, to: v.rev } : null,
    alone: req.diff && !prev,
  }
}

/* every mention of a file in the thread, by name, oldest first; the owner's fan-out (one message to three agents is
   three rows with the same body) counts once */
export interface Mention { msg: Msg; path: string; label?: string }
export function mentionsByName(rows: Msg[]): Map<string, Mention[]> {
  const by = new Map<string, Mention[]>()
  for (const m of rows) for (const e of embeds(m.body)) {
    const name = nameOf(e.path, e.label)
    const list = by.get(name) ?? []
    const last = list.at(-1)
    if (last && last.msg.from === m.from && last.path === e.path && last.msg.body === m.body && Date.parse(m.ts) - Date.parse(last.msg.ts) < 60_000) continue
    list.push({ msg: m, path: e.path, label: e.label })
    by.set(name, list)
  }
  return by
}

export interface ChipVer {
  n: number | null           // the version this message carried, once the store holds it
  updated: boolean           // a newer version of a file this thread had already seen
  carrier: MsgRef            // the newest message embedding this PATH: whose bytes the path holds now (import provenance)
  history: OpenRequest[]     // earlier mentions under other paths, oldest first: imported first so the order is true
}
const ref = (m: Msg): MsgRef => ({ id: m.id, ts: m.ts })

export function chipVer(m: Msg, path: string, label: string | undefined, by: Map<string, Mention[]>, stored: Artifact[]): ChipVer | null {
  const name = nameOf(path, label)
  const list = by.get(name) ?? []
  const i = list.findIndex((x) => x.msg.id === m.id && x.path === path)
  const earlier = i > 0 ? list.slice(0, i) : []
  const carrier = [...list].reverse().find((x) => x.path === path)?.msg ?? m
  const art = stored.find((a) => a.name === name)
  let v = art ? versionFor(art.versions, ref(m)) : null
  // a version an EARLIER mention carried is not this message's (its own bytes are not stored yet): no number
  if (v?.msg && v.msg !== m.id && earlier.some((x) => x.msg.id === v!.msg)) v = null
  const updated = earlier.length > 0 || (!!v && v.n > 1 && v.author !== 'owner')
  if (!updated && !(v && v.n > 1)) return null
  const seen = new Set([path])
  const history = earlier.filter((x) => !seen.has(x.path) && seen.add(x.path)).map((x) => ({ path: x.path, label: x.label, from: x.msg.from, msg: ref(x.msg), carrier: ref(x.msg) }))
  return { n: v?.n ?? null, updated, carrier: ref(carrier), history }
}

/* what a chip asks of the conversation */
export interface ChipCtxValue {
  info: (m: Msg, path: string, label?: string) => ChipVer | null
  whatChanged: (r: OpenRequest) => void
}
export const ChipCtx = createContext<ChipCtxValue | null>(null)

/* the conversation's side: the stored list (refetched when the thread moves or a version is saved: `bump`), the
   mentions, and how "What changed" opens */
export function useChipAwareness(thread: string, rows: Msg[], bump: string, open: (r: OpenRequest) => void): ChipCtxValue {
  const by = useMemo(() => mentionsByName(rows), [rows])
  const any = by.size > 0
  const [stored, setStored] = useState<Artifact[]>([])
  const newest = rows.at(-1)?.id ?? 0
  useEffect(() => { setStored([]) }, [thread])
  const tried = useRef(new Set<string>())        // thread|name|message: one background import per new mention
  useEffect(() => {
    if (!thread || !any) return
    let live = true
    ;(async () => {
      const arts = await threadArtifacts(thread)
      if (!live) return
      setStored(arts)
      // updated files the store has not caught up with: import them as their newest chip would, then look again
      const behind = [...by].filter(([name, list]) => {
        if (list.length < 2) return false
        const last = list.at(-1)!
        const key = `${thread}|${name}|${last.msg.id}`
        if (tried.current.has(key)) return false
        const art = arts.find((a) => a.name === name)
        if (art?.versions.some((v) => v.msg === last.msg.id)) return false
        tried.current.add(key)
        return true
      })
      if (!behind.length) return
      for (const [, list] of behind) {
        const seen = new Set<string>()
        for (const x of list) {               // each distinct path once, oldest first, carried by its NEWEST message
          if (seen.has(x.path)) continue
          seen.add(x.path)
          const carrier = [...list].reverse().find((y) => y.path === x.path)!.msg
          await openArtifact(x.path, thread, carrier.from, x.label, ref(carrier)).catch(() => null)
        }
      }
      const again = await threadArtifacts(thread)
      if (live) setStored(again)
    })().catch(() => {})
    return () => { live = false }
  }, [thread, any, newest, bump, by])
  const info = useCallback((m: Msg, path: string, label?: string) => chipVer(m, path, label, by, stored), [by, stored])
  const whatChanged = useCallback((r: OpenRequest) => open({ ...r, diff: true }), [open])
  return useMemo(() => ({ info, whatChanged }), [info, whatChanged])
}
