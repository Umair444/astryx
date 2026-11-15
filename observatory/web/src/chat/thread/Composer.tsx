import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { startDictation, stopDictation, useDictation } from '../dictate'
import { mentions, upload, type McpTool, type Skill, type Uploaded } from '../model'
import { I } from '../icons'
import { touchFirst } from '../shell/phone'
import { expandPasteTokens, pasteToken } from './code'

const PASTE_LINES = 12, PASTE_CHARS = 1500          // a paste this long folds into a token (code.ts pasteToken)
/* this tab's pastes, by token number, kept in sessionStorage beside the drafts (a reload keeps a draft, so it must keep
   the pastes its tokens name); the counter is kept too, so a number is never reused in the tab (medic 12168) */
const PASTE_KEY = 'ws.pastes', SEQ_KEY = 'ws.pastes.seq', PASTE_STORE_MAX = 2_000_000
const PASTES = new Map<number, string>()
let pasteSeq = 0
try {
  const saved = JSON.parse(sessionStorage.getItem(PASTE_KEY) || '{}') as { seq?: number; items?: [number, string][] }
  for (const [k, v] of saved.items ?? []) PASTES.set(Number(k), String(v))
  pasteSeq = Math.max(Number(saved.seq) || 0, Number(sessionStorage.getItem(SEQ_KEY)) || 0, ...PASTES.keys())
} catch { /* private mode: pastes live as long as the page */ }
function savePastes() {
  try { sessionStorage.setItem(SEQ_KEY, String(pasteSeq)) } catch { /* nothing fits: the ids still never repeat until a reload */ }
  try {
    let items = [...PASTES.entries()], size = items.reduce((n, [, v]) => n + v.length, 0)
    while (size > PASTE_STORE_MAX && items.length > 1) size -= items.shift()![1].length     // the oldest go first
    sessionStorage.setItem(PASTE_KEY, JSON.stringify({ seq: pasteSeq, items }))
  } catch { /* full or private: the token still works until a reload, and a lost one is refused, never sent empty */ }
}

/* The composer (plan-11884 C3; restyled for the workspace after canvas's Composer + Home). Everything is a key:
     Enter sends, Shift+Enter breaks a line, ↑ in an empty box brings back your last message,
     / opens commands (the org's real skills and MCP tools, plus /chat's own), @ mentions an agent,
     ⌘. or Ctrl+. dictates, Esc closes a menu.
   A message goes to the agents it @mentions, or to everyone already in the chat (shown as the "To" faces). Nothing
   sends by itself: dictation and attachments only ever fill the box. `hero` is the empty state's big well.
   SWITCH: the "To" faces are a button; it opens the roster (the @ menu's look and keys) and picking an agent hands
   the chat to it (`onSwitch`: from then on the default recipient; @mentions still add on top). /switch opens the
   same picker. */

export interface Command { key: string; label: string; hint: string; run: (arg: string) => void | string }
export interface ComposerHandle { focus: () => void; insert: (text: string) => void; set: (text: string) => void; get: () => string; attach: (u: Uploaded) => void; pick: () => void }

interface Item { key: string; label: string; hint: string; kind: 'cmd' | 'skill' | 'tool' | 'agent'; apply: () => void }

const DRAFTS = 'ws.drafts.v1'
const FILES = new Map<string, Uploaded[]>()           // attachments waiting in a conversation's box (this page only)
function drafts(): Record<string, string> { try { return JSON.parse(sessionStorage.getItem(DRAFTS) || '{}') as Record<string, string> } catch { return {} } }
function draftOf(key: string): string { return drafts()[key] ?? '' }
function keepDraft(key: string, text: string) {
  try {
    const all = drafts()
    if ((all[key] ?? '') === text) return
    if (text) all[key] = text; else delete all[key]
    sessionStorage.setItem(DRAFTS, JSON.stringify(all))
  } catch { /* private mode: the draft lives as long as the box */ }
}

