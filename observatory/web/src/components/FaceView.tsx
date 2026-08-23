import { useCallback, useEffect, useRef, useState } from 'react'
import { api, apiPost, obsKey, saveObsKey } from '../api'
import type { Msg } from '../types'

/* The creature's FACE — the fullscreen surface for the phone mounted on the
   GrowBot body. Not an app with buttons: a being with eyes. Brit's creature app
   splits behavior into engine-owned REFLEXES (instant, no LLM) and the agent;
   this face does the same on the wire:
     touch/shake/pickup -> on-screen reaction + POST /api/growbot/event
       (the API fires a canned body reflex immediately; significant/quiet-period
        events escalate as a wire message to the growbot agent)
     voice -> SpeechRecognition -> the wire -> agent reply -> spoken aloud (TTS)
   Senses: devicemotion (accelerometer+gyro) detects shake and pickup locally —
   perception is free, only events cost anything downstream.
   Screen-on: Wake Lock API when the context allows it; the setup hint covers
   the http-origin case (chrome flag or Android's stay-awake developer option). */

type Mood = 'idle' | 'sleepy' | 'joy' | 'startled' | 'dizzy' | 'listening' | 'speaking' | 'thinking'

const THREAD = 'growbot'
const MOOD_MS: Partial<Record<Mood, number>> = {
  joy: 2600, startled: 1800, dizzy: 2600, speaking: 0, listening: 0, thinking: 0,
}

