import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ScrollArea } from '@mantine/core'
import { Count, Empty, LiveDot, Panel, SectionHead, Skeleton, Spark, Stat, Tabs, ViewHeader } from '../ui/kit'
import { api } from '../api'
import type { SysInfo, Proc } from '../types'

function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—'
  const u = ['B', 'K', 'M', 'G', 'T']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)}${u[i]}`
}

function fmtDur(s: number): string {
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`
}

const hue = (p: number) => (p >= 90 ? 'var(--t-bad)' : p >= 70 ? 'var(--t-warn)' : 'var(--t-good)')

function Bar({ pct, label, sub }: { pct: number; label: string; sub?: string }) {
  return (
    <div className="mb-3 last:mb-0">
      <div className="flex justify-between gap-2 text-[12px] mb-1">
        <span className="text-ink-dim truncate">{label}</span>
        <span className="font-mono text-ink-mute shrink-0">{sub ?? `${pct.toFixed(0)}%`}</span>
      </div>
      <div className="h-2 rounded-full bg-deck/70 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${Math.min(pct, 100)}%`, background: `linear-gradient(90deg, color-mix(in srgb, ${hue(pct)} 55%, transparent), ${hue(pct)})`, boxShadow: `0 0 12px -2px ${hue(pct)}` }}
        />
      </div>
    </div>
  )
}

function Card({ title, aside, children }: { title: string; aside?: string; children: ReactNode }) {
  return (
    <Panel className="p-4">
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-dim">{title}</div>
        {aside && <div className="text-[11px] font-mono text-ink-mute truncate">{aside}</div>}
      </div>
      {children}
    </Panel>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between text-[12px] py-1 border-b border-line/30 last:border-b-0">
      <span className="text-ink-mute">{k}</span>
      <span className="text-ink-dim font-mono truncate ml-2">{v}</span>
    </div>
  )
}

/** A trace on a FIXED 0–100 scale. The kit's Spark scales to its own max, which turns a steady
 *  73% into a full-height block; a percentage must keep its meaning. */
function Trace({ data, color, className = '' }: { data: number[]; color: string; className?: string }) {
  if (data.length < 2) return null
  const W = 100, H = 30
  const pts = data.map((v, i) => `${((i / (data.length - 1)) * W).toFixed(2)},${(H - 1 - (Math.min(100, v) / 100) * (H - 3)).toFixed(2)}`)
  const first = pts[0].split(',')[0]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className={className} aria-hidden>
      <path d={`M${pts.join(' L')} L${W},${H} L${first},${H} Z`} fill={color} opacity={0.14} />
      <path d={`M${pts.join(' L')}`} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  )
}

/** a vital: a live percentage with its last ~80s drawn underneath, on a true 0–100 scale */
function Vital({ label, value, hist, sub }: { label: string; value: number | undefined; hist: number[]; sub?: ReactNode }) {
  const c = value == null ? 'var(--t-accent)' : hue(value)
  return (
    <Panel className="p-4 overflow-hidden">
      <div className="text-[11px] uppercase tracking-[0.14em] text-ink-mute">{label}</div>
      <div className="mt-2 text-[28px] font-semibold tracking-tight leading-none" style={{ color: value != null && value >= 70 ? c : 'var(--t-fg)' }}>
        <Count value={value} format={(n) => `${n.toFixed(0)}%`} />
      </div>
      {sub && <div className="mt-1.5 text-[12px] text-ink-mute relative z-[1]">{sub}</div>}
      <Trace data={hist} color={c} className="absolute right-0 bottom-0 w-[60%] h-12" />
    </Panel>
  )
}

const HIST = 40 // 2s ticks → the last ~80 seconds

const fmtRate = (n: number) => `${fmtBytes(n)}/s`

