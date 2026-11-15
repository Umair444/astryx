import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import { Menu } from '@mantine/core'
import { ACCEPT_WORDS, CODE_WORDS, ORG_KEY, SIGNUP_WORDS, WORDS, acceptLink, linkToken, nextHash, orgKey, readLink, readMe, roleWords, signIn, signInHref, signOut, signUp } from '../auth'
import type { Accept, AuthOrg, LinkInfo, Me, MeState, OrgRequest } from '../auth'
import { agentColor, saveObsKey } from '../api'
import { chooseOrg, chosenOrg, safeBase, setOrg, useCog } from '../cog'
import type { Cog } from '../cog'

/* SIGN-IN SCREENS (goal 11859 U3; the bar is seed's msg 61877 and the owner's Room pick, A ORBIT by default). The visual
   language is ORBIT's: the thing you came for docks at the centre of still, dotted orbits, and your seat is the one
   accent dot on the outer ring. Nothing here moves on its own: the screen's one motion is the walk into an org when you
   pick it (cog.tsx chooseOrg). Tokens only, so every theme restyles it. Loaded only under the LOGIN flag (App.tsx). */

/* The stage: one centred column over the orbits. The orbit is decoration with a meaning (you are about to take a seat),
   so it is aria-hidden and static. */
function Stage({ children, title, lede }: { children: ReactNode; title: string; lede: ReactNode }) {
  return (
    <main className="relative min-h-dvh bg-deck text-ink overflow-hidden grid place-items-center px-4 py-12">
      <div className="relative w-full max-w-[22rem]">
        {/* the orbits wrap the headline only, so no line ever crosses the words under it */}
        <div className="relative">
          <svg aria-hidden viewBox="-320 -64 640 128" className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[640px] max-w-none">
            <ellipse rx="180" ry="34" fill="none" stroke="var(--t-line2)" strokeWidth="1" strokeDasharray="2 6" />
            <ellipse rx="300" ry="58" fill="none" stroke="var(--t-line)" strokeWidth="1" strokeDasharray="2 7" />
            <circle cx="262" cy="28" r="4.5" fill="var(--t-accent)" />
          </svg>
          <h1 className="auth-display relative text-center">{title}</h1>
        </div>
        <p className="mt-10 text-center text-[15px] leading-relaxed text-ink-dim">{lede}</p>
        <div className="mt-9">{children}</div>
      </div>
    </main>
  )
}

function Field({ id, label, type, auto, value, onChange, invalid, inputRef, trailing }: {
  id: string; label: string; type: string; auto: string; value: string; onChange: (v: string) => void
  invalid: boolean; inputRef?: React.Ref<HTMLInputElement>; trailing?: ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-[13px] font-medium text-ink-dim mb-2">{label}</label>
      <div className="auth-well">
        <input id={id} ref={inputRef} type={type} autoComplete={auto} value={value} spellCheck={false}
          autoCapitalize="none" aria-invalid={invalid || undefined} aria-describedby={invalid ? 'auth-error' : undefined}
          onChange={(e) => onChange(e.currentTarget.value)} className="auth-field" data-trailing={trailing ? '' : undefined} />
        {trailing}
      </div>
    </div>
  )
}

/* THE EMAIL CODE's box (auth.ts codeStep): shown once the front has mailed one, under the email it went to */
function CodeField({ sentTo, value, onChange, inputRef, invalid }: {
  sentTo: string; value: string; onChange: (v: string) => void; inputRef: React.Ref<HTMLInputElement>; invalid: boolean
}) {
  return (
    <div>
      <Field id="auth-code" label="Code from your email" type="text" auto="one-time-code" value={value}
        inputRef={inputRef} invalid={invalid} onChange={(v) => onChange(v.replace(/\D/g, '').slice(0, 6))} />
      <p className="mt-2 text-[13px] text-ink-mute" aria-live="polite">{CODE_WORDS.sent(sentTo)}</p>
    </div>
  )
}

type Phase = 'idle' | 'pending' | 'done'

/* SIGN IN (owner 11-13: "make the sign in UI better … the dropdown is so lame and it shouldn't be down there … think
   of astryx"). Two panes on a wide screen, one column on a phone:
     THE SKY   the org's living side: the orb at the centre of its orbits, one dot on the ring per agent awake (the
               public overview's count, the same number the floor shows anyone), the wordmark and one line on what
               this is. Nothing private is ever read here: only /api/cog's names and each org's public overview.
     THE DOOR  WHERE first, then WHO: the org you're signing in to as an identity card (one org: the card, nothing to
               pick; several: a radio group of cards, searchable past six), then email and password, then the button.
   The button names what happens ("Sign in"), says it while it happens ("Signing in…") and once it has ("Signed in").
   A failure keeps what was typed but the password, and puts the cursor where the fix starts. The owner's key stays a
   quiet second door under the form (the same saveObsKey the header's key badge uses). PUBLIC SIGN-UP (cog-rebuild
   Phase 3): "Create your org" appears only when the cog takes sign-ups (/api/cog's `signup`, the front's flag, default
   off) and swaps the form for CreateOrg in place (#/sign-up opens it directly); off, the screen is exactly as before. */
