import { useCallback, useRef, useState } from 'react'
import { nameOf, openArtifact, type Opened } from './api'
import type { OpenRequest } from './FileChip'
import { focusOf, type Focus } from './versions/awareness'

/* The artifact panel's tabs, per conversation: opening a file adds (or focuses) its tab and imports it into the store;
   coming back to a conversation brings its tabs back. A re-open re-imports, so an agent's newer bytes become the
   newest version while the tab is open. A chip names its message (iteration 7): the tab then FOCUSES the version that
   message carried (`at`), or the diff into it ("What changed"); earlier mentions under other paths import first, so
   the store's order is the thread's. */

export interface Tab { key: string; req: OpenRequest; art: Opened | null; err: string; at?: Focus | null }
interface ThreadTabs { tabs: Tab[]; active: string | null }

export function usePanel(thread: string) {
  const [all, setAll] = useState<Record<string, ThreadTabs>>({})
  const cur = all[thread] ?? { tabs: [], active: null }
  const now = useRef(all)
  now.current = all
  const put = useCallback((t: string, f: (s: ThreadTabs) => ThreadTabs) => setAll((a) => ({ ...a, [t]: f(a[t] ?? { tabs: [], active: null }) })), [])

  const load = useCallback(async (t: string, key: string, req: OpenRequest) => {
    try {
      for (const h of req.history ?? []) if (h.path !== req.path) await openArtifact(h.path, t, h.from, h.label, h.carrier).catch(() => null)
      const art = await openArtifact(req.path, t, req.from, req.label, req.carrier ?? req.msg)
      const at = focusOf(art, req)
      put(t, (s) => ({ ...s, tabs: s.tabs.map((x) => (x.key === key ? { ...x, art, at, err: '' } : x)) }))
    } catch (e) {
      put(t, (s) => ({ ...s, tabs: s.tabs.map((x) => (x.key === key ? { ...x, err: String((e as Error).message ?? e) } : x)) }))
    }
  }, [put])

  const open = useCallback((req: OpenRequest) => {
    // one tab per artifact: another path under a name already open (an agent's v2 beside its v1) reuses that tab
    const tabs = now.current[thread]?.tabs ?? []
    const key = tabs.find((x) => x.key === req.path)?.key
      ?? (req.path.startsWith('art:') ? undefined : tabs.find((x) => x.art?.store && x.art.name === nameOf(req.path, req.label))?.key)
      ?? req.path
    put(thread, (s) => (s.tabs.some((x) => x.key === key)
      ? { ...s, active: key, tabs: s.tabs.map((x) => (x.key === key ? { ...x, req } : x)) }
      : { tabs: [...s.tabs, { key, req, art: null, err: '' }], active: key }))
    void load(thread, key, req)
  }, [thread, put, load])

  const close = useCallback((key: string) => put(thread, (s) => {
    const i = s.tabs.findIndex((x) => x.key === key)
    const tabs = s.tabs.filter((x) => x.key !== key)
    return { tabs, active: s.active === key ? (tabs[i] ?? tabs[i - 1] ?? null)?.key ?? null : s.active }
  }), [thread, put])
  const closeAll = useCallback(() => put(thread, () => ({ tabs: [], active: null })), [thread, put])
  const activate = useCallback((key: string) => put(thread, (s) => ({ ...s, active: key })), [thread, put])
  const update = useCallback((key: string, art: Opened) => put(thread, (s) => ({ ...s, tabs: s.tabs.map((x) => (x.key === key ? { ...x, art } : x)) })), [thread, put])

  return { tabs: cur.tabs, active: cur.active, open, close, closeAll, activate, update }
}
export type PanelState = ReturnType<typeof usePanel>