export default function FaceView() {
  const [mood, setMoodRaw] = useState<Mood>('idle')
  const [gaze, setGaze] = useState({ x: 0, y: 0 })
  const [blink, setBlink] = useState(false)
  const [caption, setCaption] = useState('')
  const [keyOk, setKeyOk] = useState(!!obsKey())
  const [keyVal, setKeyVal] = useState('')
  const [hint, setHint] = useState(false)
  const moodTimer = useRef<number | null>(null)
  const lastActivity = useRef(Date.now())
  const lastSeenId = useRef<number>(0)
  const recRef = useRef<{ stop: () => void } | null>(null)

  const setMood = useCallback((m: Mood) => {
    lastActivity.current = Date.now()
    setMoodRaw(m)
    if (moodTimer.current) window.clearTimeout(moodTimer.current)
    const ttl = MOOD_MS[m]
    if (ttl) moodTimer.current = window.setTimeout(() => setMoodRaw('idle'), ttl)
  }, [])

  /* ---- blinks, wandering gaze, sleepiness ---- */
  useEffect(() => {
    let alive = true
    const blinkLoop = () => {
      if (!alive) return
      setBlink(true)
      window.setTimeout(() => alive && setBlink(false), 140)
      window.setTimeout(blinkLoop, 2600 + Math.random() * 4200)
    }
    const t1 = window.setTimeout(blinkLoop, 1800)
    const gazeIv = window.setInterval(() => {
      setGaze({ x: (Math.random() - 0.5) * 26, y: (Math.random() - 0.5) * 14 })
    }, 2300)
    const sleepIv = window.setInterval(() => {
      if (Date.now() - lastActivity.current > 90_000) setMoodRaw('sleepy')
    }, 5000)
    return () => { alive = false; window.clearTimeout(t1); window.clearInterval(gazeIv); window.clearInterval(sleepIv) }
  }, [])

  /* ---- the screen NEVER turns off (owner law) — two independent holds:
     1. Wake Lock API where the context allows it (secure origin / the flag)
     2. a hidden muted looping video (keepawake.mp4, 1.7 KB) — a playing video
        holds Android Chrome's screen open even on a plain http origin ---- */
  const vidRef = useRef<HTMLVideoElement | null>(null)
  useEffect(() => {
    let lock: { release: () => void } | null = null
    const grab = async () => {
      try {
        lock = await (navigator as Navigator & { wakeLock?: { request: (t: string) => Promise<{ release: () => void }> } })
          .wakeLock?.request('screen') ?? null
      } catch { /* denied or insecure context — the video hold still applies */ }
      vidRef.current?.play().catch(() => undefined)
    }
    grab()
    const revis = () => { if (document.visibilityState === 'visible') grab() }
    document.addEventListener('visibilitychange', revis)
    return () => { document.removeEventListener('visibilitychange', revis); try { lock?.release() } catch { /* gone */ } }
  }, [])

  /* ---- the wire: watch the thread, speak new growbot lines ---- */
  useEffect(() => {
    if (!keyOk) return
    let alive = true
    const poll = async () => {
      try {
        const ms = await api<Msg[]>(`/messages?thread=${THREAD}&limit=8`)
        if (!alive || !ms.length) return
        if (lastSeenId.current === 0) { lastSeenId.current = ms[ms.length - 1].id; return }
        for (const m of ms) {
          if (m.id > lastSeenId.current && m.from !== 'owner') {
            lastSeenId.current = m.id
            speak(m.body)
          } else if (m.id > lastSeenId.current) {
            lastSeenId.current = m.id
          }
        }
      } catch { /* offline — stay serene */ }
    }
    const iv = window.setInterval(poll, 2500)
    poll()
    return () => { alive = false; window.clearInterval(iv) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyOk])

  const speak = (text: string) => {
    const clean = text.replace(/\[sense\][^]*?$/m, '').slice(0, 300)
    setCaption(clean)
    setMood('speaking')
    try {
      speechSynthesis.cancel()
      const u = new SpeechSynthesisUtterance(clean)
      u.rate = 1.05
      u.pitch = 1.25
      u.onend = () => { setMoodRaw('idle'); window.setTimeout(() => setCaption(''), 4000) }
      speechSynthesis.speak(u)
    } catch { setMoodRaw('idle') }
  }

  /* ---- senses: accelerometer shake + pickup detection ---- */
  useEffect(() => {
    if (!keyOk) return
    let spikes: number[] = []
    let still = Date.now()
    let lastShake = 0
    let lastPickup = 0
    const onMotion = (e: DeviceMotionEvent) => {
      const a = e.accelerationIncludingGravity
      if (!a || a.x == null) return
      const mag = Math.abs(Math.hypot(a.x ?? 0, a.y ?? 0, a.z ?? 0) - 9.81)
      const now = Date.now()
      if (mag > 8) {
        spikes = [...spikes.filter((t) => now - t < 900), now]
        if (spikes.length >= 3 && now - lastShake > 6000) {
          lastShake = now
          spikes = []
          setMood('dizzy')
          apiPost('/growbot/event', { kind: 'shake' }).catch(() => undefined)
        }
      } else if (mag > 2.2) {
        if (now - still > 5000 && now - lastPickup > 15000 && now - lastShake > 3000) {
          lastPickup = now
          setMood('startled')
          window.setTimeout(() => setMoodRaw('joy'), 700)
          apiPost('/growbot/event', { kind: 'pickup' }).catch(() => undefined)
        }
        still = now
      } else {
        if (mag < 1) still = still || now
      }
    }
    window.addEventListener('devicemotion', onMotion)
    return () => window.removeEventListener('devicemotion', onMotion)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyOk])

  /* ---- touch: reflex + possible escalation ---- */
  const onTap = () => {
    if (!keyOk) return
    if (document.fullscreenElement == null) document.documentElement.requestFullscreen?.().catch(() => undefined)
    vidRef.current?.play().catch(() => undefined)   // first gesture arms the screen-hold
    setMood('joy')
    apiPost('/growbot/event', { kind: 'tap' }).catch(() => undefined)
  }

  /* ---- voice ---- */
  const listen = (e: React.MouseEvent | React.TouchEvent) => {
    e.stopPropagation()
    if (recRef.current) { recRef.current.stop(); return }
    // @ts-expect-error webkit prefix
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { setCaption('mic needs the setup step — tap ⚙'); return }
    const rec = new SR()
    rec.lang = 'en-US'
    rec.interimResults = true
    recRef.current = rec
    setMood('listening')
    setCaption('')
    let text = ''
    rec.onresult = (ev: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => {
      text = Array.from({ length: ev.results.length }, (_, i) => ev.results[i][0].transcript).join('')
      setCaption(text)
    }
    rec.onerror = () => { setCaption('mic error — check the setup step (⚙)'); setMoodRaw('idle'); recRef.current = null }
    rec.onend = () => {
      recRef.current = null
      if (text.trim()) {
        setMood('thinking')
        setCaption('…')
        apiPost('/growbot/event', { kind: 'voice', text }).catch(() => { setCaption('wire unreachable'); setMoodRaw('idle') })
      } else setMoodRaw('idle')
    }
    rec.start()
  }

  /* ---- eyes geometry per mood ---- */
  const sleepy = mood === 'sleepy'
  const eyeH = blink ? 4 : sleepy ? 26 : mood === 'startled' ? 96 : mood === 'joy' ? 66 : 78
  const eyeRx = mood === 'startled' ? 46 : 34
  const pupilR = mood === 'startled' ? 16 : mood === 'listening' ? 14 : 11
  const g = mood === 'dizzy' ? { x: 0, y: 0 } : gaze
  const mouth =
    mood === 'joy' || mood === 'speaking'
      ? 'M -46 26 Q 0 66 46 26'
      : mood === 'startled'
        ? 'M -18 34 a 18 14 0 1 0 36 0 a 18 14 0 1 0 -36 0'
        : mood === 'dizzy'
          ? 'M -40 40 q 20 -18 40 0 q 20 18 40 0'
          : sleepy
            ? 'M -30 38 Q 0 46 30 38'
            : 'M -34 32 Q 0 52 34 32'

  if (!keyOk) {
    return (
      <div className="h-dvh grid place-items-center bg-[#05070d] text-[#e8f6ff]">
        <form
          className="text-center"
          onSubmit={(e) => { e.preventDefault(); if (keyVal.trim()) { saveObsKey(keyVal.trim()); setKeyOk(true) } }}
        >
          <div className="text-5xl mb-4">◠ ◠</div>
          <div className="text-sm text-[#7f93ab] mb-4">the creature is private — owner key wakes it</div>
          <input
            type="password" value={keyVal} onChange={(e) => setKeyVal(e.currentTarget.value)}
            className="px-4 py-3 rounded-xl text-center bg-[#101826] border border-[#31466b] text-[#e8f6ff]"
            placeholder="owner key" autoFocus
          />
        </form>
      </div>
    )
  }

  return (
    <div
      className="h-dvh w-full bg-[#05070d] overflow-hidden relative select-none"
      onClick={onTap}
      style={{ touchAction: 'manipulation' }}
    >
      {/* starfield backdrop */}
      <div className="absolute inset-0 opacity-40 starfield" />
      {/* the screen-hold: playing muted video keeps Android awake on any origin */}
      <video ref={vidRef} src="/keepawake.mp4" loop muted playsInline
        className="absolute w-px h-px opacity-0 pointer-events-none" />

      {/* the being */}
      <div className={`absolute inset-0 grid place-items-center transition-transform duration-300 ${mood === 'dizzy' ? 'animate-[wiggle_0.5s_ease-in-out_4]' : ''}`}>
        <svg viewBox="-160 -120 320 260" className="w-[86vw] max-w-[560px]">
          <defs>
            <radialGradient id="glow" cx="50%" cy="50%">
              <stop offset="0%" stopColor="#37e0c8" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#37e0c8" stopOpacity="0" />
            </radialGradient>
          </defs>
          {/* eye glow */}
          <ellipse cx={-62 + g.x * 0.3} cy={-30} rx="60" ry="52" fill="url(#glow)" opacity="0.25" />
          <ellipse cx={62 + g.x * 0.3} cy={-30} rx="60" ry="52" fill="url(#glow)" opacity="0.25" />
          {/* eyes */}
          {[-62, 62].map((cx) => (
            <g key={cx} transform={`translate(${cx} -30)`}>
              <rect x={-eyeRx} y={-eyeH / 2} width={eyeRx * 2} height={eyeH} rx={Math.min(eyeRx, eyeH / 2)}
                fill="#0c1a2e" stroke="#37e0c8" strokeWidth="3.5" />
              {!blink && !sleepy && (
                <circle cx={g.x * 0.55} cy={g.y * 0.55} r={pupilR} fill="#5af0dc">
                  {mood === 'dizzy' && (
                    <animateTransform attributeName="transform" type="rotate" from="0 0 0" to="360 0 0" dur="0.8s" repeatCount="3" />
                  )}
                </circle>
              )}
              {sleepy && <line x1={-eyeRx + 6} y1="0" x2={eyeRx - 6} y2="0" stroke="#37e0c8" strokeWidth="3" strokeLinecap="round" />}
            </g>
          ))}
          {/* mouth */}
          <g transform="translate(0 30)">
            <path d={mouth} fill={mood === 'startled' ? '#0c1a2e' : 'none'} stroke="#37e0c8" strokeWidth="4" strokeLinecap="round">
              {mood === 'speaking' && (
                <animate attributeName="stroke-width" values="4;7;4;6;4" dur="0.6s" repeatCount="indefinite" />
              )}
            </path>
          </g>
          {/* listening ripples */}
          {mood === 'listening' && (
            <circle cx="0" cy="10" r="90" fill="none" stroke="#5ab0ff" strokeWidth="2" opacity="0.6">
              <animate attributeName="r" values="80;140" dur="1.2s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.6;0" dur="1.2s" repeatCount="indefinite" />
            </circle>
          )}
          {/* thinking dots */}
          {mood === 'thinking' && (
            <g fill="#7f93ab">
              {[0, 1, 2].map((i) => (
                <circle key={i} cx={-16 + i * 16} cy="-95" r="5">
                  <animate attributeName="opacity" values="0.2;1;0.2" dur="1.2s" begin={`${i * 0.25}s`} repeatCount="indefinite" />
                </circle>
              ))}
            </g>
          )}
        </svg>
      </div>

      {/* caption — what it heard / what it says */}
      <div className="absolute bottom-24 inset-x-0 text-center px-8 text-[#9fdfd4] text-lg leading-snug min-h-[3.5rem]">
        {caption}
      </div>

      {/* mic */}
      <button
        onClick={listen}
        className={`absolute bottom-5 left-1/2 -translate-x-1/2 w-16 h-16 rounded-full border grid place-items-center text-2xl transition-colors ${
          mood === 'listening' ? 'bg-[#37e0c8] text-[#04110f] border-transparent' : 'bg-[#101826]/80 text-[#7f93ab] border-[#31466b]'
        }`}
      >
        {mood === 'listening' ? '◉' : '🎤'}
      </button>

      {/* setup hint */}
      <button onClick={(e) => { e.stopPropagation(); setHint(!hint) }}
        className="absolute top-4 right-4 text-[#31466b] text-xl">⚙</button>
      {hint && (
        <div onClick={(e) => e.stopPropagation()}
          className="absolute top-12 right-4 left-4 sm:left-auto sm:w-96 rounded-xl border border-[#31466b] bg-[#101826]/95 p-4 text-xs text-[#8fa3bb] leading-relaxed">
          <b className="text-[#e8f6ff]">phone setup (once)</b><br />
          mic + always-on screen need this page treated as secure:<br />
          1. chrome://flags → “Insecure origins treated as secure” → add
          <code className="text-[#37e0c8]"> http://{location.host}</code> → relaunch<br />
          2. or: Android developer options → “Stay awake” (while charging)<br />
          tap the face = it giggles (reflex, no AI call) · shake/pickup = it feels it ·
          🎤 = talk to it, the org answers out loud
        </div>
      )}
    </div>
  )
}