export function SignInScreen() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [reveal, setReveal] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [keyDoor, setKeyDoor] = useState(false)
  const [creating, setCreating] = useState(() => /^#\/sign-up\b/.test(location.hash))
  const emailRef = useRef<HTMLInputElement>(null)
  const pwRef = useRef<HTMLInputElement>(null)
  useEffect(() => { emailRef.current?.focus() }, [])
  // THE ORG: the cog's rooms, public by ruling (plan-11859 I9), preselected to the one you are in, else the front's
  // default (its only org, else the door). One org (no cog): no card, as before
  const [rooms, setRooms] = useState<Rooms | null>(null)
  const [org, setOrgPick] = useState('')
  const [pulse, setPulse] = useState<Record<string, Pulse>>({})
  useEffect(() => {
    let live = true
    cogRooms().then((r) => {
      if (!live || !r || r.orgs.length === 0) return
      const here = chosenOrg()
      setRooms(r)
      setOrgPick(r.orgs.some((o) => o.org === here) ? here! : r.door ?? r.orgs[0].org)
      r.orgs.slice(0, 24).forEach((o) => readPulse(o.base).then((p) => { if (live && p) setPulse((m) => ({ ...m, [o.org]: p })) }))
    })
    return () => { live = false }
  }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (phase !== 'idle') return
    if (!email.trim() || !password) {
      setError(WORDS.empty)
      ;(!email.trim() ? emailRef : pwRef).current?.focus()
      return
    }
    setPhase('pending'); setError(null)
    const out = await signIn(email.trim(), password)
    if (out !== 'ok') {
      setPhase('idle'); setPassword(''); setError(WORDS[out])
      ;(out === 'mismatch' ? emailRef : pwRef).current?.focus()
      return
    }
    setPhase('done')
    if (rooms && org) setOrg(org)                 // into the org picked here: its observatory home after the reload
    await afterSignIn(nextHash())
  }

  const picked = rooms?.orgs.find((o) => o.org === org) ?? null
  const sky = picked ? pulse[picked.org] : undefined
  const canSignUp = !!rooms?.signup
  if (creating && canSignUp) return (
    <main className="auth-room bg-deck text-ink">
      <Sky name={null} pulse={undefined} />
      <section className="auth-door" aria-labelledby="auth-title">
        <CreateOrg taken={rooms!.orgs.map((o) => o.org)} onBack={() => { setCreating(false); location.hash = '#/sign-in' }} />
      </section>
    </main>
  )

  return (
    <main className="auth-room bg-deck text-ink">
      <Sky name={picked?.name ?? null} pulse={sky} />
      <section className="auth-door" aria-labelledby="auth-title">
        <div className="w-full max-w-[25rem]">
          <h1 id="auth-title" className="auth-display">Sign in</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-ink-dim">
            One account opens every org you belong to.
          </p>

          {rooms && (
            <OrgPick rooms={rooms} value={org} onChange={(v) => { setOrgPick(v); setError(null) }} pulse={pulse} />
          )}

          {keyDoor ? (
            <KeyDoor org={rooms ? org : null} base={picked?.base ?? null} onBack={() => { setKeyDoor(false); requestAnimationFrame(() => emailRef.current?.focus()) }} />
          ) : (<>
            <form noValidate onSubmit={submit} className="mt-7 space-y-5">
              <Field id="auth-email" label="Email" type="email" auto="username" value={email} inputRef={emailRef}
                onChange={(v) => { setEmail(v); setError(null) }} invalid={!!error} />
              <Field id="auth-password" label="Password" type={reveal ? 'text' : 'password'} auto="current-password"
                value={password} inputRef={pwRef} onChange={(v) => { setPassword(v); setError(null) }} invalid={!!error}
                trailing={
                  <button type="button" className="auth-reveal" aria-pressed={reveal} aria-controls="auth-password"
                    aria-label={reveal ? 'Hide password' : 'Show password'}
                    onClick={() => { setReveal((r) => !r); pwRef.current?.focus() }}>
                    <EyeIcon open={!reveal} />
                  </button>
                } />
              <p id="auth-error" role="alert" aria-live="assertive" className="auth-error" data-shown={error ? '' : undefined}>
                {error && <><ErrIcon />{error}</>}
              </p>
              <button type="submit" disabled={phase !== 'idle'} className="auth-primary w-full">
                {phase === 'pending' ? 'Signing in…' : phase === 'done' ? 'Signed in' : 'Sign in'}
              </button>
            </form>
            <div className="mt-6 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-[13px]">
              <button type="button" className="auth-link auth-quiet" onClick={() => setKeyDoor(true)}>
                Use an access key instead
              </button>
              <a href="#/" className="auth-link auth-quiet">Back to the floor</a>
            </div>
          </>)}

          <p className="mt-10 pt-5 border-t border-line text-[13px] leading-relaxed text-ink-mute">
            {canSignUp && <>Want an org of your own?{' '}
              <button type="button" className="auth-link" onClick={() => { setCreating(true); setError(null) }}>Create your org</button>
              <br /></>}
            No account yet? Your org's owner adds you.
          </p>
        </div>
      </section>
    </main>
  )
}

