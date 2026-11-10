/* the annotation layer's few icons, on the workspace's 24-grid at its 1.8 stroke (chat/icons.tsx) */
const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
const svg = (c: string, d: React.ReactNode) => <svg viewBox="0 0 24 24" className={c} {...P} aria-hidden>{d}</svg>

export const A = {
  note: (c = 'w-4 h-4') => svg(c, <><path d="M5 5.5A1.5 1.5 0 0 1 6.5 4h11A1.5 1.5 0 0 1 19 5.5v9a1.5 1.5 0 0 1-1.5 1.5H11l-4.5 4v-4h0A1.5 1.5 0 0 1 5 14.5z" /><path d="M9 9h6M9 12h3.5" /></>),
  ask: (c = 'w-4 h-4') => svg(c, <><path d="M12 3.5l1.6 4.3 4.4 1.6-4.4 1.6L12 15.3l-1.6-4.3L6 9.4l4.4-1.6z" /><path d="M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" /></>),
  suggest: (c = 'w-4 h-4') => svg(c, <><path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17z" /><path d="M13.5 8.5l3 3" /></>),
  check: (c = 'w-4 h-4') => svg(c, <path d="M5 12.5l4.2 4.2L19 7" />),
  undo: (c = 'w-4 h-4') => svg(c, <><path d="M9 14L4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></>),
  trash: (c = 'w-4 h-4') => svg(c, <><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5" /></>),
  margin: (c = 'w-[15px] h-[15px]') => svg(c, <><rect x="3.5" y="4" width="17" height="16" rx="2.5" /><path d="M14.5 4v16M17 8.5h1M17 12h1" /></>),
  link: (c = 'w-3.5 h-3.5') => svg(c, <path d="M7 17L17 7M9 7h8v8" />),
  chevron: (c = 'w-3.5 h-3.5') => svg(c, <path d="M7 10l5 5 5-5" />),
}
