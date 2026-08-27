import { useEffect, useState } from 'react'
import { api, apiSend, displayName } from '../api'

/* Owner-only per-agent provider/auth, SHARED by the agent side-drawer and the Agents-tab
   profile modal so both surfaces show one identical editor. Each resident is its own `claude`
   process and may run on a different provider + key + model map; spawn.sh injects this into the
   agent's settings.json env on respawn (nucleus/runtime_env.py). The token itself NEVER transits
   here — we store only the NAME of the .env key that holds it (redacted on read). Empty
   everything → the agent reverts to the org's ambient default. */

export type RuntimeCfg = {
  base_url: string
  token_env: string
  token_present: boolean
  models: { opus?: string; sonnet?: string; haiku?: string }
  effort: string
  env_keys: string[]
  configured: boolean
}

export default function RuntimeEditor({ name, live }: { name: string; live: boolean }) {
  const [cfg, setCfg] = useState<RuntimeCfg | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [tokenEnv, setTokenEnv] = useState('')
  const [opus, setOpus] = useState('')
  const [sonnet, setSonnet] = useState('')
  const [haiku, setHaiku] = useState('')
  const [effort, setEffort] = useState('')
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  function load() {
    api<RuntimeCfg>(`/agents/${encodeURIComponent(name)}/runtime`)
      .then((c) => {
        setCfg(c)
        setBaseUrl(c.base_url || '')
        setTokenEnv(c.token_env || '')
        setOpus(c.models?.opus || '')
        setSonnet(c.models?.sonnet || '')
        setHaiku(c.models?.haiku || '')
        setEffort(c.effort || '')
      })
      .catch(() => setCfg(null))
  }
  useEffect(() => {
    setNote(null)
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name])

  const dirty =
    !!cfg &&
    (baseUrl !== (cfg.base_url || '') ||
      tokenEnv !== (cfg.token_env || '') ||
      opus !== (cfg.models?.opus || '') ||
      sonnet !== (cfg.models?.sonnet || '') ||
      haiku !== (cfg.models?.haiku || '') ||
      effort !== (cfg.effort || ''))

  async function save() {
    setSaving(true)
    setNote(null)
    try {
      const r = await apiSend<{ note: string }>('PUT', `/agents/${encodeURIComponent(name)}/runtime`, {
        base_url: baseUrl,
        token_env: tokenEnv,
        models: { opus, sonnet, haiku },
        effort,
      })
      setNote(r.note)
      load()
    } catch (e) {
      setNote('save failed — ' + (e as Error).message)
    }
    setSaving(false)
  }

  function clearAll() {
    setBaseUrl('')
    setTokenEnv('')
    setOpus('')
    setSonnet('')
    setHaiku('')
    setEffort('')
  }

  if (!cfg) return <div className="text-xs text-ink-mute py-4">loading runtime…</div>

  const inputCls =
    'w-full text-[12px] font-mono text-ink-dim bg-deck border border-line rounded-md px-2 py-1 focus:outline-none focus:border-cyan/40'
  const labelCls = 'text-[10px] uppercase tracking-[0.15em] text-ink-mute mb-1'

  return (
    <div className="flex flex-col gap-3">
      <div className="text-[11px] text-ink-mute leading-relaxed">
        {displayName(name)}'s provider &amp; key. Leave everything empty to run on the org's default
        (your ambient login). The <span className="font-mono">token</span> stays in{' '}
        <span className="font-mono">.env</span> — here you only name the key that holds it. Applies
        on the agent's next respawn{live ? ' (it is live now).' : '.'}
      </div>

      <div>
        <div className={labelCls}>base url (custom provider — blank = Anthropic default)</div>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.currentTarget.value)}
          placeholder="https://api-…/anthropic"
          spellCheck={false}
          className={inputCls}
        />
      </div>

      <div>
        <div className={labelCls}>
          token — .env key holding it{' '}
          {tokenEnv &&
            (cfg.token_env === tokenEnv ? (
              <span className={cfg.token_present ? 'text-teal-300' : 'text-red-300'}>
                · {cfg.token_present ? 'resolves in .env ✓' : 'NOT found in .env ✗'}
              </span>
            ) : (
              <span className="text-amber-300">· unsaved</span>
            ))}
        </div>
        <input
          value={tokenEnv}
          onChange={(e) => setTokenEnv(e.currentTarget.value)}
          placeholder="PROVIDER_HUAWEI_TOKEN"
          list={`envkeys-${name}`}
          spellCheck={false}
          className={inputCls}
        />
        <datalist id={`envkeys-${name}`}>
          {cfg.env_keys.map((k) => (
            <option key={k} value={k} />
          ))}
        </datalist>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {(
          [
            ['opus', opus, setOpus],
            ['sonnet', sonnet, setSonnet],
            ['haiku', haiku, setHaiku],
          ] as [string, string, (v: string) => void][]
        ).map(([tier, val, set]) => (
          <div key={tier}>
            <div className={labelCls}>{tier} →</div>
            <input
              value={val}
              onChange={(e) => set(e.currentTarget.value)}
              placeholder={tier === 'opus' ? 'glm-5.2' : ''}
              spellCheck={false}
              className={inputCls}
            />
          </div>
        ))}
      </div>

      <div>
        <div className={labelCls}>effort</div>
        <select value={effort} onChange={(e) => setEffort(e.currentTarget.value)} className={inputCls}>
          <option value="">default</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={!dirty || saving}
          className="px-3 py-1 rounded-md text-xs bg-cyan/15 text-cyan-soft border border-cyan/30 hover:bg-cyan/25 disabled:opacity-40 transition-colors duration-75"
        >
          {saving ? 'saving…' : 'save runtime'}
        </button>
        <button
          onClick={clearAll}
          className="px-3 py-1 rounded-md text-xs text-ink-mute border border-line hover:bg-deck-3/40 transition-colors duration-75"
        >
          clear (→ default)
        </button>
        {dirty && <span className="text-[11px] text-amber-300">unsaved changes</span>}
        {note && !dirty && <span className="text-[11px] text-ink-mute">{note}</span>}
      </div>
    </div>
  )
}