/* CREATE YOUR ORG: an account and a request for an org of your own, in one form. The address (/o/<key>) is previewed
   live from the name and can be edited; nothing runs until a cog admin approves it, and the screen says so before you
   send. An existing account uses its own password (the request joins it). Success signs you in and lands on the
   pending screen (your orgs: none yet, the request waiting). */
function CreateOrg({ taken, onBack }: { taken: string[]; onBack: () => void }) {
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  const [keyEdited, setKeyEdited] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [reveal, setReveal] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const codeRef = useRef<HTMLInputElement>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const keyRef = useRef<HTMLInputElement>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const pwRef = useRef<HTMLInputElement>(null)
  useEffect(() => { nameRef.current?.focus() }, [])
  const k = keyEdited ? key : orgKey(name)
  const keyBad = k !== '' && !ORG_KEY.test(k)
  const keyTaken = taken.includes(k)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (phase !== 'idle') return
    if (!name.trim() || !k || !email.trim() || !password) {
      setError(SIGNUP_WORDS.empty)
      ;(!name.trim() ? nameRef : !k ? keyRef : !email.trim() ? emailRef : pwRef).current?.focus()
      return
    }
    if (keyBad || keyTaken) { setError(keyBad ? SIGNUP_WORDS.key : SIGNUP_WORDS.taken); keyRef.current?.focus(); return }
    if (password.length < 12) { setError(SIGNUP_WORDS.short); pwRef.current?.focus(); return }
    setPhase('pending'); setError(null)
    const { out, field } = await signUp(email.trim(), password, name.trim(), k, sentTo ? code : '')
    if (out === 'code-sent' || out === 'bad-code') {          // the password stays: the same submit finishes it
      setPhase('idle'); setSentTo(email.trim()); setCode('')
      setError(out === 'bad-code' ? SIGNUP_WORDS['bad-code'] : null)
      setTimeout(() => codeRef.current?.focus())
      return
    }
    if (out !== 'ok') {
      setPhase('idle'); setPassword(''); setError(SIGNUP_WORDS[out])
      ;(out === 'taken' || field === 'org_key' ? keyRef : field === 'org_name' ? nameRef
        : out === 'mismatch' || out === 'waiting' || field === 'email' ? emailRef : pwRef).current?.focus()
      return
    }
    setPhase('done')
    location.hash = '#/orgs'
    location.reload()
  }

  return (
    <div className="w-full max-w-[25rem]">
      <h1 id="auth-title" className="auth-display">Create your org</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-dim">
        Your own org, with its own agents. A cog admin approves new orgs before anything runs; you'll see it waiting
        when you sign in.
      </p>
      <form noValidate onSubmit={submit} className="mt-7 space-y-5">
        <Field id="signup-name" label="Org name" type="text" auto="organization" value={name} inputRef={nameRef}
          onChange={(v) => { setName(v); setError(null) }} invalid={!!error && !name.trim()} />
        <div>
          <label htmlFor="signup-key" className="block text-[13px] font-medium text-ink-dim mb-2">Address</label>
          <div className="auth-well">
            <input id="signup-key" ref={keyRef} type="text" autoComplete="off" value={k} spellCheck={false}
              autoCapitalize="none" aria-invalid={keyBad || keyTaken || undefined} aria-describedby="signup-key-hint"
              onChange={(e) => { setKey(e.currentTarget.value.toLowerCase()); setKeyEdited(true); setError(null) }}
              className="auth-field auth-field-sm font-mono" />
          </div>
          <p id="signup-key-hint" className="mt-2 text-[13px] text-ink-mute" aria-live="polite">
            {keyTaken ? SIGNUP_WORDS.taken : keyBad ? SIGNUP_WORDS.key
              : k ? <>Your org will live at <span className="font-mono text-ink">/o/{k}</span></> : 'Lowercase letters, digits and dashes.'}
          </p>
        </div>
        <Field id="signup-email" label="Email" type="email" auto="username" value={email} inputRef={emailRef}
          onChange={(v) => { setEmail(v); setError(null); setSentTo(null) }} invalid={!!error && !email.trim()} />
        <Field id="signup-password" label="Password" type={reveal ? 'text' : 'password'} auto="new-password"
          value={password} inputRef={pwRef} onChange={(v) => { setPassword(v); setError(null) }} invalid={!!error && !password}
          trailing={
            <button type="button" className="auth-reveal" aria-pressed={reveal} aria-controls="signup-password"
              aria-label={reveal ? 'Hide password' : 'Show password'}
              onClick={() => { setReveal((r) => !r); pwRef.current?.focus() }}>
              <EyeIcon open={!reveal} />
            </button>
          } />
        <p className="-mt-2 text-[13px] text-ink-mute">At least 12 characters. Already have an account? Use its password.</p>
        {sentTo && <CodeField sentTo={sentTo} value={code} inputRef={codeRef} invalid={!!error}
          onChange={(v) => { setCode(v); setError(null) }} />}
        <p id="auth-error" role="alert" aria-live="assertive" className="auth-error" data-shown={error ? '' : undefined}>
          {error && <><ErrIcon />{error}</>}
        </p>
        <button type="submit" disabled={phase !== 'idle'} className="auth-primary w-full">
          {phase === 'pending' ? 'Creating…' : phase === 'done' ? 'Sent for approval' : sentTo ? 'Confirm and create' : 'Create your org'}
        </button>
      </form>
      <p className="mt-6 text-[13px]">
        <button type="button" className="auth-link auth-quiet" onClick={onBack}>I already have an org: sign in</button>
      </p>
    </div>
  )
}

