// THE theme set for astryx's web surfaces (canvas, every canvas page, the observatory).
// Omarchy's idea, adopted whole: a theme is a NAMED palette that restyles everything at once, and
// T flips through them. One file, imported by both apps, so the surfaces can never drift apart.
//
// Tokens (every surface maps its own names onto these):
//   bg        page background            bg2     sidebars / chrome
//   panel     raised surface (cards)     panel2  hover / input wells
//   line      hairline borders           line2   stronger borders / focus
//   fg        primary text               dim     secondary text      mute  tertiary text
//   accent    the subject colour         accent2 its companion (gradients, links)
//   good / bad / warn                    on      text that sits ON an accent fill

export interface Theme {
  id: string
  name: string
  dark: boolean
  t: {
    bg: string; bg2: string; panel: string; panel2: string; line: string; line2: string
    fg: string; dim: string; mute: string; accent: string; accent2: string
    good: string; bad: string; warn: string; on: string
  }
}

export const THEMES: Theme[] = [
  { id: 'astryx', name: 'Astryx', dark: true, t: {
    bg: '#07091a', bg2: '#0b0e22', panel: '#10142b', panel2: '#161b38', line: '#1f2547', line2: '#2c3466',
    fg: '#e8ebf7', dim: '#a0a8c6', mute: '#646d90', accent: '#8b7bff', accent2: '#38d9f5',
    good: '#34d399', bad: '#fb7185', warn: '#fbbf24', on: '#ffffff' } },
  { id: 'tokyo-night', name: 'Tokyo Night', dark: true, t: {
    bg: '#1a1b26', bg2: '#16161e', panel: '#1f2335', panel2: '#24283b', line: '#292e42', line2: '#3b4261',
    fg: '#c0caf5', dim: '#a9b1d6', mute: '#565f89', accent: '#7aa2f7', accent2: '#bb9af7',
    good: '#9ece6a', bad: '#f7768e', warn: '#e0af68', on: '#16161e' } },
  { id: 'catppuccin', name: 'Catppuccin', dark: true, t: {
    bg: '#1e1e2e', bg2: '#181825', panel: '#232336', panel2: '#313244', line: '#313244', line2: '#45475a',
    fg: '#cdd6f4', dim: '#a6adc8', mute: '#6c7086', accent: '#cba6f7', accent2: '#89b4fa',
    good: '#a6e3a1', bad: '#f38ba8', warn: '#f9e2af', on: '#11111b' } },
  { id: 'rose-pine', name: 'Rosé Pine', dark: true, t: {
    bg: '#191724', bg2: '#16141f', panel: '#1f1d2e', panel2: '#26233a', line: '#26233a', line2: '#403d52',
    fg: '#e0def4', dim: '#908caa', mute: '#6e6a86', accent: '#c4a7e7', accent2: '#9ccfd8',
    good: '#9ccfd8', bad: '#eb6f92', warn: '#f6c177', on: '#191724' } },
  { id: 'kanagawa', name: 'Kanagawa', dark: true, t: {
    bg: '#1f1f28', bg2: '#16161d', panel: '#23232e', panel2: '#2a2a37', line: '#2a2a37', line2: '#363646',
    fg: '#dcd7ba', dim: '#c8c093', mute: '#727169', accent: '#7e9cd8', accent2: '#957fb8',
    good: '#98bb6c', bad: '#e46876', warn: '#e6c384', on: '#16161d' } },
  { id: 'gruvbox', name: 'Gruvbox', dark: true, t: {
    bg: '#282828', bg2: '#1d2021', panel: '#32302f', panel2: '#3c3836', line: '#3c3836', line2: '#504945',
    fg: '#ebdbb2', dim: '#d5c4a1', mute: '#928374', accent: '#fe8019', accent2: '#fabd2f',
    good: '#b8bb26', bad: '#fb4934', warn: '#fabd2f', on: '#1d2021' } },
  { id: 'everforest', name: 'Everforest', dark: true, t: {
    bg: '#2d353b', bg2: '#232a2e', panel: '#343f44', panel2: '#3d484d', line: '#3d484d', line2: '#475258',
    fg: '#d3c6aa', dim: '#9da9a0', mute: '#7a8478', accent: '#a7c080', accent2: '#83c092',
    good: '#a7c080', bad: '#e67e80', warn: '#dbbc7f', on: '#232a2e' } },
  { id: 'nord', name: 'Nord', dark: true, t: {
    bg: '#2e3440', bg2: '#272c36', panel: '#3b4252', panel2: '#434c5e', line: '#3b4252', line2: '#4c566a',
    fg: '#eceff4', dim: '#d8dee9', mute: '#7b88a1', accent: '#88c0d0', accent2: '#81a1c1',
    good: '#a3be8c', bad: '#bf616a', warn: '#ebcb8b', on: '#2e3440' } },
  { id: 'matte-black', name: 'Matte Black', dark: true, t: {
    bg: '#121212', bg2: '#0c0c0c', panel: '#1a1a1a', panel2: '#222222', line: '#262626', line2: '#363636',
    fg: '#eaeaea', dim: '#bebebe', mute: '#8a8a8d', accent: '#e68e0d', accent2: '#f0b35a',
    good: '#8fb573', bad: '#d35f5f', warn: '#e68e0d', on: '#121212' } },
  { id: 'catppuccin-latte', name: 'Catppuccin Latte', dark: false, t: {
    bg: '#eff1f5', bg2: '#e6e9ef', panel: '#ffffff', panel2: '#e6e9ef', line: '#dce0e8', line2: '#bcc0cc',
    fg: '#4c4f69', dim: '#6c6f85', mute: '#9ca0b0', accent: '#8839ef', accent2: '#1e66f5',
    good: '#40a02b', bad: '#d20f39', warn: '#df8e1d', on: '#ffffff' } },
  { id: 'flexoki-light', name: 'Flexoki Light', dark: false, t: {
    bg: '#fffcf0', bg2: '#f2f0e5', panel: '#fffefa', panel2: '#f2f0e5', line: '#e6e4d9', line2: '#cecdc3',
    fg: '#100f0f', dim: '#6f6e69', mute: '#b7b5ac', accent: '#205ea6', accent2: '#5e409d',
    good: '#66800b', bad: '#af3029', warn: '#ad8301', on: '#fffcf0' } },
  { id: 'white', name: 'White', dark: false, t: {
    bg: '#ffffff', bg2: '#f7f7f7', panel: '#ffffff', panel2: '#f2f2f2', line: '#e8e8e8', line2: '#d4d4d4',
    fg: '#111111', dim: '#4a4a4a', mute: '#8c8c8c', accent: '#111111', accent2: '#5a5a5a',
    good: '#15803d', bad: '#b91c1c', warn: '#a16207', on: '#ffffff' } },
]

