// Small shared pieces: avatar, markdown, icons, time.
import { useMemo, useState } from 'react'
import { BASE } from './api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ gfm: true, breaks: true })

// Agent text renders in the origin that holds the owner's session: sanitize, always.
export function Markdown({ text, className = '' }: { text: string; className?: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false }) as string, {
    FORBID_TAGS: ['style', 'form', 'input', 'iframe'], FORBID_ATTR: ['style'],
  }), [text])
  return <div className={`md ${className}`} dangerouslySetInnerHTML={{ __html: html }} />
}

function hue(name: string) {
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360
  return h
}

const noAvatar = new Set<string>()

export function Avatar({ name, size = 32, alive }: { name: string; size?: number; alive?: boolean }) {
  const h = hue(name)
  const human = name === 'owner' || name.startsWith('cv-') || name === 'you'
  const page = name.startsWith('canvas-')
  const [failed, setFailed] = useState(noAvatar.has(name))
  if (!human && !page && !failed) {
    return (
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <img src={`${BASE}api/avatar/${encodeURIComponent(name)}`} alt={name} width={size} height={size} draggable={false}
          className="w-full h-full rounded-full object-cover select-none" style={{ boxShadow: `0 0 0 1px var(--t-line2)` }}
          onError={() => { noAvatar.add(name); setFailed(true) }} />
        {alive !== undefined && (
          <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-ink-900 ${alive ? 'bg-good' : 'bg-fg-mute'}`} />
        )}
      </div>
    )
  }
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <div
        className={`w-full h-full rounded-full grid place-items-center font-semibold ${human ? 'text-fg' : 'text-white'}`}
        style={{
          fontSize: size * 0.4,
          background: human
            ? 'linear-gradient(135deg, var(--t-line2), var(--t-panel2))'
            : `conic-gradient(from ${h}deg, hsl(${h} 80% 62%), hsl(${(h + 70) % 360} 85% 58%), hsl(${(h + 140) % 360} 75% 60%), hsl(${h} 80% 62%))`,
          boxShadow: human ? 'inset 0 0 0 1px var(--t-line2)' : `0 0 18px -4px hsl(${h} 80% 60% / .55)`,
        }}
      >
        <span style={{ textShadow: human ? 'none' : '0 1px 2px rgba(0,0,0,.35)' }}>{(human ? 'U' : name[0] ?? '?').toUpperCase()}</span>
      </div>
      {alive !== undefined && (
        <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-ink-900 ${alive ? 'bg-good' : 'bg-fg-mute'}`} />
      )}
    </div>
  )
}

export function ago(iso: string | null) {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
export const I = {
  plus: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M12 5v14M5 12h14" /></svg>,
  chat: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /></svg>,
  canvas: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><rect x="3" y="4" width="18" height="14" rx="3" /><path d="M7 14l3-3 3 3 4-5" /><path d="M8 21h8" /></svg>,
  send: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M5 12h13M13 6l6 6-6 6" /></svg>,
  mic: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>,
  wave: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M3 12h2M7 8v8M11 5v14M15 8v8M19 11v2" /></svg>,
  clip: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" /></svg>,
  x: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M6 6l12 12M18 6L6 18" /></svg>,
  menu: (c = 'w-5 h-5') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M4 7h16M4 12h16M4 17h16" /></svg>,
  history: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></svg>,
  expand: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg>,
  side: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M15 4v16" /></svg>,
  people: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6" /></svg>,
  share: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><circle cx="18" cy="5" r="2.5" /><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="19" r="2.5" /><path d="M8.2 10.8l7.6-4.5M8.2 13.2l7.6 4.5" /></svg>,
  logout: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H3" /></svg>,
  spark: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><path d="M12 3l1.8 5.4L19 10l-5.2 1.6L12 17l-1.8-5.4L5 10l5.2-1.6z" /><path d="M19 17l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" /></svg>,
  archive: (c = 'w-4 h-4') => <svg viewBox="0 0 24 24" className={c} {...P}><rect x="3" y="4" width="18" height="4" rx="1" /><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4" /></svg>,
}