/* THE SKY: the org at work, drawn, never animated beyond the orb's breath (and that stops under reduced motion). One
   dot on the outer ring per agent awake, at most twelve, so the picture is the number. */
function Sky({ name, pulse }: { name: string | null; pulse?: Pulse }) {
  const dots = Math.min(pulse?.live ?? 0, 12)
  const ring = Array.from({ length: dots }, (_, i) => {
    const a = (-0.55 + (i / Math.max(dots, 1)) * 2) * Math.PI
    return { x: Math.cos(a) * 250, y: Math.sin(a) * 74, near: Math.sin(a) > 0 }
  })
  return (
    <aside className="auth-sky" aria-label="astryx">
      <div className="auth-sky-glow" aria-hidden />
      <div className="relative flex items-center gap-2.5">
        <span className="auth-orb auth-orb-mark" aria-hidden />
        <span className="auth-wordmark">astryx</span>
      </div>
      <div className="auth-sky-stage" aria-hidden>
        <svg viewBox="-300 -110 600 220" className="auth-orbits">
          <ellipse rx="150" ry="44" fill="none" stroke="var(--t-line2)" strokeWidth="1" strokeDasharray="2 6" />
          <ellipse rx="250" ry="74" fill="none" stroke="var(--t-line2)" strokeWidth="1" strokeDasharray="2 7" />
          {ring.filter((d) => !d.near).map((d, i) => <circle key={'f' + i} cx={d.x} cy={d.y} r="3.5" fill="var(--t-accent2)" opacity=".55" />)}
        </svg>
        <span className="auth-orb auth-orb-hero" />
        <svg viewBox="-300 -110 600 220" className="auth-orbits">
          {ring.filter((d) => d.near).map((d, i) => <circle key={'n' + i} cx={d.x} cy={d.y} r="4.5" fill="var(--t-accent)" />)}
        </svg>
      </div>
      <div className="relative">
        <p className="auth-hero-line">Your agents are <em className="auth-sig">already at work.</em></p>
        <p className="mt-4 max-w-[30rem] text-[15px] leading-relaxed text-ink-dim">
          A self-managed org: agents that plan, build and check each other's work in the open. Sign in to take your seat
          among them.
        </p>
        <p className="auth-live" data-ready={pulse ? '' : undefined}>
          {pulse && <><span className="auth-live-dot" aria-hidden />
            {pulse.live} of {pulse.agents} agents awake{name ? <> in <span className="text-ink">{name}</span></> : null}</>}
        </p>
      </div>
    </aside>
  )
}

/* THE ORG, chosen first. One org: an identity card, not a control (nothing to pick). Several: a radio group of the same
   cards (arrow keys move, the native radio carries the state to a screen reader), with a search past six. */
function OrgPick({ rooms, value, onChange, pulse }: {
  rooms: Rooms; value: string; onChange: (v: string) => void; pulse: Record<string, Pulse>
}) {
  const [q, setQ] = useState('')
  if (rooms.orgs.length === 1) {
    const o = rooms.orgs[0]
    return (
      <div className="mt-8">
        <p className="text-[13px] font-medium text-ink-dim mb-2">Signing in to</p>
        <div className="auth-card" data-one="">
          <OrgCardBody o={o} p={pulse[o.org]} />
        </div>
      </div>
    )
  }
  const needle = q.trim().toLowerCase()
  const shown = needle ? rooms.orgs.filter((o) => (o.name + ' ' + o.org).toLowerCase().includes(needle)) : rooms.orgs
  return (
    <fieldset className="mt-8">
      <legend className="text-[13px] font-medium text-ink-dim mb-2">Choose your org</legend>
      {rooms.orgs.length > 6 && (
        <div className="auth-well mb-2">
          <label htmlFor="auth-org-q" className="sr-only">Find an org</label>
          <input id="auth-org-q" type="search" value={q} placeholder="Find an org" spellCheck={false} autoComplete="off"
            onChange={(e) => setQ(e.currentTarget.value)} className="auth-field auth-field-sm" />
        </div>
      )}
      <div className="auth-cards" data-many={rooms.orgs.length > 6 ? '' : undefined}>
        {shown.map((o) => (
          <label key={o.org} className="auth-card" data-checked={o.org === value ? '' : undefined}>
            <input type="radio" name="auth-org" value={o.org} checked={o.org === value} className="sr-only"
              onChange={() => onChange(o.org)} />
            <OrgCardBody o={o} p={pulse[o.org]} />
            <span className="auth-tick" aria-hidden />
          </label>
        ))}
        {shown.length === 0 && <p className="px-1 py-3 text-[13px] text-ink-mute">No org matches “{q}”.</p>}
      </div>
    </fieldset>
  )
}

