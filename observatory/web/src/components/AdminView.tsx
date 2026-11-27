import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Menu, Modal, NumberInput, Select, Switch } from '@mantine/core'
import { agentColor, fmtAgo } from '../api'
import {
  adminCancelInvite, adminInvite, adminReset, adminSignOutEverywhere, adminUsers, adminWords, cogApprove, cogReject,
  cogRequests, roleWords, signInHref,
} from '../auth'
import type { AdminInvite, AdminUser, AdminUsers, CogRequest } from '../auth'
import { safeBase } from '../cog'
import { canAdmin, hereOrg, useMe } from '../me'
import { Action, Empty, Panel, SectionHead, ViewHeader } from '../ui/kit'

/* THE ADMIN PANE (cog-rebuild, owner 11-13: "an option to create new user … whoever is the owner of org can decide the
   roles of other users … it should be managed by an admin … an admin panel in observatory too for each org").
   Two halves, as the server keeps them: ACCOUNTS are the cog's (the front: who has a role here, one-time invite and
   reset links, sign out everywhere; auth.ts), ROLES are this org's own (its /api/admin/members, under its base). There
   is no mail: an invite or a reset is a link shown ONCE, to copy and hand over. An admin manages everyone below owner;
   the server holds every guard (an admin never makes or touches an owner, the last owner stays), and this pane only
   offers what it would allow. Tokens only, so every theme (and light/dark) restyles it; one column on a phone. */

const RANK: Record<string, number> = { owner: 3, admin: 2, member: 1, viewer: 0 }
const PILL: Record<string, string> = {
  owner: 'text-cyan-soft border-cyan/40 bg-cyan/10',
  admin: 'text-good border-good/40 bg-good/10',
  member: 'text-ink-dim border-line-2 bg-deck-3/40',
  viewer: 'text-ink-mute border-line bg-transparent',
}
const ROLE_WHAT: Record<string, string> = {
  owner: 'Everything, including other owners',
  admin: 'Manages people and roles below owner',
  member: 'Works with the agents',
  viewer: 'Looks, never sends',
}

interface Node { node: string; kind: 'org' | 'group' | 'agent'; depth: number }
/* owner 11-17: what a person may use. The org's /api/admin/members says each role's default and the overrides set here;
   no override = the default, so a person nobody touched keeps what they had. An owner has everything, always. */
type Feature = 'dictate' | 'call'
const FEATURE_WORDS: Record<Feature, { title: string; what: string }> = {
  dictate: { title: 'Voice typing and Talk', what: 'Speak into the chat box, or talk with an agent and hear its answers read aloud' },
  call: { title: 'Call', what: 'A live voice call with an agent that sees the screen and can drive it. The dearest' },
}
interface Access { features: Record<Feature, string[]>; overrides: Record<string, Partial<Record<Feature, { allowed: boolean; minutes: number | null }>>> }
const orgRole = (u: AdminUser) => u.role ?? (u.roles.some((r) => r.role !== 'viewer') ? 'member' : 'viewer')
function uses(access: Access | null, u: AdminUser, f: Feature): { on: boolean; minutes: number | null; set: boolean } {
  const role = orgRole(u)
  if (role === 'owner') return { on: true, minutes: null, set: false }
  const o = access?.overrides[u.uid]?.[f]
  return o ? { on: o.allowed, minutes: o.minutes, set: true } : { on: !!access?.features[f]?.includes(role), minutes: null, set: false }
}
type Shown = { kind: 'link'; title: string; link: string; expires: string; note: string } | { kind: 'done'; title: string; note: string }

function RolePill({ role }: { role: string | null }) {
  if (!role) return <span className="text-[12px] text-ink-mute">on parts only</span>
  return (
    <span className={`inline-flex items-center h-5 px-2 rounded-full border text-[11px] font-medium ${PILL[role] ?? PILL.viewer}`}>
      {roleWords(role)}
    </span>
  )
}

function Initial({ email }: { email: string | null }) {
  const c = (email ?? '?').charAt(0).toUpperCase()
  return (
    <span aria-hidden className="grid place-items-center w-8 h-8 rounded-full shrink-0 text-[13px] font-semibold text-[var(--t-on)]"
      style={{ background: agentColor(email ?? '?') }}>{c}</span>
  )
}

