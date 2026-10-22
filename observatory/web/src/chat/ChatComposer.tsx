import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { displayName } from '../api'
import AgentFace from '../components/AgentFace'
import { startDictation, stopDictation, useDictation } from './dictate'
import { mentions, upload, type McpTool, type Skill, type Uploaded } from './model'

/* The composer (plan-11884 C3). Everything is a key:
     Enter sends, Shift+Enter breaks a line, ↑ in an empty box brings back your last message,
     / opens commands (the org's real skills and MCP tools, plus /chat's own), @ mentions an agent,
     ⌘. or Ctrl+. dictates, Esc closes a menu.
   A message goes to the agents it @mentions, or to everyone already in the chat. Nothing sends by itself:
   dictation and attachments only ever fill the box. */

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
}>(function ChatComposer({ roster, inChat, skills, tools, commands, lastMine, onSend }, ref) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<Uploaded[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [sel, setSel] = useState(0)
  const [menuOff, setMenuOff] = useState(false)
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

  // autosize, up to a third of the screen
  useEffect(() => {
    const el = box.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = Math.min(el.scrollHeight, Math.round(innerHeight / 3)) + 'px'
  }, [text])

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
  const canSend = !busy && (text.trim() || files.length) && to.length > 0

  async function send() {
    if (!canSend) { if (!to.length) setErr('Mention an agent with @ to start this chat.'); return }
    setBusy(true); setErr('')
    try {
      await onSend(text.trim(), files, to)
      setText(''); setFiles([])
    } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }
  async function addFiles(list: FileList | File[]) {
    setErr('')
    for (const f of Array.from(list)) {
      try { const u = await upload(f, f.name || 'pasted.png'); setFiles((x) => [...x, u]) } catch (e) { setErr(String((e as Error).message ?? e)) }
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
  return (
    <div className="mx-auto w-full max-w-[760px] px-6 pb-5">
      <div className={`relative rounded-2xl border bg-deck-2 transition-colors ${live ? 'border-cyan/60' : 'border-line focus-within:border-line-2'}`}
        onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) e.preventDefault() }}
        onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); addFiles(e.dataTransfer.files) } }}>
        {items.length > 0 && (
          <ul role="listbox" aria-label={slash ? 'commands' : 'agents'} className="absolute left-0 right-0 bottom-full mb-2 max-h-[300px] overflow-y-auto rounded-xl border border-line bg-deck-2 shadow-2xl p-1 z-20">
            {items.map((it, i) => (
              <li key={it.key} role="option" aria-selected={i === sel} onMouseDown={(e) => { e.preventDefault(); it.apply() }} onMouseEnter={() => setSel(i)}
                className={`flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 cursor-pointer ${i === sel ? 'bg-deck-3' : ''}`}>
                {it.kind === 'agent' ? <AgentFace name={it.key.slice(1)} size={20} />
                  : <span className="w-5 text-center text-[11px] text-ink-mute" aria-hidden>{it.kind === 'cmd' ? '/' : it.kind === 'skill' ? '✦' : 'ƒ'}</span>}
                <span className="text-[13px] text-ink shrink-0">{it.label}</span>
                <span className="text-[12px] text-ink-mute truncate">{it.hint}</span>
              </li>
            ))}
          </ul>
        )}
        {files.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3 pt-3">
            {files.map((f, i) => (
              <span key={f.path} className="inline-flex items-center gap-1.5 rounded-lg bg-deck-3 border border-line pl-2 pr-1 py-0.5 text-[12px] text-ink-dim">
                {f.name}
                <button onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} aria-label={`remove ${f.name}`} className="px-1 hover:text-ink">✕</button>
              </span>
            ))}
          </div>
        )}
        <textarea ref={box} value={text} rows={1} aria-label="message"
          onChange={(e) => { setText(e.target.value); setMenuOff(false); setErr('') }}
          onKeyDown={onKey}
          onPaste={(e) => { const fs = Array.from(e.clipboardData.files); if (fs.length) { e.preventDefault(); addFiles(fs) } }}
          placeholder={to.length ? `Message ${to.map(displayName).join(', ')}` : 'Mention an agent with @ to start'}
          className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-[15px] leading-relaxed text-ink placeholder:text-ink-mute outline-none" />
        {(live || dict.phase === 'connecting') && (
          <div className="px-4 pb-1 text-[12.5px] text-cyan flex items-center gap-2" role="status">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-cyan" style={{ transform: `scale(${1 + dict.level * 1.6})` }} aria-hidden />
            {dict.partial || (live ? 'Listening. Speech goes to OpenAI for transcription.' : 'Starting the microphone…')}
          </div>
        )}
        <div className="flex items-center gap-1 px-2 pb-2">
          <input ref={fileIn} type="file" multiple hidden onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }} />
          <button className="chat-tool" onClick={() => fileIn.current?.click()} title="Attach files (or paste, or drop)" aria-label="attach files">＋</button>
          <button className={`chat-tool ${live ? 'text-cyan' : ''}`} onClick={dictate} title="Dictate (⌘.)" aria-pressed={live} aria-label="dictate">◉</button>
          <div className="flex items-center gap-1 ml-1 min-w-0 overflow-hidden">
            {to.slice(0, 5).map((n) => <span key={n} title={`to ${displayName(n)}`}><AgentFace name={n} size={18} /></span>)}
          </div>
          {err && <span className="ml-2 text-[12px] text-bad truncate" role="alert">{err}</span>}
          {dict.phase === 'error' && dict.error && !err && <span className="ml-2 text-[12px] text-bad truncate" role="alert">{dict.error}</span>}
          <span className="ml-auto text-[11.5px] text-ink-mute hidden sm:inline">Enter to send</span>
          <button onClick={send} disabled={!canSend} className="ml-2 rounded-lg px-3 py-1.5 text-[13px] font-medium bg-cyan text-on disabled:opacity-40">
            {busy ? 'Sending' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  )
})