function OrgCardBody({ o, p }: { o: Room; p?: Pulse }) {
  return (<>
    <span className="auth-orb auth-monogram" style={{ ['--orb' as string]: agentColor(o.org) }} aria-hidden>
      <span>{monogram(o.name)}</span>
    </span>
    <span className="min-w-0 flex-1">
      <span className="block truncate text-[15px] font-medium text-ink">{o.name}</span>
      <span className="block truncate text-[13px] text-ink-mute">
        <span className="font-mono text-[12px]">{o.org}</span>
        {p ? <> · {p.agents} {p.agents === 1 ? 'agent' : 'agents'}</> : null}
      </span>
    </span>
  </>)
}

/* the mark on the org's own orb: the first letter of its name, past a domain's tail and the generic words an org name
   carries ("astryx-org" → "A", "umairfiaz.com" → "U", "north lab" → "NL") */
const GENERIC = new Set(['org', 'inc', 'co', 'ltd', 'llc', 'the', 'hq'])
export function monogram(name: string): string {
  const w = name.replace(/\.[a-z]{2,}$/i, '').split(/[\s._-]+/).filter((x) => x && !GENERIC.has(x.toLowerCase()))
  return ((w[0]?.[0] ?? name[0] ?? '?') + (w.length > 1 ? w[1][0] : '')).toUpperCase()
}

/* THE OWNER'S KEY, the quiet second door: the header key badge's own mechanism (saveObsKey), with the key TRIED against
   whoami first so a wrong one is a calm line here, never a saved key that silently opens nothing. In a cog whoami is
   asked through the picked org's own base, and the org is chosen (its cookie) only once the key has opened it. */
function KeyDoor({ org, base, onBack }: { org: string | null; base: string | null; onBack: () => void }) {
  const [val, setVal] = useState('')
  const [state, setState] = useState<'idle' | 'trying' | 'wrong' | 'down'>('idle')
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { ref.current?.focus() }, [])
  async function go(e: FormEvent) {
    e.preventDefault()
    const k = val.trim()
    if (!k || state === 'trying') return
    setState('trying')
    const at = org && base && safeBase(base) ? base : '/'
    let owner = false
    try {
      const r = await fetch(`${at}api/whoami`, { headers: { 'x-obs-key': k }, cache: 'no-store' })
      if (!r.ok) { setState('down'); return }
      owner = !!(await r.json().catch(() => ({}))).owner
    } catch { setState('down'); return }
    if (!owner) { setState('wrong'); setVal(''); ref.current?.focus(); return }
    saveObsKey(k)
    if (org) setOrg(org)
    location.hash = nextHash()
    location.reload()
  }
  const msg = state === 'wrong' ? "That key didn't open this org." : state === 'down' ? "The org isn't answering. Try again in a moment." : null
  return (
    <form noValidate onSubmit={go} className="mt-7 space-y-5">
      <div>
        <label htmlFor="auth-key" className="block text-[13px] font-medium text-ink-dim mb-2">Access key</label>
        <div className="auth-well">
          <input id="auth-key" ref={ref} type="password" autoComplete="off" value={val} spellCheck={false}
            aria-invalid={!!msg || undefined} aria-describedby={msg ? 'auth-key-error' : undefined}
            onChange={(e) => { setVal(e.currentTarget.value); setState('idle') }} className="auth-field" />
        </div>
      </div>
      <p id="auth-key-error" role="alert" aria-live="assertive" className="auth-error" data-shown={msg ? '' : undefined}>
        {msg && <><ErrIcon />{msg}</>}
      </p>
      <button type="submit" disabled={state === 'trying'} className="auth-primary w-full">
        {state === 'trying' ? 'Opening…' : 'Open with key'}
      </button>
      <div className="text-[13px]">
        <button type="button" className="auth-link auth-quiet" onClick={onBack}>Use email and password</button>
      </div>
    </form>
  )
}

function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" />
      {!open && <path d="M4 4l16 16" />}
    </svg>
  )
}

function ErrIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden className="shrink-0 mt-[2px]">
      <circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5" /><path d="M12 16.5h.01" />
    </svg>
  )
}

