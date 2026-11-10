import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { startDictation, stopDictation, useDictation } from '../dictate'
import { mentions, upload, type McpTool, type Skill, type Uploaded } from '../model'
import { I } from '../icons'

/* The composer (plan-11884 C3; restyled for the workspace after canvas's Composer + Home). Everything is a key:
     Enter sends, Shift+Enter breaks a line, ↑ in an empty box brings back your last message,
     / opens commands (the org's real skills and MCP tools, plus /chat's own), @ mentions an agent,
     ⌘. or Ctrl+. dictates, Esc closes a menu.
   A message goes to the agents it @mentions, or to everyone already in the chat (shown as the "To" faces). Nothing
   sends by itself: dictation and attachments only ever fill the box. `hero` is the empty state's big well. */

export interface Command { key: string; label: string; hint: string; run: (arg: string) => void | string }
export interface ComposerHandle { focus: () => void; insert: (text: string) => void; set: (text: string) => void; attach: (u: Uploaded) => void }

interface Item { key: string; label: string; hint: string; kind: 'cmd' | 'skill' | 'tool' | 'agent'; apply: () => void }

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
}>(function Composer({ roster, inChat, skills, tools, commands, lastMine, onSend, hero = false, placeholder }, ref) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<Uploaded[]>([])
  const [uploading, setUploading] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [sel, setSel] = useState(0)
  const [menuOff, setMenuOff] = useState(false)
  const [drop, setDrop] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  const fileIn = useRef<HTMLInputElement>(null)
  const dict = useDictation()

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
    attach: (u) => setFiles((f) => [...f, u]),
  }))

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
  }, [slash?.[1], at?.[2], commands, skills, tools, roster, inChat, menuOff, text])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setSel(0), [items.length, slash?.[1], at?.[2]])

  const named = mentions(text, roster)
  const to = named.length ? named : inChat
  const canSend = !busy && !uploading && (text.trim() || files.length) && to.length > 0

  async function send() {
    if (!canSend) { if (!to.length && (text.trim() || files.length)) setErr('Mention an agent with @ to start this chat.'); return }
    setBusy(true); setErr('')
    try {
      await onSend(text.trim(), files, to)
      setText(''); setFiles([])
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
      if (e.key === 'Escape') { e.preventDefault(); setMenuOff(true); return }
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); return }
    if (e.key === 'ArrowUp' && !text) { const l = lastMine(); if (l) { e.preventDefault(); setText(l) } return }
    if (e.key === '.' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); dictate() }
  }

  const live = dict.phase === 'live'
  const hint = placeholder ?? (to.length ? `Message ${to.map(displayName).join(', ')}` : 'Mention an agent with @ to start')
  return (
    <div className={hero ? 'w-full' : 'mx-auto w-full max-w-[760px] px-4 md:px-6 pb-4 md:pb-5 pt-1'}>
      <div className="ws-composer relative" data-drop={drop}
        onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDrop(true) } }}
        onDragLeave={() => setDrop(false)}
        onDrop={(e) => { setDrop(false); if (e.dataTransfer.files.length) { e.preventDefault(); addFiles(e.dataTransfer.files) } }}>
        {items.length > 0 && (
          <ul role="listbox" aria-label={slash ? 'commands' : 'agents'} className="ws-menu absolute left-0 right-0 bottom-full mb-2 max-h-[300px] overflow-y-auto p-1 z-20">
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
        <textarea ref={box} value={text} rows={1} aria-label="message"
          onChange={(e) => { setText(e.target.value); setMenuOff(false); setErr('') }}
          onKeyDown={onKey}
          onPaste={(e) => { const fs = Array.from(e.clipboardData.files); if (fs.length) { e.preventDefault(); addFiles(fs) } }}
          placeholder={hint}
          className={`block w-full resize-none bg-transparent px-4 outline-none text-ink placeholder:text-ink-mute ${hero ? 'pt-4 pb-1 text-[17px] leading-[1.55]' : 'pt-3.5 pb-1 text-[15px] leading-relaxed'}`} />
        {(live || dict.phase === 'connecting') && (
          <div className="px-4 pb-1 text-[12.5px] text-cyan flex items-center gap-2" role="status">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-cyan" style={{ transform: `scale(${1 + dict.level * 1.6})` }} aria-hidden />
            {dict.partial || (live ? 'Listening. Speech goes to OpenAI for transcription.' : 'Starting the microphone…')}
          </div>
        )}
        <div className="flex items-center gap-0.5 px-2 pb-2 pt-1">
          <input ref={fileIn} type="file" multiple hidden onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }} />
          <button className="ws-icon" onClick={() => fileIn.current?.click()} title="Attach files (or paste, or drop)" aria-label="attach files">{I.clip()}</button>
          <button className="ws-icon" onClick={dictate} title="Dictate (⌘.)" aria-pressed={live} aria-label="dictate">{live ? <span className="w-2.5 h-2.5 rounded-sm bg-bad animate-pulse" /> : I.mic()}</button>
          {to.length > 0 && (
            <div className="flex items-center gap-1.5 ml-1.5 min-w-0 overflow-hidden text-[12px] text-ink-mute" title={`To ${to.map(displayName).join(', ')}`}>
              <span className="max-sm:hidden">To</span>
              <span className="flex -space-x-1">{to.slice(0, 5).map((n) => <span key={n} className="rounded-full ring-2 ring-[var(--t-panel)]"><AgentFace name={n} size={18} /></span>)}</span>
              {to.length === 1 && <span className="truncate text-ink-dim max-sm:hidden">{displayName(to[0])}</span>}
            </div>
          )}
          {err && <span className="ml-2 text-[12px] text-bad truncate" role="alert">{err}</span>}
          {dict.phase === 'error' && dict.error && !err && <span className="ml-2 text-[12px] text-bad truncate" role="alert">{dict.error}</span>}
          <span className="ws-composer-hint ml-auto mr-2 text-[11px] text-ink-mute hidden md:inline">{text ? 'Enter to send · Shift+Enter for a line' : '/ for commands · @ for agents'}</span>
          <button onClick={send} disabled={!canSend} className="ws-send ws-sig max-md:ml-auto" aria-label={busy ? 'sending' : 'send'} title="Send (Enter)">
            {busy ? <span className="w-3.5 h-3.5 rounded-full border-2 border-white/70 border-t-transparent animate-spin" /> : I.send('w-[18px] h-[18px]')}
          </button>
        </div>
      </div>
    </div>
  )
})
