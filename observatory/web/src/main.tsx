import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import {
  MantineProvider,
  createTheme,
  defaultVariantColorsResolver,
  type CSSVariablesResolver,
  type MantineColorsTuple,
} from '@mantine/core'
import '@mantine/core/styles.css'
import '@fontsource-variable/inter'
import './index.css'
import App from './App'
import { ThemeProvider, useTheme } from './theme'

// Every Mantine colour points at the active astryx theme (--t-* on <html>, see theme.tsx), so
// switching themes restyles Mantine with no re-render of the theme object itself.
const v = (k: string) => `var(--t-${k})`
const mix = (k: string, pct: number, base = 'bg') => `color-mix(in srgb, var(--t-${k}) ${pct}%, var(--t-${base}))`

// a token ramp: 0-4 fade from the page toward the colour, 5-9 are the colour itself
const ramp = (k: string): MantineColorsTuple => [
  mix(k, 8), mix(k, 14), mix(k, 25), mix(k, 45), mix(k, 70), v(k), v(k), v(k), v(k), v(k),
]

const theme = createTheme({
  primaryColor: 'accent',
  primaryShade: 6,
  fontFamily: '"Inter Variable", -apple-system, "Segoe UI", Roboto, sans-serif',
  fontFamilyMonospace: 'ui-monospace, "JetBrains Mono", "Cascadia Code", monospace',
  defaultRadius: 'md',
  white: '#ffffff',
  black: '#000000',
  colors: {
    accent: ramp('accent'),
    // `color="cyan"` / `c="cyan.4"` across the views means "the subject colour"
    cyan: ramp('accent'),
    red: ramp('bad'),
    green: ramp('good'),
    teal: ramp('good'),
    yellow: ramp('warn'),
    // Mantine's dark-scheme surface ladder (0 = text … 7 = body)
    dark: [v('fg'), v('dim'), v('mute'), v('line2'), v('line'), v('panel2'), v('panel'), v('bg'), v('bg2'), v('bg2')],
    // Mantine's light-scheme surface ladder (0 = lightest well … 9 = text)
    gray: [v('bg2'), v('panel2'), v('line'), v('line'), v('line2'), v('mute'), v('dim'), v('dim'), v('fg'), v('fg')],
  },
  // a filled accent button carries the theme's `on` ink (white on violet, dark on pastel)
  variantColorResolver: (input) => {
    const r = defaultVariantColorsResolver(input)
    if (input.variant === 'filled' && (!input.color || ['accent', 'cyan'].includes(input.color)))
      return { ...r, color: v('on'), hoverColor: v('on') }
    return r
  },
})

// both schemes resolve to the same tokens — the active theme decides what they mean
const surface = {
  '--mantine-color-text': v('fg'),
  '--mantine-color-body': v('bg'),
  '--mantine-color-bright': v('fg'),
  '--mantine-color-dimmed': v('dim'),
  '--mantine-color-placeholder': v('mute'),
  '--mantine-color-anchor': v('accent2'),
  '--mantine-color-default': v('panel'),
  '--mantine-color-default-hover': v('panel2'),
  '--mantine-color-default-color': v('fg'),
  '--mantine-color-default-border': v('line'),
  '--mantine-color-error': v('bad'),
  '--mantine-color-success': v('good'),
  '--mantine-color-disabled': v('panel2'),
  '--mantine-color-disabled-color': v('mute'),
  '--mantine-color-disabled-border': v('line'),
  '--mantine-primary-color-contrast': v('on'),
}
const resolver: CSSVariablesResolver = () => ({ variables: {}, light: surface, dark: surface })

function Root() {
  const { theme: th } = useTheme()
  return (
    <MantineProvider theme={theme} cssVariablesResolver={resolver} forceColorScheme={th.dark ? 'dark' : 'light'}>
      <App />
    </MantineProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <Root />
    </ThemeProvider>
  </StrictMode>,
)