/* After signing in: one org, or a cog where the viewer is already in one of theirs, goes straight back to where they
   were. A cog with no org of theirs chosen yet shows their orgs first. The reload is the switch to the session: every
   read after it carries the cookie. */
async function afterSignIn(next: string) {
  const m = await readMe()
  const cogOrgs = await cogOrgNames()
  const mine = m.state === 'in' ? switchable(m.me.orgs, cogOrgs) : []
  const here = chosenOrg()
  const needsPick = cogOrgs !== null && !mine.some((o) => o.org === here)
  location.hash = needsPick ? `#/orgs?next=${encodeURIComponent(next.slice(1))}` : next
  location.reload()
}

/* The cog's rooms (registry name, federation name) and its default org, or null on one org. Public (the owner ruled the
   names public, plan-11859 I9). */
interface Room { org: string; name: string; base: string }
interface Rooms { orgs: Room[]; door: string | null; signup: boolean }
async function cogRooms(): Promise<Rooms | null> {
  try {
    const r = await fetch('/api/cog', { credentials: 'same-origin' })
    if (!r.ok) return null
    const j = await r.json()
    if (!j || j.cog !== true || !Array.isArray(j.orgs)) return null
    const orgs = j.orgs.filter((o: { org: unknown; name: unknown }) => o && typeof o.org === 'string' && o.org &&
      typeof o.name === 'string').map((o: { org: string; name: string; base: unknown }) =>
      ({ org: o.org, name: o.name, base: safeBase(o.base) ? o.base : '' }))
    return { orgs, door: typeof j.door === 'string' ? j.door : null, signup: j.signup === true }
  } catch { return null }
}

/* an org's pulse for the sign-in: agents awake of agents, from its PUBLIC overview (the count the floor shows anyone),
   read through its own base; anything else is no pulse, and the screen simply doesn't mention it */
interface Pulse { live: number; agents: number }
async function readPulse(base: string): Promise<Pulse | null> {
  if (!base || !safeBase(base)) return null
  try {
    const r = await fetch(`${base}api/overview`, { credentials: 'same-origin' })
    if (!r.ok) return null
    const j = await r.json()
    return Number.isFinite(j?.live) && Number.isFinite(j?.agents) && j.agents > 0 ? { live: j.live, agents: j.agents } : null
  } catch { return null }
}

async function cogOrgNames(): Promise<string[] | null> {
  const r = await cogRooms()
  return r ? r.orgs.map((o) => o.org) : null
}

/* The orgs you can switch to here: your membership (never the cog's room list, which is everyone's), and in a cog only
   the ones this cog serves. */
export function switchable(mine: AuthOrg[], cogOrgs: string[] | null): AuthOrg[] {
  return cogOrgs === null ? mine : mine.filter((o) => cogOrgs.includes(o.org))
}

export function SignedOutScreen() {
  return (
    <Stage title="Signed out" lede="You're signed out of every org on this device. The floor and the network stay open to everyone.">
      <a href="#/sign-in" className="auth-primary w-full">Sign in again</a>
      <p className="mt-6 text-center text-[13px]"><a href="#/" className="auth-link">Back to the floor</a></p>
    </Stage>
  )
}

/* Your orgs. Picking one walks you into it (the cookie, then the reload: cog.tsx). The one you're in is marked and
   doesn't walk anywhere. */
export function OrgListScreen() {
  const cog = useCog()
  const [me, setMe] = useState<MeState | null>(null)
  useEffect(() => { readMe().then(setMe) }, [])
  useEffect(() => { if (me?.state === 'out') location.hash = signInHref() }, [me])
  if (!me || me.state === 'out') return <main className="min-h-dvh bg-deck" aria-busy="true" />
  if (me.state === 'unavailable') return (
    <Stage title="Your orgs" lede="Sign-in isn't answering, so your orgs can't be listed. Try again in a moment.">
      <a href="#/" className="auth-primary w-full">Back to the floor</a>
    </Stage>
  )
  return <OrgList me={me.me} cog={cog} />
}

function OrgList({ me, cog }: { me: Me; cog: Cog }) {
  const orgs = switchable(me.orgs, cog.cog ? cog.orgs.map((o) => o.org ?? '').filter(Boolean) : null)
  const here = cog.cog ? chosenOrg() : orgs[0]?.org ?? null
  const next = nextHash()
  if (orgs.length === 0 && me.requests.length > 0) return <Pending me={me} req={me.requests[0]} />
  if (orgs.length === 0) return (
    <Stage title="No orgs yet" lede={<>You're signed in as <span className="text-ink">{me.user}</span>, but not a member of any org here. Ask an org's owner to add you.</>}>
      <SignOutButton />
    </Stage>
  )
  return (
    <Stage title="Your orgs" lede={<>Signed in as <span className="text-ink">{me.user}</span>. Pick the org to open; you can switch any time from the header.</>}>
      <ul className="auth-orgs" aria-label="Your orgs">
        {orgs.map((o) => {
          const current = o.org === here
          return (
            <li key={o.org}>
              <button type="button" className="auth-org" aria-current={current || undefined}
                onClick={() => { if (current) location.hash = next; else chooseOrg(o.org) }}>
                <span className="auth-seat" data-current={current || undefined} aria-hidden />
                <span className="min-w-0 flex-1 text-left">
                  <span className="block truncate text-[15px] text-ink">{o.name}</span>
                  <span className="block text-[13px] text-ink-mute">{roleWords(o.role)}</span>
                </span>
                <span className="text-[13px] text-ink-dim shrink-0">{current ? "You're here" : 'Open'}</span>
              </button>
            </li>
          )
        })}
      </ul>
      <div className="mt-7 flex justify-center"><SignOutButton quiet /></div>
    </Stage>
  )
}

