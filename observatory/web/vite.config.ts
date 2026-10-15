import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // plan-10108 D2: the dependency cache is per SPAWNER, never node_modules/.vite shared by every concurrent dev server
  // (check.sh hands each gate VITE_CACHE_DIR under its own TMPDIR; the live scripts set it under theirs)
  cacheDir: process.env.VITE_CACHE_DIR || 'node_modules/.vite',
  server: {
    // the theme palettes are shared with Canvas: ../../canvas/web/src/themes.ts
    fs: { allow: ['.', '../../canvas/web/src', '../pilot'] },   // + the pilot's action catalog (plan-9000)
    proxy: {
      // OBS_API points a dev server at another observatory (a fixture-backed one for screenshots)
      '/api': process.env.OBS_API || 'http://127.0.0.1:8090',
    },
  },
})