export const byId = (id: string | null | undefined) => THEMES.find(x => x.id === id)

/** The CSS custom properties for a theme, as `--t-<token>` (plus rgb triplets for alpha use). */
export function cssVars(th: Theme): Record<string, string> {
  const v: Record<string, string> = {}
  for (const [k, c] of Object.entries(th.t)) v[`--t-${k}`] = c
  return v
}

/** The same theme as the canvas shell's --cv-* names, sent into every canvas iframe. */
export function canvasVars(th: Theme): Record<string, string> {
  const t = th.t
  return {
    '--cv-bg': t.bg, '--cv-bg-2': t.bg2, '--cv-panel': t.panel, '--cv-panel-2': t.panel2,
    '--cv-line': t.line, '--cv-ink': t.fg, '--cv-dim': t.dim, '--cv-mute': t.mute,
    '--cv-accent': t.accent, '--cv-accent-2': t.accent2, '--cv-good': t.good, '--cv-bad': t.bad,
    '--cv-warn': t.warn, '--cv-on': t.on,
  }
}

const KEY = 'astryx_theme'

export function initialTheme(): Theme {
  let saved: string | null = null
  try { saved = localStorage.getItem(KEY) } catch { /* private mode */ }
  return byId(saved) ?? (matchMedia('(prefers-color-scheme: light)').matches ? byId('catppuccin-latte')! : THEMES[0])
}

/** Apply to <html>: the variables, color-scheme, and data-theme for anything that branches on light/dark. */
export function applyTheme(th: Theme) {
  const root = document.documentElement
  for (const [k, v] of Object.entries(cssVars(th))) root.style.setProperty(k, v)
  root.dataset.theme = th.dark ? 'dark' : 'light'
  root.dataset.themeId = th.id
  root.style.colorScheme = th.dark ? 'dark' : 'light'
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', th.t.bg)
  try { localStorage.setItem(KEY, th.id) } catch { /* private mode */ }
}

export function nextTheme(cur: Theme, dir = 1): Theme {
  const i = THEMES.findIndex(x => x.id === cur.id)
  return THEMES[(i + dir + THEMES.length) % THEMES.length]
}
