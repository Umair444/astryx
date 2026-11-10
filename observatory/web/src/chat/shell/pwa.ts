import { useEffect, useSyncExternalStore } from 'react'

/* INSTALL ON A PHONE (iteration 9). The chat is installable as "astryx chat": a web app manifest
   (public/chat.webmanifest: standalone, start_url = the chat route, the canvas palette's colours) and its icons. The
   manifest link and the iOS home-screen tags are put in <head> ONLY while the chat is on screen and taken out when it
   leaves, so the observatory's floor and every other tab behave exactly as before (nothing installable, no theme
   colour change). No service worker: nothing of the owner's data is ever cached by the browser for offline use. */

const TAGS: [string, Record<string, string>][] = [
  ['link', { rel: 'manifest', href: '/chat.webmanifest' }],
  ['link', { rel: 'apple-touch-icon', href: '/chat-icon-180.png' }],
  ['meta', { name: 'apple-mobile-web-app-capable', content: 'yes' }],
  ['meta', { name: 'mobile-web-app-capable', content: 'yes' }],
  ['meta', { name: 'apple-mobile-web-app-title', content: 'astryx chat' }],
  ['meta', { name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent' }],
]

export function useInstallable() {
  useEffect(() => {
    const added = TAGS.map(([tag, attrs]) => {
      const el = document.createElement(tag)
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v)
      el.setAttribute('data-chat-pwa', '')
      document.head.appendChild(el)
      return el
    })
    return () => added.forEach((el) => el.remove())
  }, [])
}

/* the browser's install offer (Chromium's beforeinstallprompt), kept so the menu can offer "Install the app" */
interface InstallEvent extends Event { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> }
let deferred: InstallEvent | null = null
const subs = new Set<() => void>()
if (typeof window !== 'undefined') {
  addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferred = e as InstallEvent; subs.forEach((f) => f()) })
  addEventListener('appinstalled', () => { deferred = null; subs.forEach((f) => f()) })
}
export function useInstallOffer(): (() => Promise<void>) | null {
  const has = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f) }, () => !!deferred)
  if (!has) return null
  return async () => { const d = deferred; deferred = null; subs.forEach((f) => f()); await d?.prompt() }
}
