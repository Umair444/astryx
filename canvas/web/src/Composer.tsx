import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { post } from './api'
import { I } from './ui'

interface Att { name: string; line: string }

export function Composer({ onSend, placeholder = 'Message…', onVoice, big, disabled }: {
  onSend: (text: string, attachments: string[]) => Promise<void> | void
  placeholder?: string
  onVoice?: () => void
  big?: boolean
  disabled?: boolean
}) {
  const [text, setText] = useState('')
  const [atts, setAtts] = useState<Att[]>([])
  const [uploading, setUploading] = useState(0)
  const [rec, setRec] = useState<MediaRecorder | null>(null)
  const [transcribing, setTranscribing] = useState(false)
  const ta = useRef<HTMLTextAreaElement>(null)
  const file = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const el = ta.current
    if (!el) return
    // measure only real text, and again whenever the box changes width (a panel animating open
    // from 0px would otherwise measure one character per line)
    const fit = () => {
      el.style.height = 'auto'
      if (el.value) el.style.height = Math.min(el.scrollHeight, 260) + 'px'
      else el.style.height = ''
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [text])

  async function send() {
    const t = text.trim()
    if ((!t && !atts.length) || uploading || disabled) return
    setText(''); setAtts([])
    await onSend(t, atts.map(a => a.line))
    ta.current?.focus()
  }

  async function attach(files: FileList | null) {
    for (const f of Array.from(files ?? [])) {
      setUploading(n => n + 1)
      try {
        const kind = f.type.startsWith('audio/') ? 'audio' : ''
        const r = await post<{ line: string }>('/upload', f, { 'x-filename': f.name, 'x-kind': kind })
        setAtts(a => [...a, { name: f.name, line: r.line }])
      } catch (e) { alert(e instanceof Error ? e.message : 'upload failed') } finally { setUploading(n => n - 1) }
    }
  }

  // dictation: record → local whisper → text in the box (you still press send)
  async function dictate() {
    if (rec) { rec.stop(); return }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const r = new MediaRecorder(stream)
      const chunks: Blob[] = []
      r.ondataavailable = e => chunks.push(e.data)
      r.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        setRec(null); setTranscribing(true)
        try {
          const blob = new Blob(chunks, { type: r.mimeType || 'audio/webm' })
          const res = await post<{ text: string }>('/transcribe', blob, { 'content-type': blob.type })
          if (res.text) setText(t => (t ? t + ' ' : '') + res.text)
        } finally { setTranscribing(false); ta.current?.focus() }
      }
      r.start(); setRec(r)
    } catch { alert('Microphone unavailable — the browser needs https or localhost for mic access.') }
  }

  return (
    <div className={`glass rounded-[22px] ${big ? 'p-3' : 'p-2.5'} focus-within:border-violet/40 transition shadow-xl shadow-black/20`}
      onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); attach(e.dataTransfer.files) }}>
      <AnimatePresence>
        {atts.length > 0 && (
          <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }} className="flex flex-wrap gap-1.5 px-1.5 pb-2 overflow-hidden">
            {atts.map((a, i) => (
              <span key={i} className="flex items-center gap-1.5 text-xs bg-white/[.07] rounded-lg pl-2.5 pr-1 py-1">
                {I.clip('w-3 h-3')} {a.name}
                <button onClick={() => setAtts(x => x.filter((_, j) => j !== i))} className="p-0.5 hover:text-bad">{I.x('w-3 h-3')}</button>
              </span>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      <textarea
        ref={ta} rows={1} value={text} disabled={disabled}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }}
        placeholder={transcribing ? 'Transcribing…' : rec ? 'Listening… click the mic to stop' : placeholder}
        className={`w-full bg-transparent resize-none outline-none px-2 ${big ? 'text-[17px] py-2 min-h-[56px]' : 'py-1.5'} placeholder:text-fg-mute`}
      />
      <div className="flex items-center gap-1 pt-1">
        <input ref={file} type="file" multiple hidden onChange={e => { attach(e.target.files); e.target.value = '' }} />
        <Btn title="Attach" onClick={() => file.current?.click()}>{uploading ? <span className="w-4 h-4 rounded-full border-2 border-fg-mute border-t-transparent animate-spin" /> : I.clip()}</Btn>
        <Btn title={rec ? 'Stop dictation' : 'Dictate'} onClick={dictate} on={!!rec}>
          {rec ? <span className="w-2.5 h-2.5 rounded-sm bg-bad animate-pulse" /> : I.mic()}
        </Btn>
        {onVoice && <Btn title="Voice conversation" onClick={onVoice}>{I.wave()}</Btn>}
        <button onClick={send} disabled={(!text.trim() && !atts.length) || !!uploading || disabled}
          className="ml-auto w-9 h-9 rounded-xl sig grid place-items-center text-white disabled:opacity-30 disabled:grayscale hover:brightness-110 active:scale-95 transition">
          {I.send()}
        </button>
      </div>
    </div>
  )
}

function Btn({ children, onClick, title, on }: { children: React.ReactNode; onClick: () => void; title: string; on?: boolean }) {
  return (
    <button title={title} onClick={onClick}
      className={`w-9 h-9 rounded-xl grid place-items-center transition ${on ? 'bg-bad/15 text-bad' : 'text-fg-dim hover:text-fg hover:bg-white/[.06]'}`}>
      {children}
    </button>
  )
}
