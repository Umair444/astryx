// Where the channel finds its org: the astryx HOME (.env, venv/, nucleus/, triggers/, bridges/, homes/).
// Default: the directory above this file, i.e. the checkout the server ships in, so the repo's own residents behave
// exactly as before. ASTRYX_HOME overrides it, so a copy of channel/ installed elsewhere (the Claude Code plugin's
// cache) can serve an org that lives in a checkout. ASTRYX_DSN, when set, wins over <home>/.env.
// An empty value, or an unsubstituted "${...}" placeholder, means "not set": the plugin passes its optional options
// through as "" when the user left them blank.
//
// plan-11324 S3a: on a host that runs SEVERAL orgs (the registry, src/astryx/orgs.py, holds >1 entry) the checkout
// carries no estate, so the default above REFUSES: ASTRYX_HOME must name a REGISTERED HOME, and an ASTRYX_DSN from
// the env that binds ANOTHER registered org's database (or libpq's user-named / postgres fallback) is refused, a
// fixture's (astryx_fx_*) allowed. The same rules as astryx.config / astryx.paths, read from the same registry file;
// with no registry (one org) every line below the predicate is dead code and the server behaves byte for byte as before.
import { readFileSync, realpathSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'

const given = v => (v && !/^\$\{.*\}$/.test(v.trim()) ? v.trim() : '')

const real = p => { try { return realpathSync(p) } catch { return resolvePath(p) } }

/** The registered orgs {org: {home, db}}, or null when this host has no registry (one org). A present but malformed
 *  registry THROWS: it fails closed, never as absent. */
export function registry(env = process.env) {
  const p = given(env.ASTRYX_ORG_REGISTRY) || '/etc/astryx/orgs.json'
  let text
  try { text = readFileSync(p, 'utf8') } catch (e) { if (e.code === 'ENOENT') return null; throw new Error(`org registry ${p} unreadable`) }
  let orgs
  try { orgs = JSON.parse(text).orgs } catch { orgs = null }
  if (!orgs || typeof orgs !== 'object' || Array.isArray(orgs) || !Object.keys(orgs).length)
    throw new Error(`org registry ${p} is malformed`)
  // orgs.load's rules, each one (a2 #58917 A-1: a registry python refuses, node must refuse too; tests/org_registry_cases.json
  // holds the cases both runtimes must classify identically)
  const out = {}, homes = Object.create(null), dbs = Object.create(null)   // no prototype: a db named "constructor" is a name
  for (const [o, e] of Object.entries(orgs)) {
    if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(o) || !e || typeof e !== 'object' || Array.isArray(e))
      throw new Error(`org registry ${p}: bad entry ${JSON.stringify(o)}`)
    if (typeof e.home !== 'string' || !e.home.startsWith('/') || typeof e.db !== 'string' || !e.db)
      throw new Error(`org registry ${p}: ${o} needs an absolute home and a db`)
    const h = real(e.home)
    if (e.db === 'postgres' || e.db.startsWith('astryx_fx_'))
      throw new Error(`org registry ${p}: ${o}'s database '${e.db}' is libpq's fallback or a fixture's`)
    if (h in homes || e.db in dbs)
      throw new Error(`org registry ${p}: ${o} shares a home or database with ${homes[h] || dbs[e.db]}`)
    homes[h] = o; dbs[e.db] = o
    out[o] = { home: h, db: e.db }
  }
  return out
}

export const multi = (env = process.env) => { const r = registry(env); return !!r && Object.keys(r).length > 1 }

/** The home directory as a file URL ending in '/'. */
export function homeUrl(env = process.env) {
  const h = given(env.ASTRYX_HOME)
  const reg = registry(env)
  if (reg && Object.keys(reg).length > 1) {
    if (!h || !Object.values(reg).some(e => e.home === real(h)))
      throw new Error('this host runs several orgs and ASTRYX_HOME names no registered HOME: refusing the checkout')
  }
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
  let v = d, src = 'the environment'
  if (!v) {
    const line = readFileSync(new URL('.env', base), 'utf8').split('\n').find(l => l.startsWith('ASTRYX_DSN='))
    if (!line) throw new Error(`no ASTRYX_DSN in the environment or in ${fileURLToPath(new URL('.env', base))}`)
    v = line.slice('ASTRYX_DSN='.length).trim().replace(/^(['"])(.*)\1$/, '$2')
    src = fileURLToPath(new URL('.env', base))
  }
  if (multi(env)) checkPair(v, src, base, env)
  return v
}

function checkPair(v, src, base, env) {
  // node-postgres's own DSN reader (pg's dependency), loaded only here: a one-org host never needs it
  const info = createRequire(import.meta.url)('pg-connection-string').parse(v)
  const db = info.database || info.user
  if (String(db || '').startsWith('astryx_fx_')) return
  if (!db || db === 'postgres' || db === info.user)
    throw new Error(`the DSN in ${src} binds ${db}: libpq's default database, never an org's (correction 1)`)
  const reg = registry(env)
  const home = real(fileURLToPath(base)).replace(/\/+$/, '')
  const mine = Object.keys(reg).find(o => reg[o].home === home)
  const owner = Object.keys(reg).find(o => reg[o].db === db)
  if (owner && owner !== mine)
    throw new Error(`the DSN in ${src} binds org ${owner}'s database, and this HOME is ${mine || 'no registered org'} (correction 2)`)
  if (mine && !owner && src !== 'the environment')
    throw new Error(`${src} names database ${db}, and the registry gives ${mine} ${reg[mine].db}`)
}