/* the org's own half: its members rows, under its base, as this signed-in viewer (the front signs the request) */
async function orgCall(base: string, method: 'GET' | 'PUT' | 'DELETE', path: string, body?: unknown) {
  try {
    const r = await fetch(`${base}api/admin/${path}`, {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: body ? { 'content-type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined,
    })
    const j = await r.json().catch(() => null)
    return r.ok ? { ok: true as const, data: j } : { ok: false as const, why: adminWords(r.status) }
  } catch { return { ok: false as const, why: adminWords(0) } }
}

const nodeLabel = (n: string) => (n === '' ? 'Whole org' : n)
const until = (iso: string) => {
  const h = Math.round((+new Date(iso) - Date.now()) / 3.6e6)
  return h >= 48 ? `${Math.round(h / 24)} days` : h >= 1 ? `${h} hours` : 'under an hour'
}

export default function AdminView() {
  const me = useMe()
  const here = hereOrg(me)
  const org = here?.org ?? ''
  const base = `/o/${org}/`
  const [data, setData] = useState<AdminUsers | null>(null)
  const [nodes, setNodes] = useState<Node[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [inviting, setInviting] = useState(false)
  const [granting, setGranting] = useState<AdminUser | null>(null)
  const [confirm, setConfirm] = useState<{ title: string; body: ReactNode; verb: string; danger?: boolean; go: () => Promise<void> } | null>(null)
  const [shown, setShown] = useState<Shown | null>(null)
  const [activity, setActivity] = useState<{ user: AdminUser; a: Activity | null | false } | null>(null)
  const [access, setAccess] = useState<Access | null>(null)
  const [featuring, setFeaturing] = useState<AdminUser | null>(null)

  const load = useCallback(async () => {
    if (!org) return
    const r = await adminUsers(org)
    if (r.ok) { setData(r.data); setError(null) } else setError(r.why)
    if (r.ok && safeBase(base)) {
      const m = await orgCall(base, 'GET', 'members')
      if (m.ok && m.data?.features) setAccess({ features: m.data.features, overrides: m.data.overrides ?? {} })
    }
    if (r.ok && r.data.tree && safeBase(base)) {
      const n = await orgCall(base, 'GET', 'nodes')
      if (n.ok && Array.isArray(n.data?.nodes)) setNodes(n.data.nodes)
    }
  }, [org, base])
  useEffect(() => { if (canAdmin(me)) load() }, [me, load])

  if (!me) return (
    <div className="h-full grid place-items-center px-4">
      <Empty title="People and roles live here" hint={<>Sign in as this org's owner or an admin to manage them. <a className="text-cyan-soft hover:underline" href={signInHref()}>Sign in</a></>} />
    </div>
  )
  if (!canAdmin(me)) return (
    <div className="h-full grid place-items-center px-4">
      <Empty title="Only the owner and admins manage people" hint="Your role here doesn't include it. Ask the org's owner." />
    </div>
  )

  const you = data?.you ?? here?.role ?? 'admin'
  const mayTouch = (u: AdminUser) => you === 'owner' || !u.roles.some((r) => r.role === 'owner')
  const offered = (data?.roles ?? []).filter((r) => you === 'owner' || r !== 'owner')

  async function act(fn: () => Promise<{ ok: boolean; why?: string }>, after?: () => void) {
    setBusy(true)
    const r = await fn()
    setBusy(false)
    if (!r.ok) { setError(r.why ?? adminWords(502)); return false }
    setError(null)
    after?.()
    await load()
    return true
  }
  const setRole = (u: AdminUser, role: string, node = '') =>
    act(() => orgCall(base, 'PUT', 'members', { uid: u.uid, role, node }))
  const setFeature = (u: AdminUser, feature: Feature, allowed: boolean | null, minutes: number | null) =>
    act(() => orgCall(base, 'PUT', 'features', { uid: u.uid, feature, allowed, minutes }))
  const dropRow = (u: AdminUser, node: string | null) =>
    act(() => orgCall(base, 'DELETE', 'members', node === null ? { uid: u.uid } : { uid: u.uid, node }))

  const users = data?.users ?? []
  const invites = data?.invites ?? []

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1080px] mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <ViewHeader kicker={`${data?.name ?? here?.name ?? org} · admin`} title="People"
          live={data ? <>{users.length} {users.length === 1 ? 'person' : 'people'} with a role here
            {invites.length > 0 && <> · {invites.length} {invites.length === 1 ? 'invite' : 'invites'} open</>}
            <span className="text-ink-mute">· you are {you === 'owner' ? 'an owner' : 'an admin'}</span></> : 'reading…'}
          actions={<Action onClick={() => setInviting(true)} disabled={!data}>+ Invite someone</Action>} />

        {error && (
          <div role="alert" className="mb-5 flex items-start gap-2 rounded-xl border border-bad/30 bg-bad/10 px-3.5 py-2.5 text-[13.5px] text-bad">
            <span aria-hidden>!</span><span className="flex-1">{error}</span>
            <button className="text-ink-mute hover:text-ink text-[12px]" onClick={() => setError(null)}>Dismiss</button>
          </div>
        )}

        <SectionHead title="Members" count={data ? users.length : undefined} />
        <Panel className="overflow-hidden">
          <div className="hidden md:grid grid-cols-[minmax(0,2.4fr)_minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)_40px] gap-3 px-4 py-2.5 border-b border-line text-[11.5px] text-ink-mute">
            <span>Person</span><span>Role</span><span>Where</span><span>Last sign-in</span><span />
          </div>
          {!data && !error && <div className="px-4 py-8 text-[13px] text-ink-mute">Reading the members…</div>}
          {data && users.length === 0 && <Empty title="No one has a role here yet" hint="Invite someone to get started." />}
          <ul>
            {users.map((u) => {
              const parts = u.roles.filter((r) => r.node !== '')
              const touch = mayTouch(u)
              const menu = (
                      <RowMenu u={u} touch={touch} offered={offered} you={you} tree={!!data?.tree} busy={busy}
                        onRole={(r) => setRole(u, r)} onGrant={() => setGranting(u)}
                        onFeatures={access && orgRole(u) !== 'owner' ? () => setFeaturing(u) : undefined}
                        onActivity={async () => {
                          setActivity({ user: u, a: null })
                          const r = await orgCall(base, 'GET', `activity?uid=${encodeURIComponent(u.uid)}`)
                          setActivity({ user: u, a: r.ok ? r.data : false })
                        }}
                        onReset={() => act(async () => {
                          const r = await adminReset(org, u.uid)
                          if (r.ok) setShown({ kind: 'link', title: `Reset link for ${u.email ?? u.uid}`, link: r.data.link,
                            expires: r.data.expires, note: 'Opening it sets a new password and signs them out everywhere. It works once.' })
                          return r
                        })}
                        onSignOut={() => setConfirm({ title: 'Sign out everywhere?', verb: 'Sign out everywhere',
                          body: <>Every device signed in as <b className="text-ink">{u.email}</b> is signed out, in every org. Their roles stay.</>,
                          go: async () => { await act(async () => {
                            const r = await adminSignOutEverywhere(org, u.uid)
                            if (r.ok) setShown({ kind: 'done', title: 'Signed out', note: `${r.data.revoked} ${r.data.revoked === 1 ? 'session' : 'sessions'} ended.` })
                            return r
                          }) } })}
                        onRemove={() => setConfirm({ title: 'Remove from this org?', verb: 'Remove', danger: true,
                          body: <><b className="text-ink">{u.email ?? u.uid}</b> loses every role here. Their account stays, and other orgs keep theirs.</>,
                          go: async () => { await dropRow(u, null) } })} />
              )
              return (
                <li key={u.uid} className="grid grid-cols-[minmax(0,1fr)_40px] md:grid-cols-[minmax(0,2.4fr)_minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)_40px] gap-x-3 gap-y-2 items-center px-4 py-3 border-b border-line last:border-b-0 hover:bg-deck-3/30">
                  <div className="flex items-center gap-3 min-w-0">
                    <Initial email={u.email} />
                    <div className="min-w-0">
                      <div className="text-[14px] text-ink truncate">{u.email ?? <span className="text-ink-mute">an account of another cog</span>}
                        {u.you && <span className="ml-2 text-[11px] text-ink-mute">you</span>}</div>
                      <div className="text-[11.5px] text-ink-mute font-mono truncate">{u.uid}</div>
                    </div>
                  </div>
                  <div className="row-start-1 col-start-2 md:hidden justify-self-end">
                    {menu}
                  </div>
                  <div className="col-span-2 md:col-span-1 flex flex-wrap items-center gap-1.5 pl-11 md:pl-0">
                    <RolePill role={u.role} />
                    {access && orgRole(u) !== 'owner' && (['dictate', 'call'] as Feature[]).filter((f) => uses(access, u, f).on).map((f) => {
                      const x = uses(access, u, f)
                      return <span key={f} title={FEATURE_WORDS[f].what} className="text-[11px] text-ink-mute">
                        {f === 'call' ? 'Call' : 'Voice'}{x.minutes != null ? ` · ${x.minutes} min/day` : ''}</span>
                    })}
                  </div>
                  <div className="col-span-2 md:col-span-1 flex flex-wrap gap-1.5 pl-11 md:pl-0 min-w-0">
                    {u.role && (parts.length > 0 && touch && u.role !== 'owner' ? (
                      <span className="inline-flex items-center gap-1 h-6 pl-2 pr-1 rounded-md border border-line text-[11.5px] text-ink-dim">
                        Whole org
                        <button aria-label="Remove the whole-org role: keep only the parts" title="Remove the whole-org role, so they reach only the parts listed"
                          disabled={busy} className="grid place-items-center w-4 h-4 rounded text-ink-mute hover:text-bad hover:bg-bad/10"
                          onClick={() => dropRow(u, '')}>×</button>
                      </span>) : <span className="text-[12px] text-ink-dim">Whole org</span>)}
                    {parts.map((p) => (
                      <span key={p.node} className="inline-flex items-center gap-1 h-6 pl-2 pr-1 rounded-md border border-line bg-deck-3/40 text-[11.5px] text-ink-dim max-w-full">
                        <span className="font-mono truncate">{p.node}</span><span className="text-ink-mute">· {roleWords(p.role)}</span>
                        {touch && <button aria-label={`Remove ${p.role} on ${p.node}`} disabled={busy}
                          className="grid place-items-center w-4 h-4 rounded text-ink-mute hover:text-bad hover:bg-bad/10"
                          onClick={() => dropRow(u, p.node)}>×</button>}
                      </span>
                    ))}
                  </div>
                  <div className="col-span-2 md:col-span-1 pl-11 md:pl-0 text-[12.5px] text-ink-dim">
                    {u.last_session ? <>{fmtAgo(u.last_session)} ago</> : <span className="text-ink-mute">never</span>}
                    {u.live_sessions > 0 && <span className="ml-2 inline-flex items-center gap-1 text-[11px] text-good">
                      <span className="w-1.5 h-1.5 rounded-full bg-good" aria-hidden />{u.live_sessions} live</span>}
                  </div>
                  <div className="hidden md:block justify-self-end">
                    {menu}
                  </div>
                </li>
              )
            })}
          </ul>
        </Panel>

        {invites.length > 0 && (
          <div className="mt-8">
            <SectionHead title="Open invites" count={invites.length} />
            <Panel className="overflow-hidden">
              <ul>
                {invites.map((i: AdminInvite) => (
                  <li key={i.id} className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-3 border-b border-line last:border-b-0">
                    <RolePill role={i.role} />
                    <span className="text-[12.5px] text-ink-dim">{nodeLabel(i.node)}</span>
                    <span className="text-[12px] text-ink-mute">by {i.by ?? '—'} · expires in {until(i.expires)}</span>
                    {(you === 'owner' || i.role !== 'owner') && (
                      <button className="ml-auto text-[12.5px] text-ink-mute hover:text-bad" disabled={busy}
                        onClick={() => act(() => adminCancelInvite(org, i.id))}>Cancel invite</button>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
        )}

        <p className="mt-8 text-[12.5px] text-ink-mute leading-relaxed max-w-[60ch]">
          Roles: <b className="text-ink-dim">Owner</b> {ROLE_WHAT.owner.toLowerCase()}. <b className="text-ink-dim">Admin</b> {ROLE_WHAT.admin.toLowerCase()}.
          {' '}<b className="text-ink-dim">Member</b> {ROLE_WHAT.member.toLowerCase()}. <b className="text-ink-dim">Viewer</b> {ROLE_WHAT.viewer.toLowerCase()}.
          {data?.tree && <> A role on a group or agent applies to everything under it.</>}
        </p>

        {me.cogAdmin && <CogSection />}
      </div>

      <InviteModal open={inviting} onClose={() => setInviting(false)} roles={offered} nodes={data?.tree ? nodes : []}
        onCreate={async (role, node) => {
          const r = await adminInvite(org, role, node)
          if (!r.ok) return r.why
          setInviting(false)
          setShown({ kind: 'link', title: `Invite: ${roleWords(role)}${node ? ` on ${node}` : ''}`, link: r.data.link,
            expires: r.data.expires, note: 'Send it to the person. Opening it lets them create an account (or use theirs) and join. It works once.' })
          load()
          return null
        }} />
      <GrantModal user={granting} onClose={() => setGranting(null)} roles={offered} nodes={nodes}
        onGrant={async (role, node) => { if (granting && await setRole(granting, role, node)) setGranting(null) }} />
      <Modal opened={!!confirm} onClose={() => setConfirm(null)} title={confirm?.title} centered radius="lg">
        <p className="text-[14px] text-ink-dim leading-relaxed">{confirm?.body}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button className="px-4 py-2 rounded-xl text-[13px] text-ink-dim hover:text-ink" onClick={() => setConfirm(null)}>Cancel</button>
          <Action disabled={busy} className={confirm?.danger ? '!text-bad' : ''}
            onClick={async () => { const c = confirm; setConfirm(null); await c?.go() }}>{confirm?.verb}</Action>
        </div>
      </Modal>
      <LinkModal shown={shown} onClose={() => setShown(null)} />
      <FeaturesModal user={featuring} access={access} you={you} onClose={() => setFeaturing(null)}
        onSave={async (f, allowed, minutes) => { await setFeature(featuring!, f, allowed, minutes) }} />
      <Modal opened={!!activity} onClose={() => setActivity(null)} title={activity ? `Activity · ${activity.user.email ?? activity.user.uid}` : ''} centered radius="lg">
        {activity && (activity.a === null ? <p className="text-[13px] text-ink-mute">Reading…</p>
          : activity.a === false ? <p className="text-[13px] text-bad">Couldn't read this account's activity. Close and open it again.</p> : (
          <div className="grid grid-cols-3 gap-3">
            <Fact label={activity.a.scope === 'owner' ? 'Owner messages' : 'Messages sent'} value={String(activity.a.messages)} />
            <Fact label="Threads" value={String(activity.a.threads)} />
            <Fact label="Last sign-in" value={activity.user.last_session ? `${fmtAgo(activity.user.last_session)} ago` : 'never'} />
            {activity.a.voice_minutes_today != null && <Fact label="Voice today" value={`${activity.a.voice_minutes_today} min`} />}
            {activity.a.scope === 'owner' && <p className="col-span-3 text-[12.5px] text-ink-mute leading-relaxed">
              Every message written as the owner, from the chat, WhatsApp and Discord together, not this account alone.</p>}
          </div>
        ))}
      </Modal>
    </div>
  )
}

interface Activity { scope: 'owner' | 'account'; messages: number; threads: number; last_message: string | null; voice_minutes_today?: number }

/* What one person may use (owner 11-17: "an admin can assign a voice chat to a member"). Each feature is on or off for
   them, with an optional daily limit; "Role's default" drops the override. The org's own daily cap holds either way. */
function FeaturesModal({ user, access, you, onClose, onSave }: {
  user: AdminUser | null; access: Access | null; you: string; onClose: () => void
  onSave: (f: Feature, allowed: boolean | null, minutes: number | null) => Promise<void>
}) {
  const [mins, setMins] = useState<Record<Feature, number | ''>>({ dictate: '', call: '' })
  useEffect(() => {
    if (user && access) setMins({ dictate: uses(access, user, 'dictate').minutes ?? '', call: uses(access, user, 'call').minutes ?? '' })
  }, [user, access])
  if (!user || !access) return <Modal opened={false} onClose={onClose}>{null}</Modal>
  const role = orgRole(user)
  return (
    <Modal opened={!!user} onClose={onClose} title={`What ${user.email ?? user.uid} can use`} centered radius="lg">
      <div className="space-y-4">
        {(['dictate', 'call'] as Feature[]).map((f) => {
          const x = uses(access, user, f)
          const def = access.features[f]?.includes(role)
          const limit = mins[f] === '' ? null : Number(mins[f])
          const needsLimit = f === 'call' && you !== 'owner' && !x.on && limit === null   // the server's rule for an admin
          return (
            <div key={f} className="rounded-xl border border-line px-3.5 py-3 space-y-2.5">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-[14px] text-ink">{FEATURE_WORDS[f].title}</div>
                  <div className="text-[12px] text-ink-mute leading-snug">{FEATURE_WORDS[f].what}</div>
                </div>
                <Switch checked={x.on} aria-label={`${FEATURE_WORDS[f].title} for ${user.email ?? user.uid}`}
                  disabled={needsLimit} title={needsLimit ? 'Set daily minutes first' : undefined}
                  onChange={(e) => onSave(f, e.currentTarget.checked, limit)} />
              </div>
              {(x.on || f === 'call') && (
                <div className="flex items-end gap-2">
                  <NumberInput className="w-44" size="xs" label="Daily minutes" placeholder="no limit of their own" min={0} max={1440}
                    value={mins[f]} onChange={(v) => setMins((m) => ({ ...m, [f]: v === '' ? '' : Number(v) }))} />
                  {x.on && <button className="h-[30px] px-3 rounded-lg text-[12.5px] text-ink-dim hover:text-ink border border-line"
                    disabled={limit === x.minutes} onClick={() => onSave(f, true, limit)}>Save limit</button>}
                </div>
              )}
              <div className="text-[11.5px] text-ink-mute">
                {x.set ? <>Set here. A {roleWords(role).toLowerCase()} {def ? 'has it' : "doesn't have it"} by default.{' '}
                  <button className="text-cyan-soft hover:underline" onClick={() => onSave(f, null, null)}>Back to the role's default</button></>
                  : <>The {roleWords(role).toLowerCase()} default.</>}
              </div>
            </div>
          )
        })}
        <p className="text-[12px] text-ink-mute leading-relaxed">Voice runs on the org's OpenAI key. The org's own daily limit holds for everyone; a person's minutes count inside it.</p>
      </div>
    </Modal>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-deck-3/30 px-3 py-2.5">
      <div className="text-[11px] text-ink-mute">{label}</div>
      <div className="mt-1 text-[18px] font-semibold text-ink">{value}</div>
    </div>
  )
}

function RowMenu({ u, touch, offered, you, tree, busy, onRole, onGrant, onFeatures, onActivity, onReset, onSignOut, onRemove }: {
  u: AdminUser; touch: boolean; offered: string[]; you: string; tree: boolean; busy: boolean
  onRole: (r: string) => void; onGrant: () => void; onFeatures?: () => void; onActivity: () => void; onReset: () => void; onSignOut: () => void; onRemove: () => void
}) {
  const roles = [...offered].sort((a, b) => (RANK[b] ?? 0) - (RANK[a] ?? 0))
  return (
    <Menu position="bottom-end" width={240} shadow="md" withinPortal>
      <Menu.Target>
        <button aria-label={`Manage ${u.email ?? u.uid}`} disabled={busy}
          className="grid place-items-center w-8 h-8 rounded-lg text-ink-mute hover:text-ink hover:bg-deck-3/60 disabled:opacity-40">⋯</button>
      </Menu.Target>
      <Menu.Dropdown>
        {touch ? (<>
          <Menu.Label>Role in the whole org</Menu.Label>
          {roles.map((r) => (
            <Menu.Item key={r} onClick={() => onRole(r)} disabled={u.role === r}
              rightSection={u.role === r ? <span className="text-[11px] text-ink-mute">current</span> : null}>
              {roleWords(r)}
            </Menu.Item>
          ))}
          {tree && <Menu.Item onClick={onGrant}>Add a role on a group or agent…</Menu.Item>}
          {onFeatures && <Menu.Item onClick={onFeatures}>What they can use…</Menu.Item>}
          <Menu.Divider />
        </>) : <Menu.Label>{you === 'admin' ? 'Only an owner can change an owner' : ''}</Menu.Label>}
        <Menu.Item onClick={onActivity}>Activity</Menu.Item>
        {touch && <Menu.Item onClick={onReset}>Make a password reset link</Menu.Item>}
        {touch && <Menu.Item onClick={onSignOut}>Sign out everywhere</Menu.Item>}
        {touch && !u.you && <><Menu.Divider /><Menu.Item color="red" onClick={onRemove}>Remove from org</Menu.Item></>}
      </Menu.Dropdown>
    </Menu>
  )
}

function NodeSelect({ nodes, value, onChange }: { nodes: Node[]; value: string; onChange: (v: string) => void }) {
  const data = useMemo(() => nodes.map((n) => ({
    value: n.node, label: n.node === '' ? 'Whole org' : `${'  '.repeat(Math.max(0, n.depth - 1))}${n.node}${n.kind === 'group' ? ' (group)' : ''}`,
  })), [nodes])
  return (
    <Select label="Where it applies" description="A role on a group covers every agent under it" data={data} value={value}
      onChange={(v) => onChange(v ?? '')} searchable allowDeselect={false} nothingFoundMessage="No such part of the tree"
      comboboxProps={{ withinPortal: true }} radius="md" />
  )
}

function RolePick({ roles, value, onChange }: { roles: string[]; value: string; onChange: (r: string) => void }) {
  return (
    <fieldset>
      <legend className="text-[13px] font-medium text-ink-dim mb-2">Role</legend>
      <div className="grid gap-2">
        {roles.map((r) => (
          <label key={r} className={`flex items-start gap-3 rounded-xl border px-3 py-2.5 cursor-pointer ${value === r ? 'border-cyan/50 bg-cyan/10' : 'border-line hover:border-line-2'}`}>
            <input type="radio" name="admin-role" value={r} checked={value === r} onChange={() => onChange(r)} className="mt-1 accent-[var(--t-accent)]" />
            <span><span className="block text-[14px] text-ink">{roleWords(r)}</span>
              <span className="block text-[12px] text-ink-mute">{ROLE_WHAT[r] ?? ''}</span></span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function InviteModal({ open, onClose, roles, nodes, onCreate }: {
  open: boolean; onClose: () => void; roles: string[]; nodes: Node[]; onCreate: (role: string, node: string) => Promise<string | null>
}) {
  const [role, setRole] = useState('member')
  const [node, setNode] = useState('')
  const [why, setWhy] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) { setWhy(null); setNode(''); setRole(roles.includes('member') ? 'member' : roles[roles.length - 1] ?? '') } }, [open, roles])
  return (
    <Modal opened={open} onClose={onClose} title="Invite someone" centered radius="lg">
      <div className="space-y-5">
        <p className="text-[13.5px] text-ink-dim leading-relaxed">You get a one-time link to send them. It's good for 3 days.</p>
        <RolePick roles={[...roles].sort((a, b) => (RANK[b] ?? 0) - (RANK[a] ?? 0))} value={role} onChange={setRole} />
        {nodes.length > 1 && <NodeSelect nodes={nodes} value={node} onChange={setNode} />}
        {why && <p role="alert" className="text-[13px] text-bad">{why}</p>}
        <div className="flex justify-end gap-2">
          <button className="px-4 py-2 rounded-xl text-[13px] text-ink-dim hover:text-ink" onClick={onClose}>Cancel</button>
          <Action disabled={busy || !role} onClick={async () => { setBusy(true); setWhy(await onCreate(role, node)); setBusy(false) }}>
            {busy ? 'Making the link…' : 'Make invite link'}
          </Action>
        </div>
      </div>
    </Modal>
  )
}

function GrantModal({ user, onClose, roles, nodes, onGrant }: {
  user: AdminUser | null; onClose: () => void; roles: string[]; nodes: Node[]; onGrant: (role: string, node: string) => Promise<void>
}) {
  const parts = nodes.filter((n) => n.node !== '')
  const [role, setRole] = useState('member')
  const [node, setNode] = useState('')
  useEffect(() => { if (user) { setRole('member'); setNode(parts[0]?.node ?? '') } }, [user]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Modal opened={!!user} onClose={onClose} title={user ? `A role on part of the org · ${user.email ?? user.uid}` : ''} centered radius="lg">
      <div className="space-y-5">
        <RolePick roles={[...roles].sort((a, b) => (RANK[b] ?? 0) - (RANK[a] ?? 0))} value={role} onChange={setRole} />
        <NodeSelect nodes={parts} value={node} onChange={setNode} />
        <p className="text-[12px] text-ink-mute leading-relaxed">With roles on parts only (no whole-org role), they reach just those
          groups and agents: they see and message nothing else.</p>
        <div className="flex justify-end gap-2">
          <button className="px-4 py-2 rounded-xl text-[13px] text-ink-dim hover:text-ink" onClick={onClose}>Cancel</button>
          <Action disabled={!node} onClick={() => onGrant(role, node)}>Give the role</Action>
        </div>
      </div>
    </Modal>
  )
}

function LinkModal({ shown, onClose }: { shown: Shown | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => setCopied(false), [shown])
  return (
    <Modal opened={!!shown} onClose={onClose} title={shown?.title} centered radius="lg">
      {shown?.kind === 'link' ? (
        <div className="space-y-4">
          <div className="flex items-stretch gap-2">
            <input readOnly value={shown.link} aria-label="One-time link" onFocus={(e) => e.currentTarget.select()}
              className="flex-1 min-w-0 rounded-xl border border-line-2 bg-deck-3/40 px-3 py-2 font-mono text-[12.5px] text-ink" />
            <Action onClick={async () => {
              try { await navigator.clipboard.writeText(shown.link); setCopied(true) } catch { setCopied(false) }
            }}>{copied ? 'Copied' : 'Copy'}</Action>
          </div>
          <p className="text-[13px] text-ink-dim leading-relaxed">{shown.note}</p>
          <p className="text-[12.5px] text-ink-mute">Shown once, here only. Expires in {until(shown.expires)}.</p>
        </div>
      ) : <p className="text-[14px] text-ink-dim">{shown?.note}</p>}
    </Modal>
  )
}

/* THE COG (cog-rebuild Phase 3): for a COG ADMIN only (cog_grants, never an org role). Every request for a new org
   from public sign-up: who asked, the name and address they want, when. Approve sets the org's token budget (no
   agent of a non-primary org runs without one) and asks the provisioner; reject frees the address, with an optional
   note the person sees. A request is decided once; the list shows what became of each. */
const COG_WORDS: Record<number, string> = {
  400: 'The budget is a whole number of tokens above zero, and a note is at most 500 characters.',
  401: 'Your session has ended. Sign in again.',
  403: 'Only a cog admin decides new orgs.',
  404: 'That request no longer exists.',
  409: 'That request was already decided, or an org with that address now exists.',
}
const PROVISION: Record<string, string> = {
  deferred: 'approved; setup waits on the org provisioner',
  done: 'approved and set up',
  failed: 'approved; setup failed',
}

function CogSection() {
  const [rows, setRows] = useState<CogRequest[] | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [budget, setBudget] = useState<Record<number, string>>({})
  const [note, setNote] = useState<Record<number, string>>({})
  const load = useCallback(async () => {
    const r = await cogRequests()
    if (r.ok) { setRows(r.data.requests); setOpen(r.data.signup); setError(null) } else setError(COG_WORDS[r.status] ?? r.why)
  }, [])
  useEffect(() => { load() }, [load])
  const pending = useMemo(() => (rows ?? []).filter((r) => r.state === 'pending'), [rows])
  const decided = useMemo(() => (rows ?? []).filter((r) => r.state !== 'pending').slice(0, 20), [rows])

  async function decide(r: CogRequest, approve: boolean) {
    let res
    if (approve) {
      const n = Number((budget[r.id] ?? '').replace(/[,_\s]/g, ''))
      if (!Number.isInteger(n) || n <= 0) { setError(COG_WORDS[400]); return }
      setBusy(r.id); res = await cogApprove(r.id, n)
    } else { setBusy(r.id); res = await cogReject(r.id, note[r.id] ?? '') }
    setBusy(null)
    if (!res.ok) { setError(COG_WORDS[res.status] ?? res.why); return }
    await load()
  }

  return (
    <section className="mt-10" aria-labelledby="cog-head">
      <div id="cog-head"><SectionHead title="Cog · new org requests" count={rows ? pending.length : undefined}
        right={<span className="text-[11.5px] text-ink-mute">{open ? 'Sign-up is open' : 'Sign-up is closed'}</span>} /></div>
      {error && <p role="alert" className="mb-3 text-[13px] text-bad">{error}</p>}
      <Panel className="overflow-hidden">
        {rows === null && !error && <div className="px-4 py-6 text-[13px] text-ink-mute">Reading the requests…</div>}
        {rows !== null && pending.length === 0 && <div className="px-4 py-6 text-[13px] text-ink-mute">No org is waiting.</div>}
        <ul>
          {pending.map((r) => (
            <li key={r.id} className="px-4 py-3.5 border-b border-line last:border-b-0">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-[14px] text-ink">{r.name}</span>
                <span className="font-mono text-[12px] text-ink-mute">/o/{r.key}</span>
                <span className="text-[12px] text-ink-mute">by {r.email} · {fmtAgo(r.created)} ago</span>
              </div>
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <label className="sr-only" htmlFor={`cog-budget-${r.id}`}>Token budget for {r.name}</label>
                <input id={`cog-budget-${r.id}`} inputMode="numeric" placeholder="Token budget, e.g. 2000000"
                  value={budget[r.id] ?? ''} onChange={(e) => { const v = e.currentTarget.value; setBudget((b) => ({ ...b, [r.id]: v })) }}
                  className="h-9 w-56 rounded-lg border border-line bg-deck-3/40 px-3 text-[13px] text-ink placeholder:text-ink-mute focus-visible:ring-2 focus-visible:ring-cyan/50" />
                <Action disabled={busy === r.id} onClick={() => decide(r, true)}>Approve</Action>
                <label className="sr-only" htmlFor={`cog-note-${r.id}`}>Note if rejected</label>
                <input id={`cog-note-${r.id}`} placeholder="Note (optional)" maxLength={500}
                  value={note[r.id] ?? ''} onChange={(e) => { const v = e.currentTarget.value; setNote((b) => ({ ...b, [r.id]: v })) }}
                  className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-deck-3/40 px-3 text-[13px] text-ink placeholder:text-ink-mute focus-visible:ring-2 focus-visible:ring-cyan/50" />
                <button className="px-3 py-2 rounded-xl text-[13px] text-ink-mute hover:text-bad" disabled={busy === r.id}
                  onClick={() => decide(r, false)}>Reject</button>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
      {decided.length > 0 && (
        <ul className="mt-3 space-y-1">
          {decided.map((r) => (
            <li key={r.id} className="text-[12.5px] text-ink-mute">
              <span className="text-ink-dim">{r.name}</span> <span className="font-mono">/o/{r.key}</span> ·{' '}
              {r.state === 'approved' ? <>{PROVISION[r.provision ?? ''] ?? 'approved'} · budget {r.allowance_tokens?.toLocaleString()}</>
                : <>rejected{r.note ? `: ${r.note}` : ''}</>}
              {r.decided_by && <> · by {r.decided_by}</>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
