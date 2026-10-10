import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // the theme palettes are shared with Canvas: ../../canvas/web/src/themes.ts
    fs: { allow: ['.', '../../canvas/web/src', '../pilot'] },   // + the pilot's action catalog (plan-9000)
    proxy: {
      // OBS_API points a dev server at another observatory (a fixture-backed one for screenshots)
      '/api': process.env.OBS_API || 'http://127.0.0.1:8090',
    },
  },
})
