import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  // relative (plan-11324 S3c canvas): the same build serves at /canvas/ (one org) and /o/<org>/canvas/ (a cog); the
  // app routes by hash, so its page is always the base directory and every asset and API call resolves from it
  base: './',
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/canvas/api': 'http://127.0.0.1:8091', '/canvas/kit': 'http://127.0.0.1:8091' } },
})
