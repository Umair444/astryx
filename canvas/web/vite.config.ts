import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/canvas/',
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/canvas/api': 'http://127.0.0.1:8091', '/canvas/kit': 'http://127.0.0.1:8091' } },
})
