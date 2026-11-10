import type { Kind } from './api'

/* One small line icon per artifact kind (the workspace's 24-grid, 1.8 stroke), and the words for it. The kind is the
   only thing an icon says; colour stays for agents and diffs. */
const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
const page = <path d="M6 3h8l4 4v14H6z" />
const fold = <path d="M14 3v4h4" />

const GLYPH: Record<Kind, React.ReactNode> = {
  text: <>{page}{fold}<path d="M9 12h6M9 15.5h6M9 9h2" /></>,
  code: <><path d="M8.5 8L4.5 12l4 4M15.5 8l4 4-4 4M13 6l-2 12" /></>,
  table: <><rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M3.5 10h17M3.5 14.5h17M10 10v9" /></>,
  sheet: <><rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M3.5 10h17M10 5v14M15 10v9" /></>,
  image: <><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><circle cx="9" cy="10" r="1.6" /><path d="M20.5 16l-5-5-8.5 8.5" /></>,
  pdf: <>{page}{fold}<path d="M8.6 17v-4h1.3a1.3 1.3 0 0 1 0 2.6H8.6M13 13v4h.8a2 2 0 0 0 0-4z" /></>,
  docx: <>{page}{fold}<path d="M8.5 11.5l1.2 5 1.6-3.6 1.6 3.6 1.2-5" /></>,
  audio: <><path d="M9 18V6l10-2v12" /><circle cx="6.5" cy="18" r="2.5" /><circle cx="16.5" cy="16" r="2.5" /></>,
  video: <><rect x="3" y="6" width="13" height="12" rx="2.5" /><path d="M16 10.5l5-3v9l-5-3" /></>,
  binary: <>{page}{fold}</>,
}
export function KindIcon({ kind, className = 'w-4 h-4' }: { kind: Kind; className?: string }) {
  return <svg viewBox="0 0 24 24" className={className} {...P} aria-hidden>{GLYPH[kind]}</svg>
}
export const KIND_WORD: Record<Kind, string> = {
  text: 'Document', code: 'Code', table: 'Table', sheet: 'Spreadsheet', image: 'Image', pdf: 'PDF', docx: 'Word document',
  audio: 'Audio', video: 'Video', binary: 'File',
}
/* the drawer's filters */
export type Filter = 'all' | 'images' | 'docs' | 'data' | 'code'
export const FILTER_OF: Record<Kind, Exclude<Filter, 'all'>> = {
  image: 'images', video: 'images', text: 'docs', pdf: 'docs', docx: 'docs', binary: 'docs', audio: 'docs',
  table: 'data', sheet: 'data', code: 'code',
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