/* YOUR ORG IS WAITING (public sign-up): signed in with a request and no org yet. It says where the request stands, in
   words: waiting for a cog admin, approved and being set up, or declined (with the admin's note). Nothing to press but
   sign out; the page reads /auth/me again on the next visit. */
function Pending({ me, req }: { me: Me; req: OrgRequest }) {
  const title = req.state === 'pending' ? 'Your org is waiting for approval' : req.state === 'approved' ? 'Your org is approved'
    : 'Your org was not approved'
  const lede = req.state === 'pending'
    ? <>You asked for <span className="text-ink">{req.name}</span> (<span className="font-mono text-[14px]">/o/{req.key}</span>). A cog admin reviews new orgs before any agent runs; come back after they've looked.</>
    : req.state === 'approved'
      ? <><span className="text-ink">{req.name}</span> is approved and being set up. It opens here once it's ready.</>
      : <><span className="text-ink">{req.name}</span> wasn't approved{req.note ? <>: <span className="text-ink">{req.note}</span></> : '.'}</>
  return (
    <Stage title={title} lede={lede}>
      <p className="mb-6 text-center text-[13px] text-ink-mute">Signed in as <span className="text-ink">{me.user}</span></p>
      <SignOutButton />
    </Stage>
  )
}

/* "Sign out" → "Signing out…" → the signed-out screen. The reload drops every per-session thing the page holds. */
function SignOutButton({ quiet = false }: { quiet?: boolean }) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [failed, setFailed] = useState(false)
  async function go() {
    setPhase('pending'); setFailed(false)
    if (await signOut()) { location.hash = '#/signed-out'; location.reload(); return }
    setPhase('idle'); setFailed(true)
  }
  return (
    <div className="text-center">
      <button type="button" onClick={go} disabled={phase !== 'idle'} className={quiet ? 'auth-link' : 'auth-primary w-full'}>
        {phase === 'pending' ? 'Signing out…' : 'Sign out'}
      </button>
      <p role="alert" className="mt-2 text-[13px] text-bad min-h-[1.3em]">{failed ? WORDS['signout-failed'] : null}</p>
    </div>
  )
}

/* The cog's chooser when sign-in is on: signed out, sign in first; signed in, your orgs (never every room). */
export function AuthChooser({ cog, fallback }: { cog: Cog; fallback: ReactNode }) {
  const [me, setMe] = useState<MeState | null>(null)
  useEffect(() => { readMe().then(setMe) }, [])
  if (!me) return <main className="min-h-dvh bg-deck" aria-busy="true" />
  if (me.state === 'out') return <SignInScreen />
  if (me.state === 'in') return <OrgList me={me.me} cog={cog} />
  return <>{fallback}</>                                        // no sign-in on this front: the building, as today
}

/* The header's account control: "Sign in" when signed out; signed in, who you are, your orgs (when you have more than
   one) and Sign out. */
export function AccountMenu() {
  const [me, setMe] = useState<MeState | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => { readMe().then(setMe) }, [])
  if (!me || me.state === 'unavailable') return null
  if (me.state === 'out') return <a href={signInHref()} className="auth-chip">Sign in</a>
  const many = me.me.orgs.length > 1
  return (
    <Menu position="bottom-end" width={240} shadow="md">
      <Menu.Target>
        <button type="button" className="auth-chip" aria-label={`Account: ${me.me.user}`} title={me.me.user}>
          <span className="auth-initial" aria-hidden>{me.me.user.charAt(0).toUpperCase()}</span>
          <span className="hidden sm:inline max-w-[10rem] truncate">{me.me.user}</span>
        </button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Signed in as {me.me.user}</Menu.Label>
        {many && <Menu.Item component="a" href={`#/orgs?next=${encodeURIComponent(location.hash.slice(1) || '/')}`}>Switch org</Menu.Item>}
        <Menu.Item onClick={async () => {
          if (await signOut()) { location.hash = '#/signed-out'; location.reload() } else setFailed(true)
        }}>{failed ? WORDS['signout-failed'] : 'Sign out'}</Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}

/* A ONE-TIME LINK (#/accept?t=…, the admin panel's invite or reset; front.py /auth/accept). The sign-in's own stage and
   fields: it says what the link opens (the org by name, the role, and where in the tree it applies), asks for what it
   needs (an invite: your email and a password, an existing account proves its own; a reset: a new password for the
   account it names) and, once used, signs you in and walks into the org. A spent or expired link says so, once. */
