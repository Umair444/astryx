import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import '@fontsource/instrument-serif'
import { Menu } from '@mantine/core'
import { WORDS, nextHash, readMe, roleWords, signIn, signInHref, signOut } from '../auth'
import type { AuthOrg, Me, MeState } from '../auth'
import { chooseOrg, chosenOrg, useCog } from '../cog'
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

function Field({ id, label, type, auto, value, onChange, invalid, inputRef }: {
  id: string; label: string; type: string; auto: string; value: string; onChange: (v: string) => void
  invalid: boolean; inputRef?: React.Ref<HTMLInputElement>
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-[13px] text-ink-dim mb-1.5">{label}</label>
      <input id={id} ref={inputRef} type={type} autoComplete={auto} value={value} spellCheck={false}
        aria-invalid={invalid || undefined} aria-describedby={invalid ? 'auth-error' : undefined}
        onChange={(e) => onChange(e.currentTarget.value)} className="auth-field" />
    </div>
  )
}

type Phase = 'idle' | 'pending' | 'done'

/* Sign in. The button names what happens ("Sign in"), says it while it happens ("Signing in…") and once it has
   ("Signed in"). A failure keeps what was typed but the password, and puts the cursor where the fix starts. */
export function SignInScreen() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const pwRef = useRef<HTMLInputElement>(null)
  useEffect(() => { emailRef.current?.focus() }, [])

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
    await afterSignIn(nextHash())
  }

  return (
    <Stage title="Sign in" lede="Use the email and password your org's owner gave you. One account opens every org you belong to.">
      <form noValidate onSubmit={submit} className="space-y-4">
        <Field id="auth-email" label="Email" type="email" auto="username" value={email} inputRef={emailRef}
          onChange={(v) => { setEmail(v); setError(null) }} invalid={!!error} />
        <Field id="auth-password" label="Password" type="password" auto="current-password" value={password} inputRef={pwRef}
          onChange={(v) => { setPassword(v); setError(null) }} invalid={!!error} />
        <p id="auth-error" role="alert" className="min-h-[2.6em] text-[13px] leading-snug text-bad">{error}</p>
        <button type="submit" disabled={phase !== 'idle'} className="auth-primary w-full">
          {phase === 'pending' ? 'Signing in…' : phase === 'done' ? 'Signed in' : 'Sign in'}
        </button>
      </form>
      <p className="mt-6 text-center text-[13px] text-ink-mute">
        No account yet? Your org's owner adds you. <a href="#/" className="auth-link">Back to the floor</a>
      </p>
    </Stage>
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

/* The cog's rooms by registry name, or null on one org. Public (the owner ruled the names public, plan-11859 I9). */
async function cogOrgNames(): Promise<string[] | null> {
  try {
    const r = await fetch('/api/cog', { credentials: 'same-origin' })
    if (!r.ok) return null
    const j = await r.json()
    return j && j.cog === true && Array.isArray(j.orgs) ? j.orgs.map((o: { org: string }) => o.org).filter(Boolean) : null
  } catch { return null }
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
