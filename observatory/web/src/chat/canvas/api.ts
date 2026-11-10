import { useEffect, useState } from 'react'
import { api } from '../../api'
import { canvasBase } from '../../cog'

/* CANVASES in the workspace (iteration 13): the live pages agents paint (bridges/canvas.py), READ-ONLY here. The data
   comes from the observatory's own owner-only routes (observatory/api/ws_canvas.py), which read canvas's tables and
   serve a version through canvas's own shell; nothing here writes. Changing a canvas, rolling it back, sharing it: the
   "Open in canvas" link. */

export interface CanvasRow {
  id: number
  title: string
  agent: string
  user: string
  tier: 'org' | 'personal'
  version: number
  brief: string | null
  updated_at: string | null
  thread: string                   // cv:canvas-<id>: the canvas's own conversation
}
export interface CanvasVersion { version: number; author: string; note: string | null; ts: string | null }
export interface CanvasMeta extends CanvasRow { versions: CanvasVersion[] }

export const loadCanvasMeta = (id: number) => api<CanvasMeta>(`/ws/canvases/${id}`)
// the page is rendered dark; the frame re-themes it to the viewer's palette before it paints (canvas does the same)
export const renderCanvas = (id: number, v: number | null) =>
  api<{ version: number; html: string | null }>(`/ws/canvases/${id}/render${v ? `?v=${v}` : ''}`)
export const canvasData = (id: number) => api<Record<string, unknown>>(`/ws/canvases/${id}/data`)

/* the canvas a conversation is about: canvas names its own thread cv:canvas-<id> */
export function canvasIdOf(thread: string | null | undefined): number | null {
  const m = /^cv:canvas-(\d+)$/.exec(thread ?? '')
  return m ? Number(m[1]) : null
}
/* the canvas app, at that canvas (it holds the edit, ask, rollback and share) */
export const canvasHref = (id: number) => `${canvasBase()}#/canvas/${id}`

/* every canvas, one fetch per page load shared by every reader (the library, ⌘K, the top bar), refreshed on demand */
let cache: CanvasRow[] | null = null
let inflight: Promise<CanvasRow[]> | null = null
const subs = new Set<(c: CanvasRow[]) => void>()
export function refreshCanvases(): Promise<CanvasRow[]> {
  inflight ??= api<CanvasRow[]>('/ws/canvases')
    .then((c) => { cache = c; subs.forEach((f) => f(c)); return c })
    .finally(() => { inflight = null })
  return inflight
}
export function useCanvases(): CanvasRow[] | null {
  const [rows, setRows] = useState<CanvasRow[] | null>(cache)
  useEffect(() => {
    subs.add(setRows)
    if (!cache) refreshCanvases().catch(() => setRows((r) => r ?? []))
    return () => { subs.delete(setRows) }
  }, [])
  return rows
}