export function AcceptScreen() {
  const [token] = useState(linkToken)
  const [info, setInfo] = useState<LinkInfo | 'gone' | 'unavailable' | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [reveal, setReveal] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const codeRef = useRef<HTMLInputElement>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const pwRef = useRef<HTMLInputElement>(null)
  useEffect(() => { readLink(token).then(setInfo) }, [token])
  useEffect(() => { if (info && typeof info === 'object') (info.kind === 'reset' ? pwRef : emailRef).current?.focus() }, [info])

  if (info === null) return <main className="min-h-dvh bg-deck" aria-busy="true" />
  if (info === 'gone' || info === 'unavailable') return (
    <Stage title={info === 'gone' ? 'Link expired' : 'Not answering'}
      lede={info === 'gone' ? ACCEPT_WORDS.gone : WORDS.unreachable}>
      <a href="#/sign-in" className="auth-primary w-full">Go to sign in</a>
      <p className="mt-6 text-center text-[13px]"><a href="#/" className="auth-link">Back to the floor</a></p>
    </Stage>
  )
  const link = info
  const reset = link.kind === 'reset'

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (phase !== 'idle') return
    if ((!reset && !email.trim()) || !password) {
      setError(ACCEPT_WORDS.empty)
      ;(!reset && !email.trim() ? emailRef : pwRef).current?.focus()
      return
    }
    setPhase('pending'); setError(null)
    const { out, org } = await acceptLink(token, reset ? '' : email.trim(), password, sentTo ? code : '')
    if (out === 'code-sent' || out === 'bad-code') {
      setPhase('idle'); setSentTo(email.trim()); setCode('')
      setError(out === 'bad-code' ? ACCEPT_WORDS['bad-code'] : null)
      setTimeout(() => codeRef.current?.focus())
      return
    }
    if (out !== 'ok') {
      setPhase('idle'); setPassword(''); setError(ACCEPT_WORDS[out as Exclude<Accept, 'ok' | 'code-sent'>])
      ;(out === 'mismatch' && !reset ? emailRef : pwRef).current?.focus()
      return
    }
    setPhase('done')
    setOrg(org ?? link.org)                      // into the org the link opened, after the reload
    location.hash = '#/'
    location.reload()
  }

  const where = link.node ? <> on <span className="font-mono text-[14px] text-ink">{link.node}</span></> : null
  return (
    <Stage title={reset ? 'New password' : "You're invited"}
      lede={reset
        ? <>Choose a new password for <span className="text-ink">{link.email}</span>. Every device signed in to it is signed out.</>
        : <>Join <span className="text-ink">{link.name}</span> as {article(roleWords(link.role ?? ''))} <span className="text-ink">{roleWords(link.role ?? '')}</span>{where}.</>}>
      <form noValidate onSubmit={submit} className="space-y-5">
        {!reset && (
          <Field id="accept-email" label="Email" type="email" auto="username" value={email} inputRef={emailRef}
            onChange={(v) => { setEmail(v); setError(null); setSentTo(null) }} invalid={!!error} />
        )}
        <Field id="accept-password" label={reset ? 'New password' : 'Password'} type={reveal ? 'text' : 'password'}
          auto="new-password" value={password} inputRef={pwRef}
          onChange={(v) => { setPassword(v); setError(null) }} invalid={!!error}
          trailing={
            <button type="button" className="auth-reveal" aria-pressed={reveal} aria-controls="accept-password"
              aria-label={reveal ? 'Hide password' : 'Show password'}
              onClick={() => { setReveal((r) => !r); pwRef.current?.focus() }}>
              <EyeIcon open={!reveal} />
            </button>
          } />
        <p className="-mt-2 text-[13px] text-ink-mute">
          {reset ? 'At least 12 characters.' : 'New here? Pick a password of at least 12 characters. Already have an account? Use its password.'}
        </p>
        {sentTo && <CodeField sentTo={sentTo} value={code} inputRef={codeRef} invalid={!!error}
          onChange={(v) => { setCode(v); setError(null) }} />}
        <p id="auth-error" role="alert" aria-live="assertive" className="auth-error" data-shown={error ? '' : undefined}>
          {error && <><ErrIcon />{error}</>}
        </p>
        <button type="submit" disabled={phase !== 'idle'} className="auth-primary w-full">
          {phase === 'pending' ? (reset ? 'Saving…' : 'Joining…') : phase === 'done' ? (reset ? 'Saved' : 'Joined')
            : reset ? 'Save and sign in' : `Join ${link.name}`}
        </button>
      </form>
      <p className="mt-6 text-center text-[13px]"><a href="#/sign-in" className="auth-link auth-quiet">I'll sign in instead</a></p>
    </Stage>
  )
}

const article = (w: string) => (/^[aeiou]/i.test(w) ? 'an' : 'a')
