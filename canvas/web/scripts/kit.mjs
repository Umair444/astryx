// Vendor the canvas kit: UMD builds served by the bridge at /kit/ (the canvas CSP allows no CDN).
import { copyFileSync, mkdirSync } from 'node:fs'
const out = new URL('../dist/kit/', import.meta.url)
mkdirSync(out, { recursive: true })
for (const [src, name] of [
  ['chart.js/dist/chart.umd.min.js', 'chart.umd.min.js'],
  ['d3/dist/d3.min.js', 'd3.min.js'],
  ['motion/dist/motion.js', 'motion.js'],
  ['marked/lib/marked.umd.js', 'marked.min.js'],
  ['@fontsource-variable/inter/files/inter-latin-wght-normal.woff2', 'inter.woff2'],
]) copyFileSync(new URL('../node_modules/' + src, import.meta.url), new URL(name, out))
console.log('kit vendored → dist/kit/')
