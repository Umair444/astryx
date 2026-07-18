import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider, createTheme } from '@mantine/core'
import '@mantine/core/styles.css'
import './index.css'
import App from './App'

const theme = createTheme({
  primaryColor: 'cyan',
  fontFamily: '-apple-system, "Segoe UI", Roboto, "Inter", sans-serif',
  fontFamilyMonospace: 'ui-monospace, "JetBrains Mono", "Cascadia Code", monospace',
  defaultRadius: 'md',
  colors: {
    dark: [
      '#d5ddf5', // 0 text
      '#9aa7c7', // 1 dim text
      '#5b6890', // 2 muted
      '#2a3660', // 3
      '#1d2647', // 4 lines
      '#141c3a', // 5 hover
      '#0f1630', // 6 panels
      '#0b1020', // 7 body
      '#080c1a', // 8
      '#05070f', // 9
    ],
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <App />
    </MantineProvider>
  </StrictMode>,
)
