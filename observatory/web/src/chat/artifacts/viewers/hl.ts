import hljs from 'highlight.js/lib/core'
import sql from 'highlight.js/lib/languages/sql'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import typescript from 'highlight.js/lib/languages/typescript'
import javascript from 'highlight.js/lib/languages/javascript'
import bash from 'highlight.js/lib/languages/bash'
import yaml from 'highlight.js/lib/languages/yaml'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import ini from 'highlight.js/lib/languages/ini'
import markdown from 'highlight.js/lib/languages/markdown'

/* The highlighter, loaded only when a code artifact opens (a dynamic import from Code.tsx): highlight.js core and the
   handful of languages the org's agents actually write. Its output is escaped text in <span class="hljs-*">, coloured by
   workspace.css from the theme tokens, so every palette carries it. */
for (const [n, l] of Object.entries({ sql, json, python, typescript, javascript, bash, yaml, xml, css, ini, markdown })) hljs.registerLanguage(n, l)

const BY_EXT: Record<string, string> = {
  sql: 'sql', json: 'json', py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript', sh: 'bash',
  yaml: 'yaml', yml: 'yaml', html: 'xml', svg: 'xml', css: 'css', toml: 'ini', md: 'markdown', markdown: 'markdown',
}

export function highlight(code: string, ext: string): string {
  const lang = BY_EXT[ext]
  if (code.length > 400_000) return escape(code)               // a huge dump reads fine plain; highlighting would stall
  return lang ? hljs.highlight(code, { language: lang, ignoreIllegals: true }).value : escape(code)
}
const escape = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/* a chat code block (thread/code.ts): by its fence's LANGUAGE name (sql, python, js, sh…), else the best guess among
   the registered ones; long blocks stay plain */
const ALIAS: Record<string, string> = { js: 'javascript', ts: 'typescript', py: 'python', sh: 'bash', shell: 'bash', zsh: 'bash', html: 'xml', yml: 'yaml' }
export function highlightLang(code: string, lang: string): string {
  if (code.length > 100_000) return escape(code)
  const l = ALIAS[lang] ?? lang
  if (l && hljs.getLanguage(l)) return hljs.highlight(code, { language: l, ignoreIllegals: true }).value
  return hljs.highlightAuto(code).value
}