export default forwardRef<ComposerHandle, {
  roster: string[]
  inChat: string[]
  skills: Skill[]
  tools: McpTool[]
  commands: Command[]
  lastMine: () => string
  onSend: (text: string, files: Uploaded[], to: string[]) => Promise<void>
  hero?: boolean
  placeholder?: string
  draftKey?: string           // the conversation the draft belongs to: each keeps its own (iteration 11)
  onTalk?: (agent: string) => void   // iteration 13: Talk, canvas's voice mode, with the agent this box writes to
  onSwitch?: (agents: string[]) => void   // hand the chat to these agents (the "To" faces' picker, /switch)
  roles?: Record<string, string>
}>(function Composer({ roster, inChat, skills, tools, commands, lastMine, onSend, hero = false, placeholder, draftKey = '', onTalk, onSwitch, roles = {} }, ref) {
  const [text, setText] = useState(() => draftOf(draftKey))
  const [files, setFiles] = useState<Uploaded[]>(() => FILES.get(draftKey) ?? [])
  // A DRAFT PER CONVERSATION: the box used to keep its words across a switch, so a line written to finance sat ready
  // to go to seed on Enter; now switching stashes it and brings back that conversation's own (per tab, so a reload
  // or an outage that remounts the workspace keeps it too). Derived state: swapped during render, never a frame late.
  const [owner, setOwner] = useState(draftKey)
  if (owner !== draftKey) {
    keepDraft(owner, text); FILES.set(owner, files)
    setOwner(draftKey); setText(draftOf(draftKey)); setFiles(FILES.get(draftKey) ?? [])
  }
  useEffect(() => { if (owner === draftKey) keepDraft(owner, text) }, [owner, draftKey, text])
  const ownerRef = useRef(owner)
  ownerRef.current = owner
  const [uploading, setUploading] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [sel, setSel] = useState(0)
  const [menuOff, setMenuOff] = useState(false)
  const [picker, setPicker] = useState(false)          // the agent picker (switch), over the box like the @ menu
  const menu = useRef<HTMLUListElement>(null)
  const [drop, setDrop] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  const fileIn = useRef<HTMLInputElement>(null)
  const dict = useDictation()

  /* A LONG PASTE (owner 11-15, the way Claude Code does it): it sits in the box as one token, "[Pasted text #2 +40
     lines]", so the box stays readable, and goes out whole on send: code fenced (code.ts fencePaste), anything else as
     pasted. Delete the token and the paste goes with it. The text lives in PASTES (this tab), keyed by its number. */
  function onPasteText(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const t = e.clipboardData.getData('text/plain')
    const n = t.split('\n').length
    if (n < PASTE_LINES && t.length < PASTE_CHARS) return       // short: it types in like anything else
    e.preventDefault()
    const id = ++pasteSeq
    PASTES.set(id, t)
    savePastes()
    insert(`${pasteToken(id, n)}\n`)
  }
  const insert = (s: string) => {
    const el = box.current
    if (!el) { setText((t) => t + s); return }
    const a = el.selectionStart ?? text.length, b = el.selectionEnd ?? text.length
    const pre = text.slice(0, a), sep = pre && !/\s$/.test(pre) ? ' ' : ''
    const next = pre + sep + s + text.slice(b)
    setText(next)
    requestAnimationFrame(() => { el.focus(); const at = (pre + sep + s).length; el.setSelectionRange(at, at) })
  }
  useImperativeHandle(ref, () => ({
    focus: () => box.current?.focus(),
    insert,
    set: (s) => { setText(s); requestAnimationFrame(() => { box.current?.focus(); box.current?.setSelectionRange(s.length, s.length) }) },
    get: () => text,
    attach: (u) => setFiles((f) => [...f, u]),
    pick: () => openPicker(),
  }))
  const openPicker = () => { if (!onSwitch) return; setPicker(true); setMenuOff(false); requestAnimationFrame(() => box.current?.focus()) }

  // autosize: a hero well starts tall; the dock grows to 40% of the screen
  useEffect(() => {
    const el = box.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = Math.max(hero ? 64 : 26, Math.min(el.scrollHeight, Math.round(innerHeight * 0.4))) + 'px'
  }, [text, hero])

  // the token under the caret decides the menu: "/word" at the start, or "@word" anywhere
  const caret = box.current?.selectionStart ?? text.length
  const head = text.slice(0, caret)
  const slash = /^\/([\w:.-]*)$/.exec(head)
  const at = /(^|\s)@([\w-]*)$/.exec(head)
  const items: Item[] = useMemo(() => {
    if (menuOff) return []
    if (picker && onSwitch) {           // the roster, the chat's current agent(s) first; picking one switches
      const cur = inChat.filter((n) => roster.includes(n))
      return [...cur, ...roster.filter((n) => !cur.includes(n))].map((n) => ({
        key: '@' + n, label: displayName(n), hint: cur.includes(n) ? (cur.length === 1 ? '✓ in To (the only one)' : cur[0] === n ? '✓ in To · leads' : '✓ in To · click to remove') : (roles[n] ? `${roles[n]} · click to add` : 'click to add'), kind: 'agent' as const,
        // a TOGGLE (owner 11-13): picking adds the agent to the "To" chips or takes it out; the first stays the lead.
        // The last one can't be removed (a message always goes somewhere).
        apply: () => {
          const next = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n]
          if (next.length) onSwitch(next)
          requestAnimationFrame(() => box.current?.focus())
        },
      }))
    }
    if (slash) {
      const q = slash[1].toLowerCase()
      const all: Item[] = [
        ...commands.map((c) => ({ key: '/' + c.key, label: '/' + c.key, hint: c.hint, kind: 'cmd' as const, apply: () => { setText(''); const r = c.run(''); if (typeof r === 'string') setErr(r) } })),
        ...skills.map((s) => ({ key: 'skill:' + s.name, label: s.name, hint: s.description, kind: 'skill' as const, apply: () => setText(`Use the ${s.name} skill: `) })),
        ...tools.map((t) => ({ key: `tool:${t.server}.${t.name}`, label: t.name, hint: `${t.server}${t.description ? ': ' + t.description : ''}`, kind: 'tool' as const, apply: () => setText(`Use the ${t.name} tool (${t.server}): `) })),
      ]
      return all.filter((i) => !q || i.label.toLowerCase().includes(q) || i.key.toLowerCase().includes(q)).slice(0, 40)
    }
    if (at) {
      const q = at[2].toLowerCase()
      return roster.filter((n) => n.includes(q)).slice(0, 12).map((n) => ({
        key: '@' + n, label: displayName(n), hint: inChat.includes(n) ? 'in this chat' : '', kind: 'agent' as const,
        apply: () => {
          const el = box.current, a = el?.selectionStart ?? text.length
          const start = a - at[2].length - 1
          const next = text.slice(0, start) + '@' + n + ' ' + text.slice(a)
          setText(next)
          requestAnimationFrame(() => { el?.focus(); const p = start + n.length + 2; el?.setSelectionRange(p, p) })
        },
      }))
    }
    return []
  }, [slash?.[1], at?.[2], commands, skills, tools, roster, inChat, menuOff, text, picker, roles])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setSel(0), [items.length, slash?.[1], at?.[2], picker])
  // the highlighted row stays in view as ↑/↓ move it (wrapping included): the list scrolls itself, never the page
  // (scrollIntoView would also scroll the conversation and, on a phone, the window under the keyboard)
  useEffect(() => {
    const ul = menu.current, li = ul?.querySelector<HTMLElement>('[aria-selected="true"]')
    if (!ul || !li) return
    const top = li.offsetTop, bottom = top + li.offsetHeight, pad = 4
    if (top - pad < ul.scrollTop) ul.scrollTop = Math.max(0, top - pad)
    else if (bottom + pad > ul.scrollTop + ul.clientHeight) ul.scrollTop = bottom + pad - ul.clientHeight
  }, [sel, items])

  const named = mentions(text, roster)
  const to = named.length ? named : inChat
  const canSend = !busy && !uploading && (text.trim() || files.length) && to.length > 0

  async function send() {
    if (!canSend) { if (!to.length && (text.trim() || files.length)) setErr('Mention an agent with @ to start this chat.'); return }
    setBusy(true); setErr('')
    try {
      const sentFrom = owner
      const out = expandPasteTokens(text, PASTES)
      if (out.missing.length) throw new Error(`Pasted text #${out.missing.join(', #')} was lost when the page reloaded. Delete the token and paste it again.`)
      if (out.broken) throw new Error('A [Pasted text …] token was edited. Delete it whole, or paste the text again.')
      await onSend(out.text.trim(), files, to)
      for (const m of text.matchAll(/\[Pasted text #(\d+) /g)) PASTES.delete(Number(m[1]))   // sent: freed
      savePastes()
      keepDraft(sentFrom, ''); FILES.delete(sentFrom)     // sent: that conversation's draft is spent, even if we moved on
      if (ownerRef.current === sentFrom) { setText(''); setFiles([]) }
    } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }
  async function addFiles(list: FileList | File[]) {
    setErr('')
    for (const f of Array.from(list)) {
      setUploading((n) => n + 1)
      try { const u = await upload(f, f.name || 'pasted.png'); setFiles((x) => [...x, u]) } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setUploading((n) => n - 1) }
    }
  }
  const dictate = () => (dict.phase === 'live' || dict.phase === 'connecting' ? stopDictation() : startDictation((t) => insert(t)))

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (items.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => (s + 1) % items.length); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => (s - 1 + items.length) % items.length); return }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); items[sel]?.apply(); return }
      if (e.key === 'Escape') { e.preventDefault(); if (picker) setPicker(false); else setMenuOff(true); return }
    }
    // a phone's Enter is a new line (iteration 16): its keyboard has no Shift+Enter, and a message goes out only by the
    // send button, as in WhatsApp. A hardware keyboard (a desktop, a tablet with keys) sends on Enter.
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !touchFirst()) { e.preventDefault(); send(); return }
    if (e.key === 'ArrowUp' && !text) { const l = lastMine(); if (l) { e.preventDefault(); setText(l) } return }
    if (e.key === '.' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); dictate() }
  }

  const live = dict.phase === 'live'
  const hint = placeholder ?? (to.length ? `Message ${to.map(displayName).join(', ')}` : 'Mention an agent with @ to start')
  return (
    <div className={hero ? 'w-full' : 'ws-dock-bottom mx-auto w-full max-w-[760px] px-3 sm:px-4 md:px-6 pt-1'}>
      <div className="ws-composer relative" data-drop={drop}
        onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDrop(true) } }}
        onDragLeave={() => setDrop(false)}
        onDrop={(e) => { setDrop(false); if (e.dataTransfer.files.length) { e.preventDefault(); addFiles(e.dataTransfer.files) } }}>
        {items.length > 0 && (
          <ul ref={menu} role="listbox" aria-label={picker ? 'switch this chat to an agent' : slash ? 'commands' : 'agents'} className="ws-menu absolute left-0 right-0 bottom-full mb-2 max-h-[300px] overflow-y-auto p-1 z-20">
            {picker && <li role="presentation" className="px-2.5 pt-1.5 pb-1 text-[11.5px] text-ink-mute">Switch this chat to… <span className="max-sm:hidden">the new agent starts fresh: earlier messages aren’t sent to it</span></li>}
            {items.map((it, i) => (
              <li key={it.key} role="option" aria-selected={i === sel} onMouseDown={(e) => { e.preventDefault(); it.apply() }} onMouseEnter={() => setSel(i)}
                className={`flex items-center gap-2.5 rounded-[9px] px-2.5 py-1.5 cursor-pointer ${i === sel ? 'bg-[color-mix(in_srgb,var(--t-fg)_7%,transparent)]' : ''}`}>
                {it.kind === 'agent' ? <AgentFace name={it.key.slice(1)} size={20} />
                  : <span className="w-5 text-center text-[11px] text-ink-mute" aria-hidden>{it.kind === 'cmd' ? '/' : it.kind === 'skill' ? '✦' : 'ƒ'}</span>}
                <span className="text-[13px] text-ink shrink-0">{it.label}</span>
                <span className="text-[12px] text-ink-mute truncate">{it.hint}</span>
              </li>
            ))}
          </ul>
        )}
        {(files.length > 0 || uploading > 0) && (
          <div className="flex flex-wrap gap-1.5 px-3.5 pt-3">
            {files.map((f, i) => (
              <span key={f.path} className="inline-flex items-center gap-1.5 rounded-[9px] bg-[color-mix(in_srgb,var(--t-fg)_6%,transparent)] pl-2 pr-1 py-1 text-[12px] text-ink-dim">
                {I.clip('w-3 h-3')}<span className="max-w-[200px] truncate">{f.name}</span>
                <button onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} aria-label={`remove ${f.name}`} className="p-0.5 rounded hover:text-bad">{I.x('w-3 h-3')}</button>
              </span>
            ))}
            {uploading > 0 && <span className="inline-flex items-center gap-1.5 text-[12px] text-ink-mute px-1"><span className="w-3 h-3 rounded-full border-2 border-ink-mute border-t-transparent animate-spin" aria-hidden />Uploading</span>}
          </div>
        )}
        <textarea ref={box} value={text} rows={1} aria-label="message" data-composer
          onChange={(e) => { setText(e.target.value); setMenuOff(false); setPicker(false); setErr('') }}
          onKeyDown={onKey}
          onBlur={() => setPicker(false)}
          onPaste={(e) => { const fs = Array.from(e.clipboardData.files); if (fs.length) { e.preventDefault(); addFiles(fs) } else onPasteText(e) }}
          placeholder={hint}
          className={`block w-full resize-none bg-transparent px-4 outline-none text-ink placeholder:text-ink-mute ${hero ? 'pt-4 pb-1 text-[17px] leading-[1.55]' : 'pt-3.5 pb-1 text-[15px] leading-relaxed'}`} />
        {(live || dict.phase === 'connecting') && (
          <div className="px-4 pb-1 text-[12.5px] text-cyan flex items-center gap-2" role="status">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-cyan" style={{ transform: `scale(${1 + dict.level * 1.6})` }} aria-hidden />
            {dict.partial || (live ? 'Listening. Speech goes to OpenAI for transcription.' : 'Starting the microphone…')}
          </div>
        )}
        <div className="flex items-center gap-0.5 px-2 pb-2 pt-1 max-sm:px-1 max-sm:pb-1">
          <input ref={fileIn} type="file" multiple hidden onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }} />
          <button className="ws-icon" onClick={() => fileIn.current?.click()} title="Attach files (or paste, or drop)" aria-label="attach files">{I.clip()}</button>
          <button className="ws-icon" onClick={dictate} title="Dictate (⌘.)" aria-pressed={live} aria-label="dictate">{live ? <span className="w-2.5 h-2.5 rounded-sm bg-bad animate-pulse" /> : I.mic()}</button>
          {onTalk && to.length > 0 && (
            <button className="ws-icon ws-talk-open" onClick={() => onTalk(to[0])} title={`Talk with ${displayName(to[0])}: a voice conversation (⌘⇧.)`} aria-label={`talk with ${displayName(to[0])}`}>{I.wave()}</button>
          )}
          {to.length > 0 && (
            // the "To" CHIPS (owner 11-13): each agent with its own ×, a hairline between them, and a + that opens the
            // roster to add or remove; the first named leads a team (its reply is the one the human gets)
            <div className="ws-to flex items-center min-w-0 ml-1.5 text-[12px] text-ink-mute" role="group" aria-label={`To ${to.map(displayName).join(', ')}`}>
              <span className="max-sm:hidden mr-1.5">To</span>
              <span className="flex items-center min-w-0 overflow-x-auto [scrollbar-width:none]">
                {to.map((n, i) => (
                  <span key={n} className="flex items-center shrink-0">
                    {i > 0 && <span className="mx-1 h-3.5 w-px bg-line" aria-hidden />}
                    <span className={`inline-flex items-center gap-1 rounded-full pl-0.5 pr-1 py-[1px] text-ink-dim ${i === 0 && to.length > 1 ? 'ws-lead' : ''}`}
                      title={i === 0 && to.length > 1 ? `${displayName(n)} leads: it replies, the others help` : displayName(n)}>
                      <AgentFace name={n} size={16} />
                      <span className="max-w-[9rem] truncate">{displayName(n)}</span>
                      {i === 0 && to.length > 1 && <span className="text-[10px] text-ink-mute">leads</span>}
                      {onSwitch && !named.length && to.length > 1 && (
                        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => onSwitch(to.filter((x) => x !== n))}
                          className="ml-0.5 w-4 h-4 grid place-items-center rounded-full text-ink-mute hover:text-ink hover:bg-[color-mix(in_srgb,var(--t-fg)_8%,transparent)]"
                          aria-label={`remove ${displayName(n)}`} title={`Remove ${displayName(n)}`}>×</button>
                      )}
                    </span>
                  </span>
                ))}
              </span>
              {onSwitch && !named.length && (
                <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => (picker ? setPicker(false) : openPicker())}
                  aria-haspopup="listbox" aria-expanded={picker} aria-label="add or remove agents"
                  className="ml-1 w-5 h-5 shrink-0 grid place-items-center rounded-full border border-line text-ink-mute hover:text-ink hover:border-[var(--t-accent)]"
                  title="Add or remove agents (or type @name)">+</button>
              )}
            </div>
          )}
          {err && <span className="ml-2 text-[12px] text-bad truncate" role="alert">{err}</span>}
          {dict.phase === 'error' && dict.error && !err && <span className="ml-2 text-[12px] text-bad truncate" role="alert">{dict.error}</span>}
          <span className="flex-1 min-w-2" aria-hidden />
          {!touchFirst() && <span className="ws-composer-hint mr-2 text-[11px] text-ink-mute hidden md:inline">{text ? 'Enter to send · Shift+Enter for a line' : '/ for commands · @ for agents'}</span>}
          <button onClick={send} disabled={!canSend} className="ws-send ws-sig shrink-0" aria-label={busy ? 'sending' : 'send'} title="Send (Enter)">
            {busy ? <span className="w-3.5 h-3.5 rounded-full border-2 border-white/70 border-t-transparent animate-spin" /> : I.send('w-[18px] h-[18px]')}
          </button>
        </div>
      </div>
    </div>
  )
})
