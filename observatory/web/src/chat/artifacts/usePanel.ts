import { useCallback, useState } from 'react'
import { openArtifact, type Opened } from './api'
import type { OpenRequest } from './FileChip'

/* The artifact panel's tabs, per conversation: opening a file adds (or focuses) its tab and imports it into the store;
   coming back to a conversation brings its tabs back. A re-open re-imports, so an agent's newer bytes become the
   newest version while the tab is open. */

export interface Tab { key: string; req: OpenRequest; art: Opened | null; err: string }
interface ThreadTabs { tabs: Tab[]; active: string | null }

export function usePanel(thread: string) {
  const [all, setAll] = useState<Record<string, ThreadTabs>>({})
  const cur = all[thread] ?? { tabs: [], active: null }
  const put = useCallback((t: string, f: (s: ThreadTabs) => ThreadTabs) => setAll((a) => ({ ...a, [t]: f(a[t] ?? { tabs: [], active: null }) })), [])

  const load = useCallback((t: string, key: string, req: OpenRequest) => {
    openArtifact(req.path, t, req.from, req.label)
      .then((art) => put(t, (s) => ({ ...s, tabs: s.tabs.map((x) => (x.key === key ? { ...x, art, err: '' } : x)) })))
      .catch((e) => put(t, (s) => ({ ...s, tabs: s.tabs.map((x) => (x.key === key ? { ...x, err: String((e as Error).message ?? e) } : x)) })))
  }, [put])

  const open = useCallback((req: OpenRequest) => {
    const key = req.path
    put(thread, (s) => (s.tabs.some((x) => x.key === key) ? { ...s, active: key } : { tabs: [...s.tabs, { key, req, art: null, err: '' }], active: key }))
    load(thread, key, req)
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
