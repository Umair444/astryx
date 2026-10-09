import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // the theme palettes are shared with Canvas: ../../canvas/web/src/themes.ts
    fs: { allow: ['.', '../../canvas/web/src'] },
    proxy: {
      '/api': 'http://127.0.0.1:8090',
    },
  },
})