export default function MonitorView() {
  const [sys, setSys] = useState<SysInfo | null>(null)
  const [procs, setProcs] = useState<Proc[]>([])
  const [psort, setPsort] = useState('cpu')
  const [err, setErr] = useState<string | null>(null)
  // live history from the 2s poll: cpu %, and network rates from successive byte counters
  const [hist, setHist] = useState<{ cpu: number[]; mem: number[]; up: number[]; down: number[] }>({ cpu: [], mem: [], up: [], down: [] })
  const prev = useRef<{ t: number; sent: number; recv: number } | null>(null)

  useEffect(() => {
    let live = true
    const tick = async () => {
      try {
        const s = await api<SysInfo>('/system')
        if (live) {
          setSys(s)
          setErr(null)
          const t = Date.now()
          const p = prev.current
          const dt = p ? (t - p.t) / 1000 : 0
          const up = p && dt > 0 ? Math.max(0, (s.net.sent - p.sent) / dt) : 0
          const down = p && dt > 0 ? Math.max(0, (s.net.recv - p.recv) / dt) : 0
          prev.current = { t, sent: s.net.sent, recv: s.net.recv }
          const push = (a: number[], v: number) => [...a.slice(-(HIST - 1)), v]
          setHist((h) => ({ cpu: push(h.cpu, s.cpu.percent), mem: push(h.mem, s.mem.percent), up: p ? push(h.up, up) : h.up, down: p ? push(h.down, down) : h.down }))
        }
      } catch (e) {
        if (live) setErr(String(e))
      }
    }
    tick()
    const t = setInterval(tick, 2000)
    return () => {
      live = false
      clearInterval(t)
    }
  }, [])

  useEffect(() => {
    let live = true
    const tick = async () => {
      try {
        const p = await api<Proc[]>(`/system/processes?sort=${psort}&limit=40`)
        if (live) setProcs(p)
      } catch {
        /* ignore */
      }
    }
    tick()
    const t = setInterval(tick, 3000)
    return () => {
      live = false
      clearInterval(t)
    }
  }, [psort])

  if (err && !sys)
    return <div className="p-8"><Empty title="The monitor is unavailable" hint={err} tone="bad" /></div>

  const s = sys?.specs
  const root = sys ? (sys.disks.find((d) => d.mount === '/') ?? sys.disks[0]) : undefined
  const hot = sys ? Math.max(0, ...sys.temps.map((t) => t.current)) : 0
  const lastUp = hist.up[hist.up.length - 1], lastDown = hist.down[hist.down.length - 1]
  return (
    <ScrollArea className="h-full">
      <div className="px-4 sm:px-8 pt-7 pb-6 max-w-[1240px] mx-auto">
        <ViewHeader
          kicker="the org's body"
          title="System"
          live={sys && s ? <>
            <span className="flex items-center gap-1.5"><LiveDot state={sys.cpu.percent > 70 ? 'working' : 'awake'} />{s.hostname}</span>
            <span className="text-ink-mute">· {s.os} · up {fmtDur(sys.uptime)} · {s.cores} cores / {s.threads} threads · {fmtBytes(s.ram_total)} RAM</span>
          </> : <Skeleton className="h-4 w-72" />}
        />

        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-6">
          <Vital label="CPU" value={sys?.cpu.percent} hist={hist.cpu}
            sub={sys ? `load ${sys.cpu.load.map((l) => l.toFixed(2)).join(' · ')}` : undefined} />
          <Vital label="Memory" value={sys?.mem.percent} hist={hist.mem}
            sub={sys ? `${fmtBytes(sys.mem.used)} of ${fmtBytes(sys.mem.total)}` : undefined} />
          <Vital label={`Disk ${root?.mount ?? ''}`} value={root?.percent} hist={[]}
            sub={root ? `${fmtBytes(root.total - root.used)} free of ${fmtBytes(root.total)}` : sys ? 'no disks' : undefined} />
          <Stat label="Network" value={sys ? (lastDown ?? 0) + (lastUp ?? 0) : undefined} format={(n) => fmtRate(n)} spark={hist.down.length > 1 ? hist.down.map((d, i) => d + (hist.up[i] ?? 0)) : undefined}
            sub={sys ? `↓ ${fmtRate(lastDown ?? 0)} · ↑ ${fmtRate(lastUp ?? 0)}` : undefined} tone="warn" />
        </div>

        {!sys ? (
          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-44 rounded-2xl" />)}
          </div>
        ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(280px, 100%), 1fr))' }}>
          <Card title="Cores" aside={sys.cpu.freq_mhz ? `${(sys.cpu.freq_mhz / 1000).toFixed(2)} GHz` : undefined}>
            <div className="flex gap-1 h-24 items-end">
              {sys.cpu.per_core.map((c, i) => (
                <div key={i} className="flex-1 h-full bg-deck/70 rounded-md overflow-hidden flex items-end" title={`core ${i}: ${c.toFixed(0)}%`}>
                  <div className="w-full rounded-md transition-all duration-700" style={{ height: `${Math.max(2, c)}%`, background: `linear-gradient(0deg, color-mix(in srgb, ${hue(c)} 40%, transparent), ${hue(c)})` }} />
                </div>
              ))}
            </div>
            <div className="mt-2 text-[11px] font-mono text-ink-mute">{sys.cpu.per_core.length} cores · busiest {Math.max(...sys.cpu.per_core).toFixed(0)}%</div>
          </Card>

          <Card title="Memory" aside={`${fmtBytes(sys.mem.used)} / ${fmtBytes(sys.mem.total)}`}>
            <Bar pct={sys.mem.percent} label="RAM" sub={`${sys.mem.percent.toFixed(0)}% · ${fmtBytes(sys.mem.available)} free`} />
            {sys.mem.swap_total > 0 && (
              <Bar pct={sys.mem.swap_percent} label="Swap" sub={`${fmtBytes(sys.mem.swap_used)} / ${fmtBytes(sys.mem.swap_total)}`} />
            )}
            <Trace data={hist.mem} color={hue(sys.mem.percent)} className="w-full h-10 mt-2" />
          </Card>

          <Card title="Disks" aside={`${sys.disks.length} mounts`}>
            {/* subvolumes of one filesystem (btrfs) report the same used/total: one bar per volume */}
            {Object.values(sys.disks.reduce((m, d) => {
              const k = `${d.fstype}:${d.total}:${d.used}`
              ;(m[k] ??= { d, mounts: [] as string[] }).mounts.push(d.mount)
              return m
            }, {} as Record<string, { d: (typeof sys.disks)[number]; mounts: string[] }>)).map(({ d, mounts }) => (
              <Bar key={mounts[0]} pct={d.percent} label={`${mounts.slice(0, 3).join('  ')}${mounts.length > 3 ? `  +${mounts.length - 3}` : ''} · ${d.fstype}`} sub={`${fmtBytes(d.used)} / ${fmtBytes(d.total)}`} />
            ))}
          </Card>

          <Card title="Network" aside={sys.wifi.iface ?? undefined}>
            <div className="flex items-end gap-4 mb-2">
              <div><div className="text-[10.5px] uppercase tracking-[0.12em] text-ink-mute">down</div><div className="text-[18px] font-semibold text-ink tabular-nums">{fmtRate(lastDown ?? 0)}</div></div>
              <div><div className="text-[10.5px] uppercase tracking-[0.12em] text-ink-mute">up</div><div className="text-[18px] font-semibold text-ink tabular-nums">{fmtRate(lastUp ?? 0)}</div></div>
            </div>
            {hist.down.length > 1 && <Spark data={hist.down} tone="warn" className="w-full h-10 mb-2" />}
            <Row k="↑ sent (total)" v={fmtBytes(sys.net.sent)} />
            <Row k="↓ received (total)" v={fmtBytes(sys.net.recv)} />
            {sys.wifi.iface && (
              <div className="mt-3"><Bar pct={sys.wifi.quality ?? 0} label={`wifi ${sys.wifi.iface}`} sub={sys.wifi.signal_dbm != null ? `${sys.wifi.signal_dbm} dBm` : undefined} /></div>
            )}
          </Card>

          <Card title="GPU">
            {sys.gpu.length === 0 && <div className="text-[12px] text-ink-mute">none detected</div>}
            {sys.gpu.map((g, i) => (
              <div key={i} className="mb-2">
                <div className="text-[12px] text-ink-dim truncate mb-2">{g.name}</div>
                {g.util != null ? (
                  <>
                    <Bar pct={g.util} label="util" />
                    {g.mem_total ? <Bar pct={(g.mem_used! / g.mem_total) * 100} label="vram" sub={`${fmtBytes(g.mem_used)} / ${fmtBytes(g.mem_total)}`} /> : null}
                    {g.temp != null && <Row k="temp" v={`${g.temp}°C`} />}
                  </>
                ) : (
                  <div className="text-[11px] text-ink-mute font-mono">integrated · no live metrics</div>
                )}
              </div>
            ))}
          </Card>

          <Card title="Sensors" aside={sys.temps.length ? `hottest ${hot.toFixed(0)}°C` : undefined}>
            {s && <Row k="cpu" v={s.cpu} />}
            {sys.temps.slice(0, 8).map((t, i) => (
              <Row key={i} k={t.label} v={`${t.current.toFixed(0)}°C`} />
            ))}
          </Card>
        </div>
        )}

        <section className="mt-8">
          <SectionHead title="Processes" count={procs.length || undefined}
            right={<Tabs id="psort" value={psort as 'cpu' | 'mem'} onChange={setPsort} items={[{ id: 'cpu', label: 'by CPU' }, { id: 'mem', label: 'by memory' }] as const} />} />
          <Panel className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="text-left text-[10.5px] uppercase tracking-[0.12em] text-ink-mute border-b border-line">
                    <th className="px-4 py-2 font-medium w-[80px]">pid</th>
                    <th className="px-2 py-2 font-medium">name</th>
                    <th className="px-2 py-2 font-medium hidden sm:table-cell">user</th>
                    <th className="px-2 py-2 font-medium text-right w-[140px]">cpu</th>
                    <th className="px-4 py-2 font-medium text-right w-[140px]">mem</th>
                  </tr>
                </thead>
                <tbody>
                  {procs.map((p) => (
                    <tr key={p.pid} className="border-b border-line/30 last:border-b-0 hover:bg-deck-3/30">
                      <td className="px-4 py-1.5 font-mono text-ink-mute">{p.pid}</td>
                      <td className="px-2 py-1.5 text-ink-dim truncate max-w-[220px]">{p.name}</td>
                      <td className="px-2 py-1.5 text-ink-mute hidden sm:table-cell">{p.user}</td>
                      <td className="px-2 py-1.5"><Meter v={p.cpu} /></td>
                      <td className="px-4 py-1.5"><Meter v={p.mem} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!procs.length && <div className="p-4 space-y-2"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-4/5" /><Skeleton className="h-3 w-3/5" /></div>}
            </div>
          </Panel>
        </section>
      </div>
    </ScrollArea>
  )
}

/** a number with its own small bar — a process row reads at a glance */
function Meter({ v }: { v: number }) {
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="hidden sm:block w-16 h-1.5 rounded-full bg-deck/70 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, v)}%`, background: hue(v) }} />
      </div>
      <span className="font-mono tabular-nums w-10 text-right" style={{ color: v >= 70 ? hue(v) : 'var(--t-dim)' }}>{v.toFixed(1)}</span>
    </div>
  )
}
