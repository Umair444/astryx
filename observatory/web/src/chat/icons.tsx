/* The workspace's icon set: canvas's line icons (canvas/web/src/ui.tsx `I`), same stroke, same 24-grid, so the two
   surfaces read as one product. Decorative: every use sits beside a label or carries an aria-label on its button. */
const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
type C = string | undefined
const svg = (c: C, d: React.ReactNode) => <svg viewBox="0 0 24 24" className={c ?? 'w-4 h-4'} {...P} aria-hidden>{d}</svg>

export const I = {
  plus: (c?: C) => svg(c, <path d="M12 5v14M5 12h14" />),
  compose: (c?: C) => svg(c, <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></>),
  chat: (c?: C) => svg(c, <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />),
  canvas: (c?: C) => svg(c, <><rect x="3" y="4" width="18" height="14" rx="3" /><path d="M7 14l3-3 3 3 4-5" /><path d="M8 21h8" /></>),
  desk: (c?: C) => svg(c, <><circle cx="12" cy="9" r="4" /><path d="M4.5 20a7.5 7.5 0 0 1 15 0" /></>),
  send: (c?: C) => svg(c, <path d="M12 19V5M6 11l6-6 6 6" />),
  mic: (c?: C) => svg(c, <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>),
  clip: (c?: C) => svg(c, <path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" />),
  x: (c?: C) => svg(c, <path d="M6 6l12 12M18 6L6 18" />),
  menu: (c?: C) => svg(c, <path d="M4 7h16M4 12h16M4 17h16" />),
  dots: (c?: C) => svg(c, <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>),
  search: (c?: C) => svg(c, <><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></>),
  pin: (c?: C) => svg(c, <><path d="M9 4h6l-1 6 3 3v1H7v-1l3-3z" /><path d="M12 14v6" /></>),
  edit: (c?: C) => svg(c, <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17z" />),
  folder: (c?: C) => svg(c, <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />),
  side: (c?: C) => svg(c, <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M15 4v16" /></>),
  people: (c?: C) => svg(c, <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6" /></>),
  home: (c?: C) => svg(c, <><path d="M4 11l8-7 8 7" /><path d="M6 9.5V20h12V9.5" /></>),
  sun: (c?: C) => svg(c, <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>),
  moon: (c?: C) => svg(c, <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />),
  keys: (c?: C) => svg(c, <><rect x="2.5" y="6" width="19" height="12" rx="2.5" /><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10" /></>),
  chevron: (c?: C) => svg(c, <path d="M9 6l6 6-6 6" />),
  back: (c?: C) => svg(c, <path d="M15 6l-6 6 6 6" />),
  spark: (c?: C) => svg(c, <><path d="M12 3l1.8 5.4L19 10l-5.2 1.6L12 17l-1.8-5.4L5 10l5.2-1.6z" /></>),
  wave: (c?: C) => svg(c, <path d="M3 12h2M7 8v8M11 5v14M15 8v8M19 11v2" />),
  arrow: (c?: C) => svg(c, <path d="M5 12h13M13 6l6 6-6 6" />),
  down: (c?: C) => svg(c, <path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" />),
}
