import { forwardRef, Fragment, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { ApiError, apiSend, displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { startDictation, stopDictation, useDictation } from '../dictate'
import { humanName, isHuman } from '../../types'
import { mentions, replyLine, upload, type McpTool, type Reply, type Skill, type Uploaded } from '../model'
import { I } from '../icons'
import { touchFirst } from '../shell/phone'
import { expandPasteTokens, pasteToken } from './code'
import { boxes, calcAt, CLOSE, latexToQalc, OPEN, openCalc, sendText, setResult, settle, splitCalc } from './calc'
import { blocks, drawn, spans, type Span } from './draft'

const PASTE_LINES = 12, PASTE_CHARS = 1500          // a paste this long folds into a token (code.ts pasteToken)
/* this tab's pastes, by token number, kept in sessionStorage beside the drafts (a reload keeps a draft, so it must keep
   the pastes its tokens name); the counter is kept too, so a number is never reused in the tab (medic 12168) */
const PASTE_KEY = 'ws.pastes', SEQ_KEY = 'ws.pastes.seq', PASTE_STORE_MAX = 2_000_000
const PASTES = new Map<number, string>()
let pasteSeq = 0

/* one calculator box's expression, evaluated by the server's Qalculate (calc.ts; observatory/api/calc.py) */
async function calculate(expr: string): Promise<string> {
  const r = await apiSend<{ result: string }>('POST', '/chat/calc', { expr: latexToQalc(expr) })
  return r.result
}
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

/* `group` heads the menu section a command sits under (the chat's own when absent); `arg` names what it takes: picking
   it then fills the box ("/model ") for the argument instead of running it */
export interface Command { key: string; label: string; hint: string; run: (arg: string) => void | string; group?: string; arg?: string }
export interface ComposerHandle { focus: () => void; insert: (text: string) => void; set: (text: string) => void; get: () => string; attach: (u: Uploaded) => void; pick: () => void
  reply: (r: Reply | null) => void }   // answer one message: it rides as a reference (model.replyLine), never the chat

interface Item { key: string; label: string; hint: string; kind: 'cmd' | 'skill' | 'tool' | 'agent'; apply: () => void; group?: string; arg?: string
  pick?: { on: boolean; lead: boolean; makeLead?: () => void } }   // the agent picker's row: chosen, leads, or can be made lead

/* A DRAFT is ONE thing per conversation (owner 11-17: "why the chat text doesnt disappear but attachments does"): its
   words, its attachments and the message it replies to, kept together in the tab's session store on every change,
   whichever box is mounted. */
interface Draft { text: string; files: Uploaded[]; reply?: Reply | null }
const DRAFTS = 'ws.drafts.v2'
function drafts(): Record<string, Draft> { try { return JSON.parse(sessionStorage.getItem(DRAFTS) || '{}') as Record<string, Draft> } catch { return {} } }
function draftOf(key: string): Draft {
  const d = drafts()[key]
  if (d) return { text: d.text ?? '', files: d.files ?? [], reply: d.reply ?? null }
  try {                                          // a draft written before ONE draft (ws.drafts.v1: its text alone)
    const old = (JSON.parse(sessionStorage.getItem('ws.drafts.v1') || '{}') as Record<string, string>)[key]
    return { text: old ?? '', files: [] }
  } catch { return { text: '', files: [] } }
}
function keepDraft(key: string, d: Draft) {
  try {
    const all = drafts()
    if (d.text || d.files.length || d.reply) all[key] = d; else delete all[key]
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
  dictation?: boolean                 // owner 11-17: the mic shows only for a person who holds the dictate feature
  onSwitch?: (agents: string[]) => void   // hand the chat to these agents (the "To" faces' picker, /switch)
  roles?: Record<string, string>
  me?: string                         // the viewer's own handle: a reply to their own message reads "You"
}>(function Composer({ roster, inChat, skills, tools, commands, lastMine, onSend, hero = false, placeholder, draftKey = '', onTalk, onSwitch, roles = {}, dictation = true, me = 'owner' }, ref) {
  const [text, setText] = useState(() => draftOf(draftKey).text)
  const [files, setFiles] = useState<Uploaded[]>(() => draftOf(draftKey).files)
  const [reply, setReply] = useState<Reply | null>(() => draftOf(draftKey).reply ?? null)
  // A DRAFT PER CONVERSATION: the box used to keep its words across a switch, so a line written to finance sat ready
  // to go to seed on Enter; now switching stashes it and brings back that conversation's own (per tab, so a reload
  // or an outage that remounts the workspace keeps it too). Derived state: swapped during render, never a frame late.
  const [owner, setOwner] = useState(draftKey)
  if (owner !== draftKey) {
    keepDraft(owner, { text, files, reply })
    const d = draftOf(draftKey)
    setOwner(draftKey); setText(d.text); setFiles(d.files); setReply(d.reply ?? null)
  }
  useEffect(() => { if (owner === draftKey) keepDraft(owner, { text, files, reply }) }, [owner, draftKey, text, files, reply])
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
    reply: (r) => { setReply(r); requestAnimationFrame(() => box.current?.focus()) },
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
      // A MULTI-SELECT (owner 11-15: "the selection of multiple agents is not good"): every row a tick box; picking
      // adds the agent or takes it out, the first chosen LEADS (it replies, the rest help), any other can be made the
      // lead. The last one can't be removed (a message always goes somewhere).
      return [...cur, ...roster.filter((n) => !cur.includes(n))].map((n) => ({
        key: '@' + n, label: displayName(n), hint: roles[n] ?? '', kind: 'agent' as const,
        pick: { on: cur.includes(n), lead: cur.length > 1 && cur[0] === n,
                makeLead: cur.length > 1 && cur.includes(n) && cur[0] !== n ? () => onSwitch([n, ...cur.filter((x) => x !== n)]) : undefined },
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
        ...commands.map((c) => ({ key: '/' + c.key, label: '/' + c.key, hint: c.hint, kind: 'cmd' as const, group: c.group ?? 'This chat', arg: c.arg,
          apply: () => {
            if (c.arg) { const t = `/${c.key} `; setText(t); requestAnimationFrame(() => { box.current?.focus(); box.current?.setSelectionRange(t.length, t.length) }); return }
            setText(''); const r = c.run(''); if (typeof r === 'string') setErr(r)
          } })),
        ...skills.map((s) => ({ key: 'skill:' + s.name, label: s.name, hint: s.description, kind: 'skill' as const, group: 'Skills', apply: () => setText(`Use the ${s.name} skill: `) })),
        ...tools.map((t) => ({ key: `tool:${t.server}.${t.name}`, label: t.name, hint: `${t.server}${t.description ? ': ' + t.description : ''}`, kind: 'tool' as const, group: 'Tools', apply: () => setText(`Use the ${t.name} tool (${t.server}): `) })),
      ]
      // what the word STARTS is offered before what merely contains it, each kept under its own heading (a stable sort)
      const hit = all.filter((i) => !q || i.label.toLowerCase().includes(q) || i.key.toLowerCase().includes(q))
      const starts = (i: Item) => (q && i.label.replace(/^\//, '').toLowerCase().startsWith(q) ? 0 : 1)
      const order = [...new Set(hit.map((i) => i.group))]
      return hit.sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group) || starts(a) - starts(b)).slice(0, 40)
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
    // the sticky heading above and the key hints below sit OVER the list (owner 11-15: "when I move down the
    // explainers hide it"): the row is kept clear of both, not of the list's bare edges
    const stuck = (sel: string) => ul.querySelector<HTMLElement>(sel)?.offsetHeight ?? 0
    const head = stuck('.ws-menu-group') || stuck('li.sticky.-top-1'), foot = stuck('.ws-menu-foot') || stuck('li.sticky.-bottom-1')
    const top = li.offsetTop, bottom = top + li.offsetHeight, pad = 4 + head, padB = 4 + foot
    if (top - pad < ul.scrollTop) ul.scrollTop = Math.max(0, top - pad)
    else if (bottom + padB > ul.scrollTop + ul.clientHeight) ul.scrollTop = bottom + padB - ul.clientHeight
  }, [sel, items])

  const named = mentions(text, roster)
  // a reply to one agent's message, where several share the chat, goes to that agent (an @mention still wins)
  const to = named.length ? named : reply && inChat.length > 1 && inChat.includes(reply.from) ? [reply.from] : inChat
  const canSend = !busy && !uploading && (text.trim() || files.length) && to.length > 0

  async function send() {
    if (!canSend) { if (!to.length && (text.trim() || files.length)) setErr('Mention an agent with @ to start this chat.'); return }
    setBusy(true); setErr('')
    try {
      const sentFrom = owner
      let calcText = text
      for (const b of [...boxes(text)].reverse()) {          // a box nobody pressed Enter in is evaluated now
        const { expr, result } = splitCalc(b.inner)
        if (result === null && expr) {
          try { calcText = setResult(calcText, b, await answer(expr)).text }
          catch (e) { calcErr(expr, e); throw new Error(`Couldn't calculate “${expr}”. Fix the box or delete it.`) }
        }
      }
      if (calcText !== text) setText(calcText)
      const out = expandPasteTokens(sendText(calcText).text, PASTES)
      if (out.missing.length) throw new Error(`Pasted text #${out.missing.join(', #')} was lost when the page reloaded. Delete the token and paste it again.`)
      if (out.broken) throw new Error('A [Pasted text …] token was edited. Delete it whole, or paste the text again.')
      await onSend(reply ? `${replyLine(reply)}\n${out.text.trim()}` : out.text.trim(), files, to)
      for (const m of text.matchAll(/\[Pasted text #(\d+) /g)) PASTES.delete(Number(m[1]))   // sent: freed
      savePastes()
      keepDraft(sentFrom, { text: '', files: [] })       // sent: that conversation's draft is spent, even if we moved on
      if (ownerRef.current === sentFrom) { setText(''); setFiles([]); setReply(null) }
    } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }
  async function addFiles(list: FileList | File[]) {
    setErr('')
    const into = ownerRef.current                 // an upload lands in the draft it was started in, even after a switch
    for (const f of Array.from(list)) {
      setUploading((n) => n + 1)
      try {
        const u = await upload(f, f.name || 'pasted.png')
        if (ownerRef.current === into) setFiles((x) => [...x, u])
        else { const d = draftOf(into); keepDraft(into, { ...d, files: [...d.files, u] }) }
      } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setUploading((n) => n - 1) }
    }
  }
  const dictate = () => (dict.phase === 'live' || dict.phase === 'connecting' ? stopDictation() : startDictation((t) => insert(t)))

  const mirror = useRef<HTMLDivElement>(null)
  const paint = useMemo(() => drawn(text), [text])
  // A BOX IS A CELL (calc.ts settle): on every caret move the box the caret is in shows its expression, the rest show
  // "expression = answer"; an expression with no answer yet is worked out here and the boxes settle again. Leaving
  // the composer counts as leaving every box (caret -1).
  const known = useRef(new Map<string, string>())       // expression -> its answer, from the server only
  const asking = useRef(new Set<string>())
  // an expression the server refused is never asked again while it reads the same (a 400/422 for good; a 429, a 5xx
  // or a dropped line for a minute): asked at every caret move it spent the viewer's calc quota, Send's too (medic 12231)
  const failed = useRef(new Map<string, number>())
  const skip = (expr: string) => (failed.current.get(expr) ?? 0) > Date.now()
  const calcErr = (expr: string, e: unknown) => {
    const st = e instanceof ApiError ? e.status : 0
    failed.current.set(expr, st >= 400 && st < 500 && st !== 429 ? Infinity : Date.now() + 60_000)
    return `Couldn't calculate “${expr}”: ${String((e as Error).message ?? e).replace(/^\/chat\/calc: /, '')}`
  }
  async function answer(expr: string): Promise<string> {   // the one way a box is worked out: known first, then the server
    const k = known.current.get(expr)
    if (k !== undefined) return k
    const v = await calculate(expr)
    known.current.set(expr, v)
    return v
  }
  // an answer that arrives later settles against the box AS IT IS THEN (its value and caret, read from the element):
  // a remembered caret would pull the cursor back while the person types on
  const now = () => { const el = box.current; return el ? { t: el.value, c: document.activeElement === el ? el.selectionStart ?? -1 : -1 } : null }
  function resettle(t: string, caret: number) {
    if (!t.includes(OPEN)) return
    const r = settle(t, caret, known.current, skip)
    if (r.text !== t) {
      setText(r.text)
      const el = box.current
      if (el && caret >= 0) { el.value = r.text; el.setSelectionRange(r.caret, r.caret) }   // before the next keystroke lands
    }
    for (const expr of r.ask) {
      if (asking.current.has(expr)) continue
      asking.current.add(expr)
      answer(expr).then(() => { const n = now(); if (n) resettle(n.t, n.c) })
        .catch((e) => setErr(calcErr(expr, e)))
        .finally(() => asking.current.delete(expr))
    }
  }
  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (items.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => (s + 1) % items.length); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => (s - 1 + items.length) % items.length); return }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); items[sel]?.apply(); return }
      if (e.key === 'Escape') { e.preventDefault(); if (picker) setPicker(false); else setMenuOff(true); return }
    }
    // ENTER INSIDE A CALCULATOR BOX steps out of it, which resolves it (calc.ts settle), on a phone too
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      const b = calcAt(text, e.currentTarget.selectionStart ?? 0)
      if (b) { e.preventDefault(); e.currentTarget.setSelectionRange(b.end + 1, b.end + 1); resettle(text, b.end + 1); return }   // step out: it resolves
    }
    // a phone's Enter is a new line (iteration 16): its keyboard has no Shift+Enter, and a message goes out only by the
    // send button, as in WhatsApp. A hardware keyboard (a desktop, a tablet with keys) sends on Enter.
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !touchFirst()) { e.preventDefault(); send(); return }
    if (e.key === 'ArrowUp' && !text) { const l = lastMine(); if (l) { e.preventDefault(); setText(l) } return }
    if (e.key === '.' && (e.metaKey || e.ctrlKey) && dictation) { e.preventDefault(); dictate() }
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
          <ul ref={menu} role="listbox" aria-multiselectable={picker || undefined} aria-label={picker ? 'who works on this chat' : slash ? 'commands' : 'agents'} className="ws-menu absolute left-0 right-0 bottom-full mb-2 max-h-[340px] overflow-y-auto p-1 z-20">
            {picker && (
              <li role="presentation" className="sticky -top-1 z-10 bg-[var(--t-panel)] flex items-baseline gap-2 px-2.5 pt-2 pb-1.5">
                <span className="text-[13px] font-medium text-ink">Who works on this?</span>
                <span className="text-[11.5px] text-ink-mute truncate">Pick one or more. The first leads and replies; the others help.</span>
              </li>
            )}
            {items.map((it, i) => (
              <Fragment key={it.key}>
              {slash && it.group && it.group !== items[i - 1]?.group && <li role="presentation" className="ws-menu-group">{it.group}</li>}
              <li role="option" aria-selected={it.pick ? it.pick.on : i === sel} onMouseDown={(e) => { e.preventDefault(); it.apply() }} onMouseEnter={() => setSel(i)}
                className={`group flex items-center gap-2.5 rounded-[9px] px-2.5 py-1.5 cursor-pointer ${i === sel ? 'bg-[color-mix(in_srgb,var(--t-fg)_7%,transparent)]' : ''}`}>
                {it.pick && <span className="ws-check" data-on={it.pick.on || undefined} aria-hidden>{it.pick.on ? '✓' : ''}</span>}
                {it.kind === 'agent' && <AgentFace name={it.key.slice(1)} size={20} />}
                <span className="text-[13px] text-ink shrink-0">{it.label}{it.arg && <span className="text-ink-mute"> {it.arg}</span>}</span>
                <span className="text-[12px] text-ink-mute truncate flex-1 min-w-0">{it.hint}</span>
                {it.pick?.lead && <span className="ws-lead shrink-0 rounded-full px-1.5 py-[1px] text-[10.5px]">Leads</span>}
                {it.pick?.makeLead && (
                  <button type="button" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); it.pick!.makeLead!() }}
                    className="shrink-0 rounded-full border border-line px-1.5 py-[1px] text-[10.5px] text-ink-mute opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-ink">Make lead</button>
                )}
              </li>
              </Fragment>
            ))}
            {slash && !picker && (
              <li role="presentation" className="ws-menu-foot">
                <span><kbd>↑</kbd><kbd>↓</kbd>choose</span><span><kbd>Enter</kbd>run</span><span><kbd>Esc</kbd>close</span>
              </li>
            )}
            {picker && (
              <li role="presentation" className="sticky -bottom-1 z-10 bg-[var(--t-panel)] flex items-center gap-2 px-2.5 pt-1.5 pb-1.5 mt-1 border-t border-line">
                <span className="text-[11.5px] text-ink-mute flex-1 min-w-0 truncate">Agents you add start fresh: earlier messages aren’t sent to them.</span>
                <button type="button" onMouseDown={(e) => { e.preventDefault(); setPicker(false); requestAnimationFrame(() => box.current?.focus()) }}
                  className="shrink-0 rounded-[8px] px-2.5 py-1 text-[12px] font-medium text-ink bg-[color-mix(in_srgb,var(--t-fg)_8%,transparent)] hover:bg-[color-mix(in_srgb,var(--t-fg)_12%,transparent)]">Done</button>
              </li>
            )}
          </ul>
        )}
        {reply && (
          <div className="ws-replying flex items-center gap-2 mx-3 mt-3 rounded-[10px] pl-2.5 pr-1 py-1.5 text-[12.5px] text-ink-dim">
            {I.reply('w-3.5 h-3.5 shrink-0 text-ink-mute')}
            <span className="min-w-0 truncate" title={reply.quote}>
              <span className="text-ink-mute">{reply.from === me ? 'You' : isHuman(reply.from) ? humanName(reply.from) : displayName(reply.from)}: </span>“{reply.quote}”
            </span>
            <button onClick={() => setReply(null)} aria-label="don't reply to this message" className="ml-auto shrink-0 p-1 rounded hover:text-ink">{I.x('w-3.5 h-3.5')}</button>
          </div>
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
        <div className="relative">
        {paint && <DraftMirror ref={mirror} text={text} hero={hero} bad={skip} />}
        <textarea ref={box} value={text} rows={1} aria-label="message" data-composer spellCheck={!paint}
          onChange={(e) => {
            const opened = openCalc(e.target.value, e.target.selectionStart ?? e.target.value.length)   // "= " opens a box
            setText(opened ? opened.text : e.target.value); setMenuOff(false); setPicker(false); setErr('')
            if (opened) { const el = e.target; requestAnimationFrame(() => el.setSelectionRange(opened.caret, opened.caret)) }
          }}
          onScroll={(e) => { if (mirror.current) mirror.current.scrollTop = (e.target as HTMLTextAreaElement).scrollTop }}
          onKeyDown={onKey}
          onSelect={(e) => resettle(e.currentTarget.value, e.currentTarget.selectionStart ?? -1)}
          onBlur={() => { setPicker(false); resettle(text, -1) }}
          onPaste={(e) => { const fs = Array.from(e.clipboardData.files); if (fs.length) { e.preventDefault(); addFiles(fs) } else onPasteText(e) }}
          placeholder={hint}
          className={`relative block w-full resize-none bg-transparent px-4 outline-none placeholder:text-ink-mute ${paint ? 'text-transparent caret-[var(--t-fg)]' : 'text-ink'} ${hero ? 'pt-4 pb-1 text-[17px] leading-[1.55]' : 'pt-3.5 pb-1 text-[15px] leading-relaxed'}`} />
        </div>
        {(live || dict.phase === 'connecting') && (
          <div className="px-4 pb-1 text-[12.5px] text-cyan flex items-center gap-2" role="status">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-cyan" style={{ transform: `scale(${1 + dict.level * 1.6})` }} aria-hidden />
            {dict.partial || (live ? 'Listening. Speech goes to OpenAI for transcription.' : 'Starting the microphone…')}
          </div>
        )}
        <div className="flex items-center gap-0.5 px-2 pb-2 pt-1 max-sm:px-1 max-sm:pb-1">
          <input ref={fileIn} type="file" multiple hidden onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }} />
          <button className="ws-icon" onClick={() => fileIn.current?.click()} title="Attach files (or paste, or drop)" aria-label="attach files">{I.clip()}</button>
          {dictation && <button className="ws-icon" onClick={dictate} title="Dictate (⌘.)" aria-pressed={live} aria-label="dictate">{live ? <span className="w-2.5 h-2.5 rounded-sm bg-bad animate-pulse" /> : I.mic()}</button>}
          {onTalk && to.length > 0 && (
            <button className="ws-icon ws-talk-open" onClick={() => onTalk(to[0])} title={`Talk with ${displayName(to[0])}: a voice conversation (⌘⇧.)`} aria-label={`talk with ${displayName(to[0])}`}>{I.wave()}</button>
          )}
          {to.length > 0 && (
            // the "To" CHIPS (owner 11-13): each agent with its own ×, a hairline between them, and a + that opens the
            // roster to add or remove; the first named leads a team (its reply is the one the human gets). Faces only
            // (owner 11-16): the name is the hover title and the label, the lead its accent ring
            <div className="ws-to flex items-center min-w-0 ml-1.5 text-[12px] text-ink-mute" role="group" aria-label={`To ${to.map(displayName).join(', ')}`}>
              <span className="max-sm:hidden mr-1.5">To</span>
              <span className="flex items-center min-w-0 overflow-x-auto [scrollbar-width:none]">
                {to.map((n, i) => (
                  <span key={n} className="flex items-center shrink-0">
                    {i > 0 && <span className="mx-1 h-3.5 w-px bg-line" aria-hidden />}
                    <span className={`relative inline-flex items-center rounded-full p-[2px] text-ink-dim ${i === 0 && to.length > 1 ? 'ws-lead' : ''}`}
                      title={i === 0 && to.length > 1 ? `${displayName(n)} leads: it replies, the others help` : displayName(n)}>
                      <AgentFace name={n} size={18} />
                      {onSwitch && !named.length && to.length > 1 && (
                        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => onSwitch(to.filter((x) => x !== n))}
                          className="ws-to-x absolute -top-1 -right-1.5 w-3.5 h-3.5 grid place-items-center rounded-full text-[10px] leading-none border border-line bg-[var(--t-panel)] text-ink-mute hover:text-ink"
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

/* THE DRAFT, drawn: the composer's text again, behind the (then transparent) textarea, in its exact type and padding,
   as the chat will show it (thread/draft.ts): a ``` fence a dark block, `code` and each ⟦…⟧ a dark box, **strong** and a
   # heading weighted by a stroke. Each run of lines is one block, so the lines match the textarea's one for one; the
   textarea stays the one thing you type in, so a box edits like any text. */
const DraftMirror = forwardRef<HTMLDivElement, { text: string; hero: boolean; bad?: (expr: string) => boolean }>(function DraftMirror({ text, hero, bad }, ref) {
  const span = (x: Span, key: number) => {
    if (x.kind === 'text') return x.text
    if (x.kind === 'calc') {
      const inner = x.text.slice(1, -1), k = inner.lastIndexOf(' = ')   // the RAW characters, so the box sits exactly under the typed text
      // a box the server refused keeps saying so (a red edge, its reason on hover is the error line), not just once
      return <span key={key} className="ws-calc" data-bad={bad?.(splitCalc(inner).expr) || undefined}><span className="ws-calc-mark">{OPEN}</span>{k < 0 ? inner : <>{inner.slice(0, k)}<span className="ws-calc-eq">{inner.slice(k)}</span></>}<span className="ws-calc-mark">{CLOSE}</span></span>
    }
    if (x.kind === 'code') return <span key={key} className="ws-calc"><span className="ws-calc-mark">`</span>{x.text.slice(1, -1)}<span className="ws-calc-mark">`</span></span>
    if (x.kind === 'strong') return <span key={key} className="ws-md-strong"><span className="ws-md-mark">**</span>{x.text.slice(2, -2)}<span className="ws-md-mark">**</span></span>
    const h = x.text.indexOf(' ')
    return <span key={key} className="ws-md-strong ws-md-head"><span className="ws-md-mark">{x.text.slice(0, h)}</span>{x.text.slice(h)}</span>
  }
  const end = (t: string) => (t === '' || t.endsWith('\n') ? '\u200b' : '')   // a last empty line still takes its height
  return (
    <div ref={ref} aria-hidden className={`absolute inset-x-0 top-0 bottom-0 overflow-hidden pointer-events-none whitespace-pre-wrap break-words px-4 text-ink ${hero ? 'pt-4 pb-1 text-[17px] leading-[1.55]' : 'pt-3.5 pb-1 text-[15px] leading-relaxed'}`}>
      {blocks(text).map((b, i) => {
        if (!b.fence) return <div key={i}>{spans(b.text).map(span)}{end(b.text)}</div>
        const lines = b.text.split('\n'), closed = !!b.closed
        const body = lines.slice(1, closed ? -1 : undefined).join('\n')
        return (
          <div key={i} className="ws-md-fence">
            <span className="ws-calc-mark">{lines[0]}</span>{lines.length > 1 ? '\n' : ''}{body}
            {closed ? <>{'\n'}<span className="ws-calc-mark">{lines[lines.length - 1]}</span></> : end(b.text)}
          </div>
        )
      })}
    </div>
  )
})
