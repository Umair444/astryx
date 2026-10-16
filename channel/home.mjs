// Where the channel finds its org: the astryx HOME (.env, venv/, nucleus/, triggers/, bridges/, homes/).
// Default: the directory above this file, i.e. the checkout the server ships in, so the repo's own residents behave
// exactly as before. ASTRYX_HOME overrides it, so a copy of channel/ installed elsewhere (the Claude Code plugin's
// cache) can serve an org that lives in a checkout. ASTRYX_DSN, when set, wins over <home>/.env.
// An empty value, or an unsubstituted "${...}" placeholder, means "not set": the plugin passes its optional options
// through as "" when the user left them blank.
import { readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'

const given = v => (v && !/^\$\{.*\}$/.test(v.trim()) ? v.trim() : '')

/** The home directory as a file URL ending in '/'. */
export function homeUrl(env = process.env) {
  const h = given(env.ASTRYX_HOME)
  if (!h) return new URL('../', import.meta.url)
  return pathToFileURL(h.endsWith('/') ? h : h + '/')
}

export const HOME_URL = homeUrl()
export const HOME = fileURLToPath(HOME_URL).replace(/\/+$/, '')

/** A file URL for `rel` (no leading slash) under the home. */
export const homeFile = (rel, base = HOME_URL) => new URL(rel, base)
/** The same as a filesystem path. */
export const homePath = (rel, base = HOME_URL) => fileURLToPath(new URL(rel, base))

/** The org's DSN: ASTRYX_DSN from the env when given, else the ASTRYX_DSN= line of <home>/.env. Throws if neither. */
export function dsn(env = process.env, base = HOME_URL) {
  const d = given(env.ASTRYX_DSN)
  if (d) return d
  const line = readFileSync(new URL('.env', base), 'utf8').split('\n').find(l => l.startsWith('ASTRYX_DSN='))
  if (!line) throw new Error(`no ASTRYX_DSN in the environment or in ${fileURLToPath(new URL('.env', base))}`)
  return line.slice('ASTRYX_DSN='.length).trim().replace(/^(['"])(.*)\1$/, '$2')
}
